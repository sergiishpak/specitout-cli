from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion_contract import (
    BUBBLE_SOURCE_ARTIFACTS_BUCKET,
    OVERLAY_FILENAME_BY_KIND,
    compute_content_hash,
    make_base_prefix,
    overlay_artifact_path,
    storage_object_path_for_artifact,
)


SOURCE_BUNDLE_FORMAT = "bubble-source-bundle-v1"
SOURCE_BUNDLE_MANIFEST_ROLE = "source_bundle_manifest"
SOURCE_BUNDLE_LOCATION_STORAGE = "storage_object"
SOURCE_BUNDLE_LOCATION_LOCAL_FILE = "local_file"


@dataclass(frozen=True)
class MaterializedSourceBundle:
    manifest: dict[str, Any]
    manifest_ref: str
    manifest_alias_ref: str
    manifest_local_path: Path
    manifest_storage_bucket: str
    manifest_storage_object_path: str
    manifest_alias_storage_object_path: str
    manifest_logical_path: str
    manifest_content_hash: str
    export_path: Path
    export_entry: dict[str, Any]
    bundle_root: Path
    overlay_entries_by_kind: dict[str, dict[str, Any]]
    overlay_paths_by_kind: dict[str, Path]
    plugin_supplement_entries: list[dict[str, Any]]
    plugin_supplement_paths: list[Path]


def _artifact_entry(
    *,
    role: str,
    logical_path: str,
    local_path: Path,
    storage_object_path: str,
    kind: str | None = None,
    location_kind: str = SOURCE_BUNDLE_LOCATION_STORAGE,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "role": role,
        "logical_path": logical_path,
        "storage_bucket": BUBBLE_SOURCE_ARTIFACTS_BUCKET,
        "storage_object_path": storage_object_path,
        "storage_ref": (
            make_storage_ref(BUBBLE_SOURCE_ARTIFACTS_BUCKET, storage_object_path)
            if location_kind == SOURCE_BUNDLE_LOCATION_STORAGE
            else local_path.resolve().as_posix()
        ),
        "content_hash": compute_content_hash(local_path),
        "location_kind": location_kind,
        "local_source_path": local_path.resolve().as_posix(),
    }
    if kind is not None:
        entry["kind"] = kind
    return entry


def _upload_and_record(
    backend: BackendProtocol,
    *,
    local_path: Path,
    storage_object_path: str,
) -> None:
    backend.upload_object(
        bucket=BUBBLE_SOURCE_ARTIFACTS_BUCKET,
        object_path=storage_object_path,
        payload=local_path.read_bytes(),
    )


def _logical_plugin_supplement_path(local_path: Path) -> str:
    parent_label = local_path.parent.name or "root"
    source_hash = hashlib.sha256(local_path.resolve().as_posix().encode("utf-8")).hexdigest()[:12]
    return Path(f"{parent_label}--{source_hash}") / local_path.name


def make_storage_ref(bucket: str, object_path: str) -> str:
    return f"storage://{bucket}/{object_path}"


def parse_storage_ref(storage_ref: str) -> tuple[str, str]:
    prefix = "storage://"
    if not storage_ref.startswith(prefix):
        raise ValueError(f"Unsupported storage ref: {storage_ref!r}")
    bucket_and_path = storage_ref[len(prefix) :]
    bucket, sep, object_path = bucket_and_path.partition("/")
    if not bucket or not sep or not object_path:
        raise ValueError(f"Unsupported storage ref: {storage_ref!r}")
    return bucket, object_path


def source_bundle_manifest_logical_path(app_slug: str) -> str:
    return (Path(app_slug) / "source_bundle" / "manifest.json").as_posix()


def source_bundle_manifest_alias_object_path(app_slug: str, version_label: str) -> str:
    return f"{make_base_prefix(app_slug, version_label)}/source_bundle/manifest.json"


def source_bundle_manifest_object_path(app_slug: str, version_label: str, manifest_id: str) -> str:
    return f"{make_base_prefix(app_slug, version_label)}/source_bundle/manifest--{manifest_id}.json"


def _build_manifest_identity_payload(
    *,
    app_slug: str,
    version_label: str,
    export_entry: dict[str, Any],
    overlays: list[dict[str, Any]],
    supplements: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": SOURCE_BUNDLE_FORMAT,
        "app_slug": app_slug,
        "version_label": version_label,
        "manifest_logical_path": source_bundle_manifest_logical_path(app_slug),
        "export": export_entry,
        "overlays": overlays,
        "plugin_supplements": supplements,
    }


def _manifest_identity_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def merge_plugin_supplement_paths(
    *groups: list[Path],
    error_cls: type[Exception] = ValueError,
) -> list[Path]:
    merged: list[Path] = []
    seen: set[str] = set()
    for group in groups:
        for path in group:
            resolved = Path(path).resolve()
            if not resolved.exists():
                raise error_cls(f"Missing plugin supplement: {resolved}")
            if not resolved.is_file():
                raise error_cls(f"Expected plugin supplement to be a file: {resolved}")
            key = compute_content_hash(resolved)
            if key in seen:
                continue
            seen.add(key)
            merged.append(resolved)
    return merged


def stage_source_bundle(
    *,
    backend: BackendProtocol,
    app_slug: str,
    version_label: str,
    export_path: Path,
    overlay_dir: Path,
    plugin_supplements: list[Path],
    manifest_out: Path | None,
    sync_source_evidence: bool = True,
) -> dict[str, Any]:
    from bubble_ingestion.source_bundle_stage import stage_source_bundle as _stage_source_bundle

    return _stage_source_bundle(
        backend=backend,
        app_slug=app_slug,
        version_label=version_label,
        export_path=export_path,
        overlay_dir=overlay_dir,
        plugin_supplements=plugin_supplements,
        manifest_out=manifest_out,
        sync_source_evidence=sync_source_evidence,
    )


def load_source_bundle_manifest_payload(payload: str, *, source: str) -> dict[str, Any]:
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or manifest.get("format") != SOURCE_BUNDLE_FORMAT:
        raise ValueError(f"Unsupported source bundle manifest: {source}")
    return manifest


def validate_source_bundle_scope(
    manifest: dict[str, Any],
    *,
    app_slug: str,
    version_label: str,
    error_cls: type[Exception] = ValueError,
) -> None:
    manifest_app_slug = manifest.get("app_slug")
    manifest_version_label = manifest.get("version_label")
    if manifest_app_slug != app_slug:
        raise error_cls(
            f"source bundle manifest app_slug {manifest_app_slug!r} does not match requested app_slug {app_slug!r}"
        )
    if manifest_version_label != version_label:
        raise error_cls(
            "source bundle manifest version_label "
            f"{manifest_version_label!r} does not match requested version_label {version_label!r}"
        )


def _resolve_bundle_member_path(
    *,
    bundle_root: Path,
    logical_path: str,
    error_cls: type[Exception],
) -> Path:
    local_path = (bundle_root / logical_path).resolve()
    try:
        local_path.relative_to(bundle_root.resolve())
    except ValueError as exc:
        raise error_cls(f"source bundle logical_path {logical_path!r} escapes outside the bundle cache") from exc
    return local_path


def _resolve_manifest_locator(
    *,
    backend: BackendProtocol,
    manifest_locator: str | Path,
    cache_root: Path,
    error_cls: type[Exception],
) -> tuple[dict[str, Any], Path, str, str, str, str, str]:
    locator = manifest_locator.as_posix() if isinstance(manifest_locator, Path) else str(manifest_locator)
    manifest_cache_path = cache_root / "_source_bundle" / "manifest.json"
    manifest_cache_path.parent.mkdir(parents=True, exist_ok=True)

    if locator.startswith("storage://"):
        locator_bucket, locator_object_path = parse_storage_ref(locator)
        payload = backend.download_object(bucket=locator_bucket, object_path=locator_object_path)
        manifest_cache_path.write_bytes(payload)
        manifest_payload = payload.decode("utf-8")
        manifest = load_source_bundle_manifest_payload(manifest_payload, source=locator)
        manifest_ref = str(manifest.get("manifest_ref") or locator)
        bucket, object_path = parse_storage_ref(manifest_ref)
        local_path = manifest_cache_path
    else:
        local_path = Path(locator).resolve()
        manifest_payload = local_path.read_text()
        manifest = load_source_bundle_manifest_payload(manifest_payload, source=local_path.as_posix())
        manifest_ref = str(manifest.get("manifest_ref") or local_path.as_posix())
        if manifest_ref.startswith("storage://"):
            bucket, object_path = parse_storage_ref(manifest_ref)
        else:
            bucket = str(manifest.get("manifest_storage_bucket") or BUBBLE_SOURCE_ARTIFACTS_BUCKET)
            object_path = str(
                manifest.get("manifest_storage_object_path")
                or source_bundle_manifest_alias_object_path(
                    str(manifest["app_slug"]),
                    str(manifest["version_label"]),
                )
            )

    manifest_logical_path = str(
        manifest.get("manifest_logical_path")
        or source_bundle_manifest_logical_path(str(manifest["app_slug"]))
    )
    manifest_alias_ref = str(manifest.get("manifest_alias_ref") or manifest_ref)
    return (
        manifest,
        local_path,
        manifest_ref,
        manifest_alias_ref,
        bucket,
        object_path,
        manifest_logical_path,
    )


def _download_entry_to_path(
    *,
    backend: BackendProtocol,
    entry: dict[str, Any],
    local_path: Path,
    error_cls: type[Exception],
) -> Path:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if entry.get("location_kind") == SOURCE_BUNDLE_LOCATION_LOCAL_FILE:
        source_path = Path(str(entry["local_source_path"])).resolve()
        if not source_path.exists():
            raise error_cls(f"source bundle local artifact is missing: {source_path}")
        local_path.write_bytes(source_path.read_bytes())
    else:
        payload = backend.download_object(
            bucket=entry["storage_bucket"],
            object_path=entry["storage_object_path"],
        )
        local_path.write_bytes(payload)
    expected_hash = entry.get("content_hash")
    if expected_hash and compute_content_hash(local_path) != expected_hash:
        raise error_cls(
            "source bundle artifact content_hash mismatch for "
            f"{entry.get('logical_path', local_path.as_posix())!r}"
        )
    return local_path


def materialize_source_bundle(
    *,
    backend: BackendProtocol,
    manifest_locator: str | Path,
    cache_root: Path,
    clear_cache: bool = False,
    error_cls: type[Exception] = ValueError,
) -> MaterializedSourceBundle:
    cache_root = cache_root.resolve()
    if clear_cache and cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    (
        manifest,
        manifest_local_path,
        manifest_ref,
        manifest_alias_ref,
        manifest_storage_bucket,
        manifest_storage_object_path,
        manifest_logical_path,
    ) = _resolve_manifest_locator(
        backend=backend,
        manifest_locator=manifest_locator,
        cache_root=cache_root,
        error_cls=error_cls,
    )
    bundle_root = cache_root / "bundle"
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    export_entry = manifest["export"]
    export_path = _resolve_bundle_member_path(
        bundle_root=bundle_root,
        logical_path=str(export_entry["logical_path"]),
        error_cls=error_cls,
    )
    _download_entry_to_path(
        backend=backend,
        entry=export_entry,
        local_path=export_path,
        error_cls=error_cls,
    )

    overlay_entries_by_kind: dict[str, dict[str, Any]] = {}
    overlay_paths_by_kind: dict[str, Path] = {}
    for overlay in manifest.get("overlays") or []:
        local_path = _resolve_bundle_member_path(
            bundle_root=bundle_root,
            logical_path=str(overlay["logical_path"]),
            error_cls=error_cls,
        )
        _download_entry_to_path(
            backend=backend,
            entry=overlay,
            local_path=local_path,
            error_cls=error_cls,
        )
        overlay_entries_by_kind[str(overlay["kind"])] = overlay
        overlay_paths_by_kind[str(overlay["kind"])] = local_path

    supplement_paths: list[Path] = []
    supplement_entries = list(manifest.get("plugin_supplements") or [])
    for supplement in supplement_entries:
        local_path = _resolve_bundle_member_path(
            bundle_root=bundle_root,
            logical_path=str(supplement["logical_path"]),
            error_cls=error_cls,
        )
        _download_entry_to_path(
            backend=backend,
            entry=supplement,
            local_path=local_path,
            error_cls=error_cls,
        )
        supplement_paths.append(local_path)

    return MaterializedSourceBundle(
        manifest=manifest,
        manifest_ref=manifest_ref,
        manifest_alias_ref=manifest_alias_ref,
        manifest_local_path=manifest_local_path,
        manifest_storage_bucket=manifest_storage_bucket,
        manifest_storage_object_path=manifest_storage_object_path,
        manifest_alias_storage_object_path=str(
            manifest.get("manifest_alias_storage_object_path")
            or (
                parse_storage_ref(manifest_alias_ref)[1]
                if manifest_alias_ref.startswith("storage://")
                else manifest_storage_object_path
            )
        ),
        manifest_logical_path=manifest_logical_path,
        manifest_content_hash=compute_content_hash(manifest_local_path),
        export_path=export_path,
        export_entry=export_entry,
        bundle_root=bundle_root,
        overlay_entries_by_kind=overlay_entries_by_kind,
        overlay_paths_by_kind=overlay_paths_by_kind,
        plugin_supplement_entries=supplement_entries,
        plugin_supplement_paths=supplement_paths,
    )
