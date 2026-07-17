#!/usr/bin/env python3
"""Shared ingestion-contract helpers for Bubble MCP artifact planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


BUBBLE_SOURCE_ARTIFACTS_BUCKET = "bubble-source-artifacts"

EVIDENCE_ROLE_BUBBLE_EXPORT = "bubble_export"
EVIDENCE_ROLE_CONTEXT_PACK = "context_pack"
EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST = "source_bundle_manifest"
EVIDENCE_ROLE_VERIFICATION_REPORT = "verification_report"
EVIDENCE_ROLE_GAP_REPORT = "gap_report"
EVIDENCE_ROLE_OVERLAY_ARTIFACT = "overlay_artifact"
EVIDENCE_ROLE_PLUGIN_SUPPLEMENT = "plugin_supplement"
EVIDENCE_ROLE_SEMANTIC_INDEX = "semantic_index"
EVIDENCE_ROLE_ENTITY_CATALOG = "entity_catalog"
EVIDENCE_ROLE_EDGE_INDEX = "edge_index"
EVIDENCE_ROLE_UNRESOLVED_EDGES = "unresolved_edges"

CANONICAL_UNIQUE_EVIDENCE_ROLES = frozenset(
    {
        EVIDENCE_ROLE_BUBBLE_EXPORT,
        EVIDENCE_ROLE_CONTEXT_PACK,
    }
)

REQUIRED_PACK_RELATIVE_PATHS = (
    "structural/indexes/manifest.json",
    "structural/indexes/entity_catalog.jsonl",
    "structural/indexes/edge_index.jsonl",
    "structural/indexes/unresolved_edges.json",
    "reports/verification_report.json",
)

PRESERVED_SEMANTIC_INDEX_FILENAMES = (
    "app_settings_summary.json",
    "capability_index.json",
    "condition_index.json",
    "custom_state_index.json",
    "data_api_surface.json",
    "data_source_index.json",
    "event_index.json",
    "expression_index.json",
    "field_index.json",
    "glossary.json",
    "integration_index.json",
    "option_value_index.json",
    "permission_surface_index.json",
    "public_api_workflows.json",
    "query_hints.json",
    "reverse_usage_index.json",
)

PRESERVED_GAP_REPORT_PATHS = (
    "reports/gap_report.json",
    "reports/gap_report.md",
)

OVERLAY_TYPE_BY_KIND = {
    "privacy_rules_as_is": "privacy_rules",
    "backend_workflows_as_is": "backend_workflows_as_is",
    "schema_as_is": "schema_prisma",
    "database_schema_as_is": "database_schema_markdown",
}

OVERLAY_FILENAME_BY_KIND = {
    "privacy_rules_as_is": "privacy_rules_as_is.json",
    "backend_workflows_as_is": "backend_workflows_as_is.json",
    "schema_as_is": "schema_as_is.prisma",
    "database_schema_as_is": "database_schema_as_is.md",
}

PLUGIN_SUPPLEMENT_AUGMENTATION_TARGETS = (
    "context_pack",
    "entities",
    "semantic_layer",
    "verification",
)

LOAD_TARGET_BY_ROLE = {
    EVIDENCE_ROLE_BUBBLE_EXPORT: "preserved_evidence_only",
    EVIDENCE_ROLE_CONTEXT_PACK: "preserved_evidence_only",
    EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST: "preserved_evidence_only",
    EVIDENCE_ROLE_VERIFICATION_REPORT: "preserved_evidence_only",
    EVIDENCE_ROLE_GAP_REPORT: "preserved_evidence_only",
    EVIDENCE_ROLE_OVERLAY_ARTIFACT: "preserved_evidence_only",
    EVIDENCE_ROLE_PLUGIN_SUPPLEMENT: "context_pack_augmentation",
    EVIDENCE_ROLE_SEMANTIC_INDEX: "preserved_evidence_only",
    EVIDENCE_ROLE_ENTITY_CATALOG: "entities",
    EVIDENCE_ROLE_EDGE_INDEX: "edges",
    EVIDENCE_ROLE_UNRESOLVED_EDGES: "edges",
}


@dataclass(frozen=True)
class ArtifactRecord:
    role: str
    local_path: str
    storage_bucket: str
    storage_object_path: str
    source_path: str
    content_hash: str
    metadata_json: dict[str, Any] = field(default_factory=dict)
    canonical: bool = False


@dataclass(frozen=True)
class SourceEvidencePlan:
    role: str
    local_path: str
    storage_bucket: str
    storage_object_path: str
    source_path: str
    content_hash: str
    canonical: bool
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionInventory:
    app_slug: str
    version_label: str
    export_path: str
    pack_dir: str
    canonical_evidence_roles: list[str]
    artifacts: list[ArtifactRecord]
    source_evidence_plan: list[SourceEvidencePlan]
    relational_load_plan: dict[str, Any]
    validation_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_slug": self.app_slug,
            "version_label": self.version_label,
            "export_path": self.export_path,
            "pack_dir": self.pack_dir,
            "canonical_evidence_roles": list(self.canonical_evidence_roles),
            "artifacts": [asdict(item) for item in self.artifacts],
            "source_evidence_plan": [asdict(item) for item in self.source_evidence_plan],
            "relational_load_plan": self.relational_load_plan,
            "validation_summary": self.validation_summary,
        }


def compute_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def hashed_artifact_filename(local_path: Path, content_hash: str) -> str:
    digest = content_hash.split(":", 1)[-1]
    short_hash = digest[:12]
    if local_path.suffix:
        return f"{local_path.stem}--{short_hash}{local_path.suffix}"
    return f"{local_path.name}--{short_hash}"


def maybe_relative_to(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def make_base_prefix(app_slug: str, version_label: str) -> str:
    return f"apps/{app_slug}/exports/{version_label}"


def overlay_artifact_path(app_slug: str, kind: str) -> Path:
    """Return the repo-relative overlay path for an app slug and overlay kind."""
    try:
        filename = OVERLAY_FILENAME_BY_KIND[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported overlay kind: {kind}") from exc
    return Path(app_slug) / filename


def storage_object_path_for_artifact(
    *,
    app_slug: str,
    version_label: str,
    role: str,
    local_path: Path,
    pack_dir: Path | None = None,
    overlay_type: str | None = None,
    index_name: str | None = None,
    path_hash: str | None = None,
) -> str:
    base_prefix = make_base_prefix(app_slug, version_label)
    content_hash = compute_content_hash(local_path)

    if role == EVIDENCE_ROLE_BUBBLE_EXPORT:
        return f"{base_prefix}/bubble_export/{hashed_artifact_filename(local_path, content_hash)}"

    if role == EVIDENCE_ROLE_SOURCE_BUNDLE_MANIFEST:
        return f"{base_prefix}/source_bundle/{local_path.name}"

    if role in {
        EVIDENCE_ROLE_CONTEXT_PACK,
        EVIDENCE_ROLE_ENTITY_CATALOG,
        EVIDENCE_ROLE_EDGE_INDEX,
        EVIDENCE_ROLE_UNRESOLVED_EDGES,
        EVIDENCE_ROLE_SEMANTIC_INDEX,
    }:
        if pack_dir is None:
            raise ValueError(f"pack_dir is required for role {role}")
        return f"{base_prefix}/context_pack/{local_path.relative_to(pack_dir).as_posix()}"

    if role in {EVIDENCE_ROLE_VERIFICATION_REPORT, EVIDENCE_ROLE_GAP_REPORT}:
        return f"{base_prefix}/verification/{local_path.name}"

    if role == EVIDENCE_ROLE_OVERLAY_ARTIFACT:
        if not overlay_type:
            raise ValueError("overlay_type is required for overlay_artifact")
        return f"{base_prefix}/overlays/{overlay_type}/{hashed_artifact_filename(local_path, content_hash)}"

    if role == EVIDENCE_ROLE_PLUGIN_SUPPLEMENT:
        if path_hash:
            digest = path_hash.split(":", 1)[-1]
            short_hash = digest[:12]
            if local_path.suffix:
                filename = f"{local_path.stem}--{short_hash}{local_path.suffix}"
            else:
                filename = f"{local_path.name}--{short_hash}"
        else:
            filename = local_path.name
        return f"{base_prefix}/plugin_supplements/{filename}"

    raise ValueError(f"Unsupported artifact role: {role} (index_name={index_name!r})")


def artifact_record(
    *,
    role: str,
    path: Path,
    app_slug: str,
    version_label: str,
    repo_root: Path | None = None,
    pack_dir: Path | None = None,
    source_path: str | None = None,
    storage_bucket: str | None = None,
    storage_object_path: str | None = None,
    content_hash: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    canonical: bool = False,
) -> ArtifactRecord:
    metadata = dict(metadata_json or {})
    overlay_type = metadata.get("overlay_type")
    index_name = metadata.get("index_name")
    resolved_content_hash = content_hash or compute_content_hash(path)
    if source_path is None:
        if pack_dir is not None:
            source_path = maybe_relative_to(path, pack_dir)
        elif repo_root is not None:
            source_path = maybe_relative_to(path, repo_root)
        else:
            raise ValueError("artifact_record requires source_path or a base path")
    path_hash = hashlib.sha256(source_path.encode()).hexdigest()
    return ArtifactRecord(
        role=role,
        local_path=path.resolve().as_posix(),
        storage_bucket=storage_bucket or BUBBLE_SOURCE_ARTIFACTS_BUCKET,
        storage_object_path=storage_object_path
        or storage_object_path_for_artifact(
            app_slug=app_slug,
            version_label=version_label,
            role=role,
            local_path=path,
            pack_dir=pack_dir,
            overlay_type=overlay_type,
            index_name=index_name,
            path_hash=path_hash,
        ),
        source_path=source_path,
        content_hash=resolved_content_hash,
        metadata_json=metadata,
        canonical=canonical,
    )


def source_evidence_plan_from_artifact(artifact: ArtifactRecord) -> SourceEvidencePlan:
    return SourceEvidencePlan(
        role=artifact.role,
        local_path=artifact.local_path,
        storage_bucket=artifact.storage_bucket,
        storage_object_path=artifact.storage_object_path,
        source_path=artifact.source_path,
        content_hash=artifact.content_hash,
        canonical=artifact.canonical,
        metadata_json=dict(artifact.metadata_json),
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sort_artifacts(artifacts: list[ArtifactRecord]) -> list[ArtifactRecord]:
    return sorted(
        artifacts,
        key=lambda item: (
            item.role,
            item.storage_object_path,
            item.local_path,
        ),
    )
