#!/usr/bin/env python3
"""Install CLI and complete skill from one checked-out, immutable Git commit.

Standard-library only. This is a source bootstrap, intentionally outside the
installed Python package. No private export or workspace is read by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


PROVENANCE = ".specitout-install.json"


class BootstrapError(Exception):
    pass


def git(checkout: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True)
    if result.returncode:
        # Git stderr can contain authentication details or local file contents.
        raise BootstrapError("Cannot read the pinned checkout with Git; verify the checkout and revision.")
    return result.stdout


def canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", parsed.path)
            or any(part == ".." for part in parsed.path.split("/"))):
        raise BootstrapError("Repository must be a public HTTPS Git URL without credentials, query, or fragment.")
    return value.rstrip("/").removesuffix(".git")


def pinned_skill(checkout: Path, revision: str) -> dict[str, bytes]:
    files = {}
    listing = git(checkout, "ls-tree", "-rz", revision, "--", "skills/specitout/")
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, raw_path = item.split(b"\t", 1)
        mode, kind, object_id = meta.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise BootstrapError("Pinned skill must contain regular files only; symlinks are unsupported.")
        try:
            path = PurePosixPath(raw_path.decode("utf-8")).relative_to("skills/specitout")
        except (ValueError, UnicodeDecodeError) as exc:
            raise BootstrapError("Unsupported path in pinned skill.") from exc
        if path.is_absolute() or ".." in path.parts or path.as_posix() == PROVENANCE:
            raise BootstrapError("Unsafe or reserved path in pinned skill.")
        files[path.as_posix()] = git(checkout, "cat-file", "blob", object_id.decode("ascii"))
    if "SKILL.md" not in files:
        raise BootstrapError("Pinned revision does not contain skills/specitout/SKILL.md.")
    return files


def inspect_target(target: Path, files: dict[str, bytes], provenance: dict) -> bool:
    if target.is_symlink():
        raise BootstrapError("Refusing existing skill symlink; select a different skill directory.")
    if not target.exists():
        return False
    message = "Refusing existing skill: provenance, files, or local edits differ. Preserve it and choose another directory, or explicitly remove it before installing."
    if not target.is_dir():
        raise BootstrapError(message)
    expected = set(files) | {PROVENANCE}
    actual = set()
    for path in target.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise BootstrapError(message)
        if path.is_file():
            actual.add(path.relative_to(target).as_posix())
    if actual != expected:
        raise BootstrapError(message)
    try:
        recorded = json.loads((target / PROVENANCE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootstrapError(message) from exc
    if recorded != provenance or any((target / name).read_bytes() != value for name, value in files.items()):
        raise BootstrapError(message)
    return True


def bootstrap(args: argparse.Namespace) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", args.revision):
        raise BootstrapError("--revision must be a full immutable Git commit hash, not a branch or tag.")
    repository = canonical_url(args.repo_url)
    checkout = Path(args.checkout).expanduser().resolve(strict=True)
    revision = args.revision.lower()
    if git(checkout, "rev-parse", "HEAD").decode().strip().lower() != revision:
        raise BootstrapError("Checkout HEAD does not match --revision; check out the resolved commit first.")
    if canonical_url(git(checkout, "remote", "get-url", "origin").decode().strip()) != repository:
        raise BootstrapError("Checkout origin does not match --repo-url.")
    files = pinned_skill(checkout, revision)
    parent = Path(args.skill_dir).expanduser().resolve()
    target = parent / "specitout"
    provenance = {
        "schema_version": 1,
        "repository": args.repo_url.rstrip("/"),
        "revision": revision,
        "installer": "uv tool install",
        "files_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())},
    }
    existing = inspect_target(target, files, provenance)
    command = ["uv", "tool", "install", "--force", f"git+{args.repo_url.rstrip('/')}@{revision}"]
    plan = {"revision": revision, "repository": args.repo_url.rstrip("/"), "cli_command": command,
            "skill_path": str(target), "skill_files": sorted(files),
            "skill_action": "keep identical installation" if existing else "install", "dry_run": args.dry_run}
    if args.dry_run:
        return plan
    if shutil.which("uv") is None:
        raise BootstrapError("uv is missing; install uv using its official platform instructions, then retry.")
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / ".specitout-bootstrap.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise BootstrapError("Another bootstrap may be running. Inspect the skill-directory lock before retrying.") from exc
    try:
        # Recheck under the lock before the first persistent tool mutation.
        existing = inspect_target(target, files, provenance)
        result = subprocess.run(command, stdout=sys.stderr, stderr=sys.stderr)
        if result.returncode:
            raise BootstrapError("uv tool installation failed; the skill was not changed.")
        if not existing:
            target.mkdir()  # Exclusive creation: never overwrite a competing directory.
            try:
                for name, value in files.items():
                    output = target / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with output.open("xb") as stream:
                        stream.write(value)
                with (target / PROVENANCE).open("x", encoding="utf-8") as stream:
                    json.dump(provenance, stream, indent=2, sort_keys=True)
                    stream.write("\n")
            except BaseException:
                shutil.rmtree(target)
                raise
    finally:
        lock.rmdir()
    plan["installed"] = True
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, help="Local clone checked out at --revision")
    parser.add_argument("--repo-url", required=True, help="Public HTTPS origin URL")
    parser.add_argument("--revision", required=True, help="Full resolved commit hash")
    parser.add_argument("--skill-dir", required=True, help="Explicit host-supported parent directory for specitout/")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON plan without installing or creating directories")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(bootstrap(args), indent=2, sort_keys=True))
        return 0
    except (BootstrapError, OSError, ValueError):
        # Details for known errors are safe; unexpected filesystem errors may contain private paths.
        exc = sys.exc_info()[1]
        message = str(exc) if isinstance(exc, BootstrapError) else "Filesystem operation failed; inspect the selected checkout and skill directory permissions."
        print(f"Bootstrap failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
