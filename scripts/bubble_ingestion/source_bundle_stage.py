from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion.source_bundle import (
    SOURCE_BUNDLE_LOCATION_LOCAL_FILE,
    SOURCE_BUNDLE_LOCATION_STORAGE,
    _artifact_entry,
    _build_manifest_identity_payload,
    _logical_plugin_supplement_path,
    _manifest_identity_hash,
    _upload_and_record,
    make_storage_ref,
    merge_plugin_supplement_paths,
    source_bundle_manifest_alias_object_path,
    source_bundle_manifest_object_path,
)
from bubble_ingestion_contract import (
    BUBBLE_SOURCE_ARTIFACTS_BUCKET,
    OVERLAY_FILENAME_BY_KIND,
    compute_content_hash,
    overlay_artifact_path,
    storage_object_path_for_artifact,
)


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
) -> dict[str, object]:
    export_path = export_path.resolve()
    overlay_dir = overlay_dir.resolve()
    manifest_out = manifest_out.resolve() if manifest_out is not None else None
    plugin_supplements = merge_plugin_supplement_paths(plugin_supplements)
    if not sync_source_evidence and manifest_out is None:
        raise ValueError("stage_source_bundle requires manifest_out when sync_source_evidence is disabled")

    export_logical_path = Path(app_slug) / "bubble_export" / export_path.name
    export_storage_object_path = storage_object_path_for_artifact(
        app_slug=app_slug,
        version_label=version_label,
        role="bubble_export",
        local_path=export_path,
    )
    if sync_source_evidence:
        _upload_and_record(backend, local_path=export_path, storage_object_path=export_storage_object_path)

    overlays: list[dict[str, object]] = []
    for kind, filename in sorted(OVERLAY_FILENAME_BY_KIND.items()):
        local_path = overlay_dir / filename
        if not local_path.exists():
            continue
        storage_object_path = storage_object_path_for_artifact(
            app_slug=app_slug,
            version_label=version_label,
            role="overlay_artifact",
            local_path=local_path,
            overlay_type={
                "privacy_rules_as_is": "privacy_rules",
                "backend_workflows_as_is": "backend_workflows_as_is",
                "schema_as_is": "schema_prisma",
                "database_schema_as_is": "database_schema_markdown",
            }[kind],
        )
        if sync_source_evidence:
            _upload_and_record(backend, local_path=local_path, storage_object_path=storage_object_path)
        overlays.append(
            _artifact_entry(
                role="overlay_artifact",
                kind=kind,
                logical_path=overlay_artifact_path(app_slug, kind).as_posix(),
                local_path=local_path,
                storage_object_path=storage_object_path,
                location_kind=SOURCE_BUNDLE_LOCATION_STORAGE if sync_source_evidence else SOURCE_BUNDLE_LOCATION_LOCAL_FILE,
            )
        )

    supplements: list[dict[str, object]] = []
    for local_path in plugin_supplements:
        local_path = local_path.resolve()
        storage_object_path = storage_object_path_for_artifact(
            app_slug=app_slug,
            version_label=version_label,
            role="plugin_supplement",
            local_path=local_path,
            path_hash=compute_content_hash(local_path),
        )
        if sync_source_evidence:
            _upload_and_record(backend, local_path=local_path, storage_object_path=storage_object_path)
        supplements.append(
            _artifact_entry(
                role="plugin_supplement",
                logical_path=(Path(app_slug) / "plugin_supplements" / _logical_plugin_supplement_path(local_path)).as_posix(),
                local_path=local_path,
                storage_object_path=storage_object_path,
                location_kind=SOURCE_BUNDLE_LOCATION_STORAGE if sync_source_evidence else SOURCE_BUNDLE_LOCATION_LOCAL_FILE,
            )
        )

    export_entry = _artifact_entry(
        role="bubble_export",
        logical_path=export_logical_path.as_posix(),
        local_path=export_path,
        storage_object_path=export_storage_object_path,
        location_kind=SOURCE_BUNDLE_LOCATION_STORAGE if sync_source_evidence else SOURCE_BUNDLE_LOCATION_LOCAL_FILE,
    )
    manifest_identity_payload = _build_manifest_identity_payload(
        app_slug=app_slug,
        version_label=version_label,
        export_entry=export_entry,
        overlays=overlays,
        supplements=supplements,
    )
    manifest_id = _manifest_identity_hash(manifest_identity_payload)
    manifest_storage_object_path = source_bundle_manifest_object_path(app_slug, version_label, manifest_id)
    manifest_alias_object_path = source_bundle_manifest_alias_object_path(app_slug, version_label)
    if sync_source_evidence:
        manifest_ref = make_storage_ref(BUBBLE_SOURCE_ARTIFACTS_BUCKET, manifest_storage_object_path)
        manifest_alias_ref = make_storage_ref(BUBBLE_SOURCE_ARTIFACTS_BUCKET, manifest_alias_object_path)
    else:
        assert manifest_out is not None
        manifest_ref = manifest_out.as_posix()
        manifest_alias_ref = manifest_out.as_posix()
    manifest = {
        **manifest_identity_payload,
        "manifest_ref": manifest_ref,
        "manifest_alias_ref": manifest_alias_ref,
        "manifest_storage_bucket": BUBBLE_SOURCE_ARTIFACTS_BUCKET,
        "manifest_storage_object_path": manifest_storage_object_path,
        "manifest_alias_storage_object_path": manifest_alias_object_path,
        "manifest_location_kind": SOURCE_BUNDLE_LOCATION_STORAGE if sync_source_evidence else SOURCE_BUNDLE_LOCATION_LOCAL_FILE,
        "evidence_sync_enabled": sync_source_evidence,
    }
    manifest_payload = json.dumps(manifest, indent=2) + "\n"
    if sync_source_evidence:
        backend.upload_object(
            bucket=BUBBLE_SOURCE_ARTIFACTS_BUCKET,
            object_path=manifest_storage_object_path,
            payload=manifest_payload.encode("utf-8"),
        )
        backend.upload_object(
            bucket=BUBBLE_SOURCE_ARTIFACTS_BUCKET,
            object_path=manifest_alias_object_path,
            payload=manifest_payload.encode("utf-8"),
        )
    if manifest_out is not None:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(manifest_payload)
    return manifest
