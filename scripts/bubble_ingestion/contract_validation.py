from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from bubble_ingestion_contract import (
    REQUIRED_PACK_RELATIVE_PATHS,
    compute_content_hash,
    load_json,
    load_jsonl,
)


class ValidationError(RuntimeError):
    """Raised when ingestion inputs do not satisfy the contract."""


REQUIRED_VERIFICATION_CHECKS = frozenset(
    {
        "structural_completeness",
        "semantic_completeness",
        "evidence_linkage",
        "augmentation_coverage",
    }
)


def resolve_contract_path(base_dir: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def require_file(path: Path, label: str) -> Path:
    if not path.exists():
        raise ValidationError(f"Missing {label}: {path}")
    if not path.is_file():
        raise ValidationError(f"Expected {label} to be a file: {path}")
    return path


def ensure_required_pack_files(pack_dir: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for relative_path in REQUIRED_PACK_RELATIVE_PATHS:
        resolved[relative_path] = require_file(pack_dir / relative_path, relative_path)
    return resolved


def ensure_preserved_optional_files(
    pack_dir: Path,
    *,
    optional_paths: tuple[str, ...],
) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for relative_path in optional_paths:
        candidate = pack_dir / relative_path
        if candidate.exists():
            require_file(candidate, relative_path)
            resolved[relative_path] = candidate
    return resolved


def load_and_validate_entity_catalog(pack_dir: Path) -> tuple[list[dict[str, Any]], Counter[str]]:
    catalog_path = pack_dir / "structural/indexes/entity_catalog.jsonl"
    rows = load_jsonl(catalog_path)
    if not rows:
        raise ValidationError("entity_catalog.jsonl is empty")

    type_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        for key in ("entity_key", "entity_type", "artifact_path", "semantic_artifact_path", "source_path"):
            if key not in row or not row[key]:
                raise ValidationError(f"entity_catalog row {index} is missing {key}")

        structural_path = pack_dir / row["artifact_path"]
        semantic_path = pack_dir / row["semantic_artifact_path"]
        require_file(structural_path, f"entity_catalog structural artifact for {row['entity_key']}")
        require_file(semantic_path, f"entity_catalog semantic artifact for {row['entity_key']}")

        structural = load_json(structural_path)
        semantic = load_json(semantic_path)
        if structural.get("entity_key") != row["entity_key"]:
            raise ValidationError(
                f"structural artifact mismatch for {row['entity_key']}: "
                f"found {structural.get('entity_key')!r}"
            )
        if semantic.get("entity_key") != row["entity_key"]:
            raise ValidationError(
                f"semantic artifact mismatch for {row['entity_key']}: "
                f"found {semantic.get('entity_key')!r}"
            )

        semantic_links = semantic.get("evidence_links")
        if not isinstance(semantic_links, list) or not semantic_links:
            raise ValidationError(
                f"semantic artifact for {row['entity_key']} is missing non-empty evidence_links"
            )

        structural_evidence = structural.get("evidence") or {}
        valid_structural_links = {("source", structural_evidence.get("source_path"))}
        for link in structural_evidence.get("overlay_links") or []:
            kind = link.get("kind")
            path = link.get("path")
            if kind and path:
                valid_structural_links.add((kind, path))

        normalized_semantic_links = set()
        for link in semantic_links:
            if not isinstance(link, dict) or not link.get("kind") or not link.get("path"):
                raise ValidationError(
                    f"semantic artifact for {row['entity_key']} contains malformed evidence_links"
                )
            normalized_semantic_links.add((link["kind"], link["path"]))

        invalid_semantic_links = normalized_semantic_links - valid_structural_links
        if invalid_semantic_links:
            raise ValidationError(
                f"semantic artifact for {row['entity_key']} contains evidence_links that do not map back to structural evidence: "
                f"{sorted(invalid_semantic_links)!r}"
            )
        if not normalized_semantic_links:
            raise ValidationError(
                f"semantic artifact for {row['entity_key']} has no evidence_links that map back to structural evidence"
            )
        type_counts[row["entity_type"]] += 1
    return rows, type_counts


def validate_manifest_counts(
    *,
    manifest: dict[str, Any],
    entity_catalog_rows: list[dict[str, Any]],
    entity_type_counts: Counter[str],
    edge_rows: list[dict[str, Any]],
    unresolved_edges: list[dict[str, Any]],
    public_api_workflows: dict[str, Any],
    permission_surface_index: dict[str, Any],
    expected_source_export: str,
    expected_source_bundle_manifest: str | None = None,
) -> None:
    if manifest.get("entity_catalog_count") != len(entity_catalog_rows):
        raise ValidationError("manifest entity_catalog_count does not match entity_catalog.jsonl line count")

    manifest_counts = manifest.get("entity_counts") or {}
    if dict(sorted(manifest_counts.items())) != dict(sorted(entity_type_counts.items())):
        raise ValidationError("manifest entity_counts do not match entity_catalog.jsonl entity_type totals")

    if manifest.get("edge_count") != len(edge_rows):
        raise ValidationError("manifest edge_count does not match edge_index.jsonl row count")
    if manifest.get("unresolved_edge_count") != len(unresolved_edges):
        raise ValidationError("manifest unresolved_edge_count does not match unresolved_edges.json length")

    public_count = public_api_workflows.get("count")
    workflow_rows = public_api_workflows.get("workflows") or []
    if public_count != len(workflow_rows):
        raise ValidationError("public_api_workflows.json count does not match workflow row count")
    if manifest.get("public_api_workflow_count") != public_count:
        raise ValidationError("manifest public_api_workflow_count does not match public_api_workflows.json")

    permission_surface_count = permission_surface_index.get("count")
    permission_surface_rows = permission_surface_index.get("user_types") or []
    if permission_surface_count != len(permission_surface_rows):
        raise ValidationError("permission_surface_index.json count does not match user_types row count")
    manifest_permission_surface_count = manifest.get("permission_surface_index_count")
    if (
        manifest_permission_surface_count is not None
        and manifest_permission_surface_count != permission_surface_count
    ):
        raise ValidationError(
            "manifest permission_surface_index_count does not match permission_surface_index.json"
        )

    source_export = manifest.get("source_export")
    if not source_export:
        raise ValidationError("manifest is missing source_export")
    if source_export != expected_source_export:
        raise ValidationError(
            "manifest source_export does not match staged export ref: "
            f"{source_export!r} != {expected_source_export!r}"
        )
    if expected_source_bundle_manifest is not None:
        if manifest.get("source_bundle_manifest") != expected_source_bundle_manifest:
            raise ValidationError(
                "manifest source_bundle_manifest does not match staged manifest ref: "
                f"{manifest.get('source_bundle_manifest')!r} != {expected_source_bundle_manifest!r}"
            )


def validate_verification_report(path: Path) -> dict[str, Any]:
    report = load_json(path)
    if not isinstance(report, dict):
        raise ValidationError("verification_report.json must contain an object")
    if "generated_at" not in report:
        raise ValidationError("verification_report.json is missing generated_at")
    if "checks" not in report or not isinstance(report["checks"], dict):
        raise ValidationError("verification_report.json is missing checks")
    if "counts" not in report or not isinstance(report["counts"], dict):
        raise ValidationError("verification_report.json is missing counts")

    checks = report["checks"]
    if not checks:
        raise ValidationError("verification_report.json has no populated checks")

    missing_checks = sorted(
        check_name
        for check_name in REQUIRED_VERIFICATION_CHECKS
        if check_name not in checks
    )
    if missing_checks:
        raise ValidationError(
            f"verification_report.json is missing required checks: {', '.join(missing_checks)}"
        )
    return report
