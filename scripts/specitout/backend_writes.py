from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from specitout.runtime import SpecItOutRuntimeError
from specitout.progress import report_active

_CONFLICT_TARGETS = {
    "pipeline_runs": ("id",),
    "ingestion_runs": ("export_id", "phase"),
    "source_evidence": ("export_id", "evidence_role", "storage_bucket", "storage_object_path"),
    "entities": ("export_id", "entity_key"),
    "edges": ("id",),
    "entity_facets": ("export_id", "entity_key", "facet_type", "facet_value"),
    "overlay_links": ("export_id", "entity_key", "overlay_type", "source_path"),
    "public_api_workflow_index": ("export_id", "entity_key", "workflow_name"),
    "permission_surface_index": ("export_id", "entity_key"),
}
_MAX_QUERY_PARAMETERS = 65535


def prepare_rows_for_upsert(table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    try:
        conflict_columns = _CONFLICT_TARGETS[table]
    except KeyError as exc:
        raise ValueError(f"Unsupported upsert target: {table}") from exc
    return _dedupe_rows(rows, conflict_columns)


def delete_export_scoped_rows(*, connect: Any, table: str, export_id: str) -> None:
    deleted_total = 0
    with connect() as conn, conn.cursor() as cur:
        while True:
            cur.execute(
                "select specitout.delete_export_scoped_rows(%s, %s, %s)",
                (table, export_id, 1000),
            )
            deleted = int(_extract_scalar(cur.fetchone()))
            if deleted <= 0:
                break
            deleted_total += deleted
            report_active(f"graph_clear.{table}", deleted_total, 0, f"deleted {deleted_total} {table} rows; unit=rows total=unknown; transaction uncommitted")
        report_active(f"graph_clear.{table}", 0, 0, f"waiting for {table} deletion transaction validation and commit; rows={deleted_total}")
    report_active(f"graph_clear.{table}", deleted_total, 0, f"committed deletion of {deleted_total} {table} rows; unit=rows total=unknown")


def upsert_rows(*, connect: Any, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    rows = prepare_rows_for_upsert(table, rows)
    conflict_columns = _CONFLICT_TARGETS[table]
    columns = list(rows[0].keys())
    update_columns = [column for column in columns if column not in conflict_columns]
    if update_columns:
        conflict_action = (
            "do update\n"
            "set " + ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        )
    else:
        conflict_action = "do nothing"
    max_batch_size = max(1, _MAX_QUERY_PARAMETERS // max(1, len(columns)))
    written = 0
    for batch in _batched(rows, max_batch_size):
        placeholders: list[str] = []
        params: dict[str, Any] = {}
        for row_index, row in enumerate(batch):
            row_placeholders: list[str] = []
            for column in columns:
                param_name = f"{column}_{row_index}"
                row_placeholders.append(f"%({param_name})s")
                params[param_name] = coerce_db_value(row[column])
            placeholders.append("(" + ", ".join(row_placeholders) + ")")

        query = f"""
insert into specitout.{table} ({", ".join(columns)})
values {", ".join(placeholders)}
on conflict ({", ".join(conflict_columns)}) {conflict_action}
"""
        report_active(f"graph_write.{table}", written, len(rows), f"processing {table} batch of {len(batch)} rows; unit=rows; committed={written}")
        with connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            report_active(f"graph_commit.{table}", written, len(rows), f"waiting for {table} batch transaction validation and commit; unit=rows; committed={written}")
        written += len(batch)
        report_active(f"graph_write.{table}", written, len(rows), f"committed {written}/{len(rows)} {table} rows; unit=rows")


def coerce_db_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _build_jsonb(dict(value))
    if isinstance(value, (list, tuple)):
        return _build_jsonb(list(value))
    return value


def _build_jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError as exc:
        raise SpecItOutRuntimeError(
            "psycopg is required for runtime-backed SpecItOut catalog commands. "
            "Install project dependencies before running app or import commands."
        ) from exc
    return Jsonb(value)


def _extract_scalar(row: object) -> object:
    if isinstance(row, Mapping):
        if not row:
            raise ValueError("expected one scalar row value, received empty mapping")
        return next(iter(row.values()))
    if isinstance(row, tuple):
        if not row:
            raise ValueError("expected one scalar row value, received empty tuple")
        return row[0]
    raise TypeError(f"unsupported scalar row type: {type(row)!r}")


def _batched(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def _dedupe_rows(rows: list[dict[str, Any]], conflict_columns: tuple[str, ...]) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row[column] for column in conflict_columns)
        if key in deduped:
            del deduped[key]
        deduped[key] = row
    return list(deduped.values())
