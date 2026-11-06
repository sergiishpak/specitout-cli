"""Private workspace identity, stable source copies, and process-safe ownership."""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import re
import shutil
import tomllib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from specitout.runtime_errors import SpecItOutRuntimeError


@dataclass(frozen=True)
class Workspace:
    root: Path
    app_slug: str

    @property
    def data_root(self) -> Path:
        return self.root / '.specitout'


CURRENT_PROJECT = contextvars.ContextVar('specitout_project', default=None)
READ_ONLY_RUNTIME = contextvars.ContextVar("specitout_read_only_runtime", default=False)
_LOCKED = contextvars.ContextVar('specitout_locked', default=False)


class WorkspaceBusyError(SpecItOutRuntimeError):
    pass


def _check_owned_dirs(root: Path):
    for name in ("exports", ".specitout", "reports"):
        if (root / name).is_symlink():
            raise SpecItOutRuntimeError(f"Workspace-owned {name} must be a local directory, not a symlink.")


def _slug(value: str) -> str:
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', value):
        raise SpecItOutRuntimeError('Application slug must be 1–80 lowercase letters, digits, underscores or hyphens.')
    return value


def load_project(root: Path) -> Workspace:
    _check_owned_dirs(root)
    try:
        data = tomllib.loads((root / 'specitout.toml').read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SpecItOutRuntimeError(f'Cannot read workspace manifest at {root / "specitout.toml"}.') from exc
    if data.get('schema_version') != 1:
        raise SpecItOutRuntimeError('Unsupported workspace schema_version; use a compatible CLI or upgrade the workspace.')
    return Workspace(root.resolve(), _slug(str(data.get('app_slug', ''))))


def discover_project(start: Path) -> Workspace | None:
    start = start.expanduser().resolve()
    for root in (start, *start.parents):
        if (root / 'specitout.toml').is_file():
            return load_project(root)
    return None


def init_project(path: Path | str, app_slug: str) -> Workspace:
    root = Path(path).expanduser().resolve()
    slug = _slug(app_slug)
    # Exports and databases belong outside the public tool's source checkout.
    for ancestor in (root, *root.parents):
        if (ancestor / 'pyproject.toml').is_file() and (ancestor / 'scripts' / 'specitout').is_dir():
            raise SpecItOutRuntimeError('Create the private workspace outside the SpecItOut source checkout.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _check_owned_dirs(root)
    manifest = root / 'specitout.toml'
    if manifest.exists():
        project = load_project(root)
        if project.app_slug != slug:
            raise SpecItOutRuntimeError('Existing workspace application scope differs; choose a new folder.')
        return project
    for name in ('exports', '.specitout', 'reports'):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    with manifest.open('x') as stream:
        stream.write(f'schema_version = 1\napp_slug = {json.dumps(slug)}\n')
    manifest.chmod(0o600)
    return Workspace(root, slug)


@contextlib.contextmanager
def select_project(path: str | None):
    project = load_project(Path(path).expanduser().resolve()) if path else discover_project(Path.cwd())
    override = os.environ.get('SPECITOUT_DATA_ROOT')
    if project and override and Path(override).expanduser().resolve() != project.data_root:
        raise SpecItOutRuntimeError('SPECITOUT_DATA_ROOT conflicts with selected workspace; unset it or select its workspace.')
    token = CURRENT_PROJECT.set(project)
    try:
        yield project
    finally:
        CURRENT_PROJECT.reset(token)


def validate_export(path: Path) -> None:
    try:
        with path.open() as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecItOutRuntimeError('Cannot read export: expected a UTF-8 Bubble application JSON file.') from exc
    domains = ('pages', 'element_definitions', 'mobile_views', 'api', 'user_types', 'option_sets')
    if not isinstance(data, dict) or not any(key in data for key in domains):
        raise SpecItOutRuntimeError('Expected Bubble export object with pages, api, user_types or another application domain.')
    maps = (*domains, "styles", "comments", "settings", "_index")
    if any(key in data and not isinstance(data[key], dict) for key in maps):
        raise SpecItOutRuntimeError('Bubble export domains must be JSON objects keyed by identifier, not arrays.')
    settings = data.get('settings', {})
    if any(key in settings and not isinstance(settings[key], dict) for key in ('client_safe', 'secure')):
        raise SpecItOutRuntimeError('Bubble settings client_safe and secure must be JSON objects.')


def stage_export(project: Workspace, source: Path, version: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', version):
        raise SpecItOutRuntimeError('Export version must be 1–100 letters, digits, dots, underscores or hyphens.')
    _check_owned_dirs(project.root)
    validate_export(source)
    destination = project.root / 'exports' / f'{version}.json'
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if destination.is_symlink():
        raise SpecItOutRuntimeError("Stable export evidence must be a regular file, not a symlink.")
    if destination.exists():
        if digest(destination) == digest(source):
            return destination
        raise SpecItOutRuntimeError('This export version already has different source content; use a new version.')
    expected_hash = digest(source)
    temporary = None
    try:
        with source.open('rb') as src, tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.copy-', delete=False) as dst:
            temporary = Path(dst.name)
            shutil.copyfileobj(src, dst)
        if digest(temporary) != expected_hash:
            raise SpecItOutRuntimeError('Source changed during copying; retry with a stable export file.')
        try:
            os.link(temporary, destination)  # Atomic publication without replacing existing evidence.
        except FileExistsError:
            if digest(destination) != expected_hash:
                raise SpecItOutRuntimeError('This export version already has different source content; use a new version.')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return destination


@contextlib.contextmanager
def operation_lock(data_root: Path):
    """flock is released by the OS after interruption; a leftover file is harmless."""
    if _LOCKED.get():
        yield
        return
    try:
        import fcntl
    except ImportError as exc:
        raise SpecItOutRuntimeError('Native Windows is unsupported; use Linux or macOS.') from exc
    data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data_root / 'operation.lock').open('a+') as stream:
        os.chmod(stream.name, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkspaceBusyError('Workspace is processing another command; wait for it to finish before retrying.') from exc
        token = _LOCKED.set(True)
        try:
            yield
        finally:
            _LOCKED.reset(token)
            fcntl.flock(stream, fcntl.LOCK_UN)
