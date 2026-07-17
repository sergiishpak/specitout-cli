from __future__ import annotations


SELECTED_BACKEND = "postgres"
SQLITE_FALLBACK_STATE = "not-active"


def build_backend_gate_status() -> dict[str, str]:
    return {
        "backend": SELECTED_BACKEND,
        "sqlite_fallback": SQLITE_FALLBACK_STATE,
    }
