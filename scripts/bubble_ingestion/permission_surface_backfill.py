from __future__ import annotations

import argparse
from typing import Any

from bubble_ingestion.backend_protocol import BackendProtocol
from bubble_ingestion.errors import IngestionError
from bubble_ingestion.transforms import build_permission_surface_index


def backfill_permission_surface_index_with_backend(
    args: argparse.Namespace,
    backend: BackendProtocol,
) -> dict[str, Any]:
    app = backend.get_app(app_slug=args.app_slug)
    if app is None:
        raise IngestionError(f"Unknown app_slug {args.app_slug}")

    export = backend.get_export(app_id=str(app["id"]), version_label=args.version_label)
    if export is None:
        raise IngestionError(
            f"Unknown export version_label {args.version_label} for app_slug {args.app_slug}"
        )
    pack_dir = getattr(args, "pack_dir", None)
    if pack_dir is None:
        raise IngestionError("backfill-permission-surface-index now requires --pack-dir")

    rows = build_permission_surface_index(str(export["id"]), pack_dir)
    backend.upsert_rows("permission_surface_index", rows)

    return {
        "action": "backfill-permission-surface-index",
        "app_slug": app["slug"],
        "version_label": export["version_label"],
        "status": "succeeded",
        "rows_loaded": len(rows),
    }
