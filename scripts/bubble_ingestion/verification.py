from __future__ import annotations

from typing import Any

from bubble_ingestion.constants import (
    CUTOVER_SAFE_READINESS,
    DEGRADABLE_READINESS,
    QUERY_ELIGIBLE_READINESS,
    RETRYABLE_READINESS,
)
from bubble_ingestion.contract_validation import REQUIRED_VERIFICATION_CHECKS
from bubble_ingestion.errors import IngestionError


def has_passed_verification(export: dict[str, Any]) -> bool:
    return ((export.get("metadata_json") or {}).get("verification") or {}).get("status") == "passed"


def has_pending_replacement(export: dict[str, Any]) -> bool:
    metadata_json = export.get("metadata_json") or {}
    return bool(metadata_json.get("pending_replacement_of_export_id") or export.get("supersedes_export_id"))


def replacement_target_export_id(export: dict[str, Any]) -> str | None:
    metadata_json = export.get("metadata_json") or {}
    return export.get("supersedes_export_id") or metadata_json.get("pending_replacement_of_export_id")


def is_query_eligible_readiness(readiness_status: str | None) -> bool:
    return readiness_status in QUERY_ELIGIBLE_READINESS


def build_verification_result(
    *,
    verification_report: dict[str, Any],
    plugin_supplement_summary: dict[str, Any] | None = None,
    required_verification_checks: frozenset[str] = REQUIRED_VERIFICATION_CHECKS,
) -> dict[str, Any]:
    _ = plugin_supplement_summary
    checks = verification_report.get("checks") or {}
    if not isinstance(checks, dict) or not checks:
        raise IngestionError("verification_report.json must contain non-empty checks")

    missing_required_checks = sorted(
        check_name for check_name in required_verification_checks if check_name not in checks
    )
    if missing_required_checks:
        raise IngestionError(
            "verification_report.json must include checks for: " + ", ".join(missing_required_checks)
        )

    required_check_statuses = {
        "structural_completeness": bool(checks.get("structural_completeness")),
        "semantic_completeness": bool(checks.get("semantic_completeness")),
        "evidence_linkage": bool(checks.get("evidence_linkage")),
        "augmentation_coverage": bool(checks.get("augmentation_coverage")),
    }
    required_check_statuses["structural_completeness"] = required_check_statuses["structural_completeness"] and all(
        bool(checks.get(check_name, True))
        for check_name in (
            "entity_registry_complete",
            "entity_catalog_complete",
            "path_registry_complete",
            "edge_targets_resolve_or_are_flagged",
            "synthetic_entities_have_parents",
            "synthetic_ids_are_repeatable",
            "synthetic_counts_are_repeatable",
        )
    )
    required_check_statuses["semantic_completeness"] = required_check_statuses["semantic_completeness"] and all(
        bool(checks.get(check_name, True))
        for check_name in (
            "semantic_record_count_matches_entities",
            "condition_expression_data_source_chain_present",
            "permission_surface_index_reconciles",
            "app_settings_summary_reconciles",
        )
    )
    required_check_statuses["evidence_linkage"] = required_check_statuses["evidence_linkage"] and bool(
        checks.get("semantic_evidence_links_map_to_structural_evidence", True)
    )
    required_check_statuses["augmentation_coverage"] = required_check_statuses["augmentation_coverage"] and all(
        bool(checks.get(check_name, True))
        for check_name in ("overlay_link_validation_complete", "synthetic_entities_have_evidence")
    )

    failed_checks = sorted(check_name for check_name, passed in required_check_statuses.items() if not passed)
    if failed_checks:
        return {
            "status": "failed",
            "failed_checks": failed_checks,
            "failure_reason": f"verification failed: {', '.join(failed_checks)}",
        }
    return {"status": "passed", "failed_checks": [], "failure_reason": None}


def should_cutover_replacement_export(
    *,
    export: dict[str, Any],
    import_mode: str,
    verification_status: str,
) -> bool:
    return (
        import_mode == "replace_active_version"
        and verification_status == "passed"
        and has_pending_replacement(export)
        and export.get("readiness_status") in CUTOVER_SAFE_READINESS
    )


def validate_or_backfill_plugin_supplement_hashes(
    *,
    backend: Any,
    export: dict[str, Any],
    plugin_supplement_hashes: list[str],
    mismatch_message: str,
    allow_backfill: bool = True,
) -> dict[str, Any]:
    metadata_json = dict(export.get("metadata_json") or {})
    existing_plugin_hashes = metadata_json.get("plugin_supplement_hashes")
    if existing_plugin_hashes is not None:
        if sorted(existing_plugin_hashes) != plugin_supplement_hashes:
            raise IngestionError(mismatch_message)
        return export

    if not allow_backfill:
        existing_plugin_hashes = sorted(
            backend.list_source_evidence_hashes(
                export_id=export["id"],
                evidence_role="plugin_supplement",
            )
        )
        if existing_plugin_hashes != plugin_supplement_hashes:
            raise IngestionError(mismatch_message)
        return export

    existing_plugin_hashes = sorted(
        backend.list_source_evidence_hashes(export_id=export["id"], evidence_role="plugin_supplement")
    )
    if existing_plugin_hashes:
        if existing_plugin_hashes != plugin_supplement_hashes:
            raise IngestionError(mismatch_message)
        metadata_json["plugin_supplement_hashes"] = existing_plugin_hashes
        return backend.update_export(export["id"], metadata_json=metadata_json)

    metadata_json["plugin_supplement_hashes"] = plugin_supplement_hashes
    return backend.update_export(export["id"], metadata_json=metadata_json)


def failure_readiness_status(current_readiness_status: str | None) -> str:
    if current_readiness_status in DEGRADABLE_READINESS:
        return "degraded"
    return "failed"


def should_fast_path_existing_replacement(
    *,
    export: dict[str, Any],
    active_export: dict[str, Any] | None,
    import_mode: str,
) -> bool:
    if import_mode != "replace_active_version":
        return False
    if export.get("lifecycle_status") != "candidate":
        return False
    if not has_passed_verification(export) or not has_pending_replacement(export):
        return False
    if active_export is None:
        return False
    return replacement_target_export_id(export) == active_export.get("id")


def backfill_pending_replacement_metadata(*, backend: Any, export: dict[str, Any]) -> dict[str, Any]:
    metadata_json = dict(export.get("metadata_json") or {})
    if metadata_json.get("pending_replacement_of_export_id"):
        return export
    supersedes_export_id = export.get("supersedes_export_id")
    if not supersedes_export_id:
        return export
    metadata_json["pending_replacement_of_export_id"] = supersedes_export_id
    return backend.update_export(export["id"], metadata_json=metadata_json)


def retryable_readiness() -> frozenset[str]:
    return RETRYABLE_READINESS
