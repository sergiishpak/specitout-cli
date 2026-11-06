from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArgumentSpec:
    flags: tuple[str, ...]
    kwargs: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help: str
    description: str
    handler_key: str
    arguments: tuple[ArgumentSpec, ...] = ()


@dataclass(frozen=True)
class GroupSpec:
    name: str
    help: str
    description: str
    commands: tuple[CommandSpec, ...] = ()
    epilog: str | None = None


OUTPUT_FORMAT_ARGUMENT = ArgumentSpec(
    flags=("--format",),
    kwargs={"dest": "output_format", "choices": ("text", "json"), "default": "text"},
)


COMMAND_GROUPS: tuple[GroupSpec, ...] = (
    GroupSpec(
        name="app",
        help="Manage Bubble application scopes",
        description="Manage Bubble application scopes.",
        commands=(
            CommandSpec(
                name="list",
                help="List known Bubble application scopes.",
                description="List known Bubble application scopes.",
                handler_key="placeholder",
            ),
            CommandSpec(
                name="show",
                help="Show one Bubble application scope.",
                description="Show one Bubble application scope.",
                handler_key="app_show",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                ),
            ),
        ),
    ),
    GroupSpec(
        name="import",
        help="Register and process Bubble export files",
        description="Register and process Bubble export files.",
        epilog=(
            "Scope notes:\n"
            "  - Use --app to target one Bubble application scope.\n"
            "  - Add --version to inspect one non-active export version explicitly.\n"
            "\n"
            "Status usage:\n"
            "  specitout import status --app APP_SLUG [--version VERSION_LABEL]\n"
            "\n"
            "Next steps:\n"
            "  - Check readiness with specitout import status --app <app-slug>\n"
            "  - Inspect runtime bootstrap with specitout index status --app <app-slug>"
        ),
        commands=(
            CommandSpec(
                name="add",
                help="Register one Bubble export file for processing.",
                description="Register one Bubble export file for processing.",
                handler_key="import_add",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label", "required": True}),
                    ArgumentSpec(flags=("--export",), kwargs={"dest": "export_path", "required": True}),
                    ArgumentSpec(flags=("--display-name",), kwargs={"dest": "display_name"}),
                    ArgumentSpec(flags=("--source-system",), kwargs={"dest": "source_system", "default": "bubble"}),
                    ArgumentSpec(flags=("--external-app-id",), kwargs={"dest": "external_app_id"}),
                ),
            ),
            CommandSpec(
                name="list",
                help="List known Bubble export registrations.",
                description="List known Bubble export registrations.",
                handler_key="import_list",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug"}),
                ),
            ),
            CommandSpec(
                name="status",
                help="Show processing status for one Bubble export.",
                description="Show processing status for one Bubble export.",
                handler_key="import_status",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                ),
            ),
            CommandSpec(
                name="retry",
                help="Retry a failed or incomplete Bubble export import.",
                description="Retry a failed or incomplete Bubble export import.",
                handler_key="import_retry",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label", "required": True}),
                    ArgumentSpec(flags=("--export",), kwargs={"dest": "export_path"}),
                ),
            ),
            CommandSpec(
                name="activate",
                help="Cut over an application scope to one processed export.",
                description="Cut over an application scope to one processed export.",
                handler_key="import_activate",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label", "required": True}),
                ),
            ),
        ),
    ),
    GroupSpec(
        name="index",
        help="Monitor or rebuild local indexing work",
        description="Monitor or rebuild local indexing work.",
        epilog=(
            "Scope notes:\n"
            "  - Use --app to target one Bubble application scope.\n"
            "  - Add --version only together with --app when you need one explicit export version.\n"
            "\n"
            "Status usage:\n"
            "  specitout index status --app APP_SLUG [--version VERSION_LABEL]\n"
            "\n"
            "Next steps:\n"
            "  - Check runtime bootstrap with specitout index status --app <app-slug>\n"
            "  - Check import readiness with specitout import status --app <app-slug>"
        ),
        commands=(
            CommandSpec(
                name="status",
                help="Show the current local indexing status for a scope.",
                description="Show the current local indexing status for a scope.",
                handler_key="index_status",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug"}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                ),
            ),
            CommandSpec(
                name="rebuild",
                help="Rebuild local indexes for a scope.",
                description="Rebuild local indexes for a scope.",
                handler_key="index_rebuild",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label", "required": True}),
                    ArgumentSpec(flags=("--limit",), kwargs={"dest": "limit", "type": int}),
                ),
            ),
            CommandSpec(
                name="resume",
                help="Resume bounded embedding work until an export is ready.",
                description="Resume bounded embedding work until an export is ready.",
                handler_key="index_resume",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label", "required": True}),
                    ArgumentSpec(flags=("--initial-limit",), kwargs={"dest": "initial_limit", "type": int, "default": 256}),
                    ArgumentSpec(flags=("--min-limit",), kwargs={"dest": "min_limit", "type": int, "default": 16}),
                    ArgumentSpec(flags=("--max-passes",), kwargs={"dest": "max_passes", "type": int, "default": 500}),
                    ArgumentSpec(flags=("--stuck-pass-threshold",), kwargs={"dest": "stuck_pass_threshold", "type": int, "default": 5}),
                    ArgumentSpec(flags=("--sleep-seconds",), kwargs={"dest": "sleep_seconds", "type": float, "default": 2.0}),
                ),
            ),
        ),
    ),
    GroupSpec(
        name="query",
        help="Search and inspect local project knowledge",
        description="Search and inspect the active Bubble export for one application scope.",
        commands=(
            CommandSpec(
                name="search",
                help="Find likely matches for a question, identifier, or keyword.",
                description="Find likely matches for a question, identifier, or keyword.",
                handler_key="query_search",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--query",), kwargs={"dest": "query_text", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                    ArgumentSpec(
                        flags=("--mode",),
                        kwargs={"dest": "mode", "choices": ("root", "deep"), "default": "root"},
                    ),
                    ArgumentSpec(flags=("--limit",), kwargs={"dest": "limit", "type": int, "default": 10}),
                    OUTPUT_FORMAT_ARGUMENT,
                ),
            ),
            CommandSpec(
                name="entity",
                help="Fetch one canonical entity by key or unambiguous identifier.",
                description="Fetch one canonical entity by key or unambiguous identifier.",
                handler_key="query_entity",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--entity",), kwargs={"dest": "entity_lookup", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                    OUTPUT_FORMAT_ARGUMENT,
                ),
            ),
            CommandSpec(
                name="usage",
                help="Show where an entity is used and what it depends on.",
                description="Show where an entity is used and what it depends on.",
                handler_key="query_usage",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--entity",), kwargs={"dest": "entity_lookup", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                    ArgumentSpec(
                        flags=("--direction",),
                        kwargs={
                            "dest": "direction",
                            "choices": ("inbound", "outbound", "bidirectional"),
                            "default": "bidirectional",
                        },
                    ),
                    ArgumentSpec(flags=("--relation",), kwargs={"dest": "relation"}),
                    ArgumentSpec(flags=("--limit",), kwargs={"dest": "limit", "type": int, "default": 10}),
                    OUTPUT_FORMAT_ARGUMENT,
                ),
            ),
            CommandSpec(
                name="paths",
                help="Show a bounded connection path between two anchors.",
                description="Show a bounded connection path between two anchors.",
                handler_key="query_paths",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--from",), kwargs={"dest": "from_lookup", "required": True}),
                    ArgumentSpec(flags=("--to",), kwargs={"dest": "to_lookup", "required": True}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                    ArgumentSpec(
                        flags=("--direction",),
                        kwargs={
                            "dest": "direction",
                            "choices": ("inbound", "outbound", "bidirectional"),
                            "default": "bidirectional",
                        },
                    ),
                    ArgumentSpec(flags=("--relation",), kwargs={"dest": "relation"}),
                    ArgumentSpec(flags=("--max-hops",), kwargs={"dest": "max_hops", "type": int, "default": 3}),
                    ArgumentSpec(flags=("--max-paths",), kwargs={"dest": "max_paths", "type": int, "default": 3}),
                    OUTPUT_FORMAT_ARGUMENT,
                ),
            ),
        ),
        epilog=(
            "Behavior notes:\n"
            "  - Results stay inside one application and one active export version.\n"
            "  - Exact identifiers should outrank weaker semantic matches.\n"
            "  - Degraded mode is reported when semantic retrieval is unavailable."
        ),
    ),
    GroupSpec(
        name="bundle",
        help="Build bounded context bundles for downstream reasoning",
        description="Build bounded context bundles for downstream reasoning.",
        commands=(
            CommandSpec(
                name="build",
                help="Build one bounded context bundle for downstream reasoning.",
                description="Build one bounded context bundle for downstream reasoning.",
                handler_key="bundle_build",
                arguments=(
                    ArgumentSpec(flags=("--app",), kwargs={"dest": "app_slug", "required": True}),
                    ArgumentSpec(flags=("--query",), kwargs={"dest": "query_text"}),
                    ArgumentSpec(flags=("--entity",), kwargs={"dest": "entity_key"}),
                    ArgumentSpec(flags=("--version",), kwargs={"dest": "version_label"}),
                    ArgumentSpec(
                        flags=("--mode",),
                        kwargs={"dest": "mode", "choices": ("root", "deep"), "default": "root"},
                    ),
                    ArgumentSpec(flags=("--anchor-limit",), kwargs={"dest": "anchor_limit", "type": int, "default": 3}),
                    ArgumentSpec(flags=("--max-hops",), kwargs={"dest": "max_hops", "type": int, "default": 1}),
                    ArgumentSpec(flags=("--entity-limit",), kwargs={"dest": "entity_limit", "type": int, "default": 20}),
                    ArgumentSpec(flags=("--edge-limit",), kwargs={"dest": "edge_limit", "type": int, "default": 30}),
                    OUTPUT_FORMAT_ARGUMENT,
                ),
            ),
        ),
    ),
    GroupSpec(
        name="task",
        help="Start and finish user-visible trial tasks",
        description="Start and finish user-visible trial tasks.",
        commands=(
            CommandSpec(
                name="start",
                help="Start one user-visible task run.",
                description="Start one user-visible task run.",
                handler_key="placeholder",
            ),
            CommandSpec(
                name="finish",
                help="Finish one user-visible task run.",
                description="Finish one user-visible task run.",
                handler_key="placeholder",
            ),
        ),
    ),
    GroupSpec(
        name="license",
        help="Activate, deactivate, and inspect paid access",
        description="Activate, deactivate, and inspect paid access.",
        commands=(
            CommandSpec(
                name="activate",
                help="Activate paid access on this machine.",
                description="Activate paid access on this machine.",
                handler_key="placeholder",
            ),
            CommandSpec(
                name="deactivate",
                help="Deactivate paid access on this machine.",
                description="Deactivate paid access on this machine.",
                handler_key="placeholder",
            ),
            CommandSpec(
                name="status",
                help="Inspect the current paid-access state.",
                description="Inspect the current paid-access state.",
                handler_key="placeholder",
            ),
        ),
    ),
    GroupSpec(
        name="trial",
        help="Inspect trial status and remaining tasks",
        description="Inspect trial status and remaining tasks.",
        commands=(
            CommandSpec(
                name="status",
                help="Inspect trial status and remaining tasks.",
                description="Inspect trial status and remaining tasks.",
                handler_key="placeholder",
            ),
        ),
    ),
)


# Public runtime surface: unfinished commercial command families are not prerequisites.
COMMAND_GROUPS = tuple(group for group in COMMAND_GROUPS if group.name not in {"task", "license", "trial"}) + (
    GroupSpec(name="project", help="Create a private application workspace", description="Create a private application workspace.", commands=(
        CommandSpec(name="init", help="Initialize a private folder without starting Postgres.", description="Initialize a private folder without starting Postgres.", handler_key="project_init", arguments=(
            ArgumentSpec(flags=("path",)),
            ArgumentSpec(flags=("--app",), kwargs={"dest":"app_slug", "required": True}),
        )),
    )),
    GroupSpec(name="runtime", help="Manage the selected local Postgres runtime", description="Manage the selected local Postgres runtime.", commands=(
        CommandSpec(name="stop", help="Stop only the selected runtime; preserve data.", description="Stop only the selected runtime; preserve data.", handler_key="runtime_stop"),
    )),
)


HELP_GROUP = GroupSpec(
    name="help",
    help="Show help for a command or subcommand",
    description="Show help for a command or subcommand.",
)


def iter_root_groups() -> tuple[GroupSpec, ...]:
    return (*COMMAND_GROUPS, HELP_GROUP)


def get_group(name: str) -> GroupSpec:
    for group in COMMAND_GROUPS:
        if group.name == name:
            return group
    if name == HELP_GROUP.name:
        return HELP_GROUP
    raise KeyError(name)
