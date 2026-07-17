from __future__ import annotations


def status_next_actions(*, readiness_state: str, is_active: bool, degraded: bool) -> list[str]:
    if readiness_state in {"registered", "ingesting"}:
        return ["index status --app <app-slug>", "import list --app <app-slug>"]
    if readiness_state == "embedding_pending":
        return ["index rebuild --app <app-slug> --version <version>", "index status --app <app-slug>"]
    if readiness_state == "searchable":
        actions = ["query search --app <app-slug>"]
        if not is_active:
            actions.append("import activate --app <app-slug> --version <version>")
        return actions
    if readiness_state == "ready":
        actions = ["query search --app <app-slug>", "query entity --app <app-slug> --key <entity-key>"]
        if not is_active:
            actions.append("import activate --app <app-slug> --version <version>")
        return actions
    if readiness_state == "degraded":
        actions = ["query search --app <app-slug>", "index status --app <app-slug>"]
        if not is_active:
            actions.append("import activate --app <app-slug> --version <version>")
        return actions
    if degraded or readiness_state == "failed":
        return ["import retry --app <app-slug> --version <version>", "index status --app <app-slug>"]
    return ["import list --app <app-slug>"]
