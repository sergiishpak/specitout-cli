from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MAX_SINGLE_UPLOAD_BYTES = 40 * 1024 * 1024
BUBBLE_EXPORT_MAX_SINGLE_UPLOAD_BYTES = 16 * 1024 * 1024
PRESERVED_ARTIFACT_MAX_SINGLE_UPLOAD_BYTES = 8 * 1024 * 1024
CHUNK_MANIFEST_STORAGE_ENCODING = "chunk_manifest_v1"


@dataclass(frozen=True)
class PlannedArtifactUpload:
    bucket: str
    object_path: str
    payload: bytes


def _content_hash(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def chunk_manifest_object_path(storage_object_path: str) -> str:
    return f"{storage_object_path}.chunk-manifest.json"


def chunk_object_path(storage_object_path: str, *, chunk_index: int, chunk_count: int) -> str:
    return f"{storage_object_path}.parts/{chunk_index + 1:04d}-of-{chunk_count:04d}"


def _source_evidence_row(
    *,
    export_id: str,
    artifact: Any,
    storage_object_path: str,
    metadata_json: dict[str, Any],
) -> dict[str, Any]:
    return {
        "export_id": export_id,
        "evidence_role": artifact.role,
        "storage_bucket": artifact.storage_bucket,
        "storage_object_path": storage_object_path,
        "content_hash": artifact.content_hash,
        "source_path": artifact.source_path,
        "metadata_json": metadata_json,
    }


def _artifact_upload_limit_bytes(artifact: Any, default_limit_bytes: int) -> int:
    if artifact.role == "bubble_export":
        return max(default_limit_bytes, BUBBLE_EXPORT_MAX_SINGLE_UPLOAD_BYTES)
    return default_limit_bytes


def plan_artifact_preservation(
    *,
    export_id: str,
    inventory: Any,
    max_single_upload_bytes: int = PRESERVED_ARTIFACT_MAX_SINGLE_UPLOAD_BYTES,
) -> tuple[list[PlannedArtifactUpload], list[dict[str, Any]]]:
    uploads: list[PlannedArtifactUpload] = []
    source_evidence_rows: list[dict[str, Any]] = []

    for artifact in inventory.artifacts:
        payload = Path(artifact.local_path).read_bytes()
        artifact_metadata = dict(artifact.metadata_json)
        artifact_limit_bytes = _artifact_upload_limit_bytes(artifact, max_single_upload_bytes)
        if len(payload) <= artifact_limit_bytes:
            uploads.append(
                PlannedArtifactUpload(
                    bucket=artifact.storage_bucket,
                    object_path=artifact.storage_object_path,
                    payload=payload,
                )
            )
            source_evidence_rows.append(
                _source_evidence_row(
                    export_id=export_id,
                    artifact=artifact,
                    storage_object_path=artifact.storage_object_path,
                    metadata_json=artifact_metadata,
                )
            )
            continue

        chunk_count = (len(payload) + artifact_limit_bytes - 1) // artifact_limit_bytes
        chunk_descriptors: list[dict[str, Any]] = []
        for chunk_index in range(chunk_count):
            offset = chunk_index * artifact_limit_bytes
            chunk_payload = payload[offset : offset + artifact_limit_bytes]
            object_path = chunk_object_path(
                artifact.storage_object_path,
                chunk_index=chunk_index,
                chunk_count=chunk_count,
            )
            uploads.append(
                PlannedArtifactUpload(
                    bucket=artifact.storage_bucket,
                    object_path=object_path,
                    payload=chunk_payload,
                )
            )
            chunk_descriptors.append(
                {
                    "storage_object_path": object_path,
                    "byte_offset": offset,
                    "byte_length": len(chunk_payload),
                    "content_hash": _content_hash(chunk_payload),
                }
            )

        manifest_object_path = chunk_manifest_object_path(artifact.storage_object_path)
        manifest_payload = {
            "storage_encoding": CHUNK_MANIFEST_STORAGE_ENCODING,
            "artifact_role": artifact.role,
            "source_path": artifact.source_path,
            "original_storage_object_path": artifact.storage_object_path,
            "original_content_hash": artifact.content_hash,
            "original_size_bytes": len(payload),
            "chunk_count": chunk_count,
            "chunk_size_bytes": artifact_limit_bytes,
            "chunks": chunk_descriptors,
        }
        uploads.append(
            PlannedArtifactUpload(
                bucket=artifact.storage_bucket,
                object_path=manifest_object_path,
                payload=json.dumps(manifest_payload, sort_keys=True).encode("utf-8"),
            )
        )
        source_evidence_rows.append(
            _source_evidence_row(
                export_id=export_id,
                artifact=artifact,
                storage_object_path=manifest_object_path,
                metadata_json={
                    **artifact_metadata,
                    "storage_encoding": CHUNK_MANIFEST_STORAGE_ENCODING,
                    "original_storage_object_path": artifact.storage_object_path,
                    "original_size_bytes": len(payload),
                    "chunk_count": chunk_count,
                    "chunk_size_bytes": artifact_limit_bytes,
                },
            )
        )

    return uploads, source_evidence_rows
