from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from specitout.backend import build_local_backend
from specitout.backend_protocol import LocalBackendProtocol
from specitout.command_registry import COMMAND_GROUPS, HELP_GROUP, CommandSpec, GroupSpec, iter_root_groups
from specitout.contracts import CommandEnvelope
from specitout.json_rendering import render_json_envelope
from specitout.rendering import coerce_exit_code, render_envelope
from specitout.runtime import SpecItOutRuntimeError
from specitout.services import CliServices, build_cli_services

BackendFactory = Callable[[], LocalBackendProtocol]
ServicesFactory = Callable[[], CliServices]


class RootParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        if self.prog != "specitout":
            return super().format_help()
        lines = [
            "SpecItOut helps an AI agent search and inspect Bubble application knowledge locally.",
            "",
            "Usage:",
            "  specitout <command> <subcommand> [arguments] [flags]",
            "",
            "Command groups:",
        ]
        for group in iter_root_groups():
            lines.append(f"  {group.name:<11}{group.help}")
        lines.extend(
            [
                "",
                "Use:",
                "  specitout help <command>",
                "  specitout <command> --help",
                "",
            ]
        )
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = RootParser(prog="specitout")
    subparsers = parser.add_subparsers(dest="command")

    for group in COMMAND_GROUPS:
        _add_group_parser(subparsers, group)

    help_parser = subparsers.add_parser("help", help=HELP_GROUP.help, description=HELP_GROUP.description)
    help_parser.add_argument("topic", nargs="*")
    help_parser.set_defaults(handler=_handle_help_command)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: BackendFactory = build_local_backend,
    services_factory: ServicesFactory | None = None,
) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    resolved_services_factory = services_factory or _make_services_factory(backend_factory)
    try:
        args = parser.parse_args(args_list)
        handler = getattr(args, "handler", None)
        if handler is None:
            services = resolved_services_factory()
            print(services.help.render_root(), end="")
            return 0
        services = resolved_services_factory()
        return int(handler(args, parser, services))
    except SpecItOutRuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        return coerce_exit_code(exc.code)


def _add_group_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser], group: GroupSpec) -> None:
    group_parser = subparsers.add_parser(
        group.name,
        help=group.help,
        description=group.description,
        epilog=group.epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter if group.epilog else argparse.HelpFormatter,
    )
    group_parser.set_defaults(handler=_show_parser_help)
    group_subparsers = group_parser.add_subparsers(dest=f"{group.name}_command")
    for command in group.commands:
        _add_command_parser(group_subparsers, group, command)


def _add_command_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    group: GroupSpec,
    command: CommandSpec,
) -> None:
    command_parser = subparsers.add_parser(command.name, help=command.help, description=command.description)
    for argument in command.arguments:
        command_parser.add_argument(*argument.flags, **argument.kwargs)
    command_parser.set_defaults(handler=_resolve_handler(command.handler_key), command_path=f"{group.name} {command.name}")


def _make_services_factory(backend_factory: BackendFactory) -> ServicesFactory:
    return lambda: build_cli_services(backend_factory=backend_factory, parser_factory=build_parser)


def _resolve_handler(handler_key: str) -> Callable[[argparse.Namespace, argparse.ArgumentParser, CliServices], int]:
    handlers = {
        "app_show": _handle_app_show,
        "import_status": _handle_import_status,
        "import_retry": _handle_import_retry,
        "import_activate": _handle_import_activate,
        "index_status": _handle_index_status,
        "index_rebuild": _handle_index_rebuild,
        "index_resume": _handle_index_resume,
        "import_add": _handle_import_add,
        "import_list": _handle_import_list,
        "query_search": _handle_query_search,
        "query_entity": _handle_query_entity,
        "query_usage": _handle_query_usage,
        "query_paths": _handle_query_paths,
        "bundle_build": _handle_bundle_build,
        "placeholder": _handle_placeholder_command,
    }
    try:
        return handlers[handler_key]
    except KeyError as exc:
        raise KeyError(f"Unknown handler key: {handler_key}") from exc


def _handle_help_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    topic = list(getattr(args, "topic", []))
    print(services.help.render_topic(topic), end="")
    return 0


def _handle_index_status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.index.status(
        app_slug=getattr(args, "app_slug", None),
        version_label=getattr(args, "version_label", None),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_index_rebuild(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.index.rebuild(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label"),
        limit=getattr(args, "limit", None),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_index_resume(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.index.resume(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label"),
        initial_limit=getattr(args, "initial_limit"),
        min_limit=getattr(args, "min_limit"),
        max_passes=getattr(args, "max_passes"),
        stuck_pass_threshold=getattr(args, "stuck_pass_threshold"),
        sleep_seconds=getattr(args, "sleep_seconds"),
    )
    print(render_envelope(envelope), end="")
    return 0 if envelope["status"] == "ok" else 2


def _handle_import_status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.import_.status(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label", None),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_import_retry(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.import_.retry(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label"),
        export_path=getattr(args, "export_path", None),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_import_activate(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.import_.activate(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label"),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_app_show(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.app.show(app_slug=getattr(args, "app_slug"))
    print(render_envelope(envelope), end="")
    return 0


def _handle_import_add(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.import_.add(
        app_slug=getattr(args, "app_slug"),
        version_label=getattr(args, "version_label"),
        export_path=getattr(args, "export_path"),
        display_name=getattr(args, "display_name", None),
        source_system=getattr(args, "source_system"),
        external_app_id=getattr(args, "external_app_id", None),
    )
    print(render_envelope(envelope), end="")
    return 0


def _handle_import_list(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.import_.list(app_slug=getattr(args, "app_slug", None))
    print(render_envelope(envelope), end="")
    return 0


def _handle_query_search(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.retrieval.search(
        app_slug=getattr(args, "app_slug"),
        query_text=getattr(args, "query_text"),
        version_label=getattr(args, "version_label", None),
        mode=getattr(args, "mode"),
        limit=getattr(args, "limit"),
    )
    _print_envelope(envelope, args)
    return 0


def _handle_query_entity(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.retrieval.entity(
        app_slug=getattr(args, "app_slug"),
        entity_lookup=getattr(args, "entity_lookup"),
        version_label=getattr(args, "version_label", None),
    )
    _print_envelope(envelope, args)
    return 0


def _handle_query_usage(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.retrieval.usage(
        app_slug=getattr(args, "app_slug"),
        entity_lookup=getattr(args, "entity_lookup"),
        version_label=getattr(args, "version_label", None),
        direction=getattr(args, "direction"),
        relation=getattr(args, "relation", None),
        limit=getattr(args, "limit"),
    )
    _print_envelope(envelope, args)
    return 0


def _handle_query_paths(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.retrieval.paths(
        app_slug=getattr(args, "app_slug"),
        from_lookup=getattr(args, "from_lookup"),
        to_lookup=getattr(args, "to_lookup"),
        version_label=getattr(args, "version_label", None),
        direction=getattr(args, "direction"),
        relation=getattr(args, "relation", None),
        max_hops=getattr(args, "max_hops"),
        max_paths=getattr(args, "max_paths"),
    )
    _print_envelope(envelope, args)
    return 0


def _handle_bundle_build(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = services.bundle.build(
        app_slug=getattr(args, "app_slug"),
        query_text=getattr(args, "query_text", None),
        entity_key=getattr(args, "entity_key", None),
        version_label=getattr(args, "version_label", None),
        mode=getattr(args, "mode"),
        anchor_limit=getattr(args, "anchor_limit"),
        max_hops=getattr(args, "max_hops"),
        entity_limit=getattr(args, "entity_limit"),
        edge_limit=getattr(args, "edge_limit"),
    )
    _print_envelope(envelope, args)
    return 0


def _handle_placeholder_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    envelope = _dispatch_placeholder(args, services)
    print(render_envelope(envelope), end="")
    return 0


def _show_parser_help(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    services: CliServices,
) -> int:
    del parser
    topic = [getattr(args, "command", "help")]
    print(services.help.render_topic(topic), end="")
    return 0


def _print_envelope(envelope: CommandEnvelope, args: argparse.Namespace) -> None:
    output_format = getattr(args, "output_format", "text")
    renderer = render_json_envelope if output_format == "json" else render_envelope
    print(renderer(envelope), end="")


def _dispatch_placeholder(args: argparse.Namespace, services: CliServices) -> CommandEnvelope:
    command_path = getattr(args, "command_path", "")
    handlers: dict[str, Callable[[], CommandEnvelope]] = {
        "app list": lambda: services.app.list(),
        "import status": lambda: services.import_.status(),
        "import activate": lambda: services.import_.activate(),
        "index rebuild": lambda: services.index.rebuild(),
        "query search": lambda: services.retrieval.search(),
        "query entity": lambda: services.retrieval.entity(),
        "query usage": lambda: services.retrieval.usage(),
        "query paths": lambda: services.retrieval.paths(),
        "task start": lambda: services.task.start(),
        "task finish": lambda: services.task.finish(),
        "license activate": lambda: services.license.activate(),
        "license deactivate": lambda: services.license.deactivate(),
        "license status": lambda: services.license.status(),
        "trial status": lambda: services.trial.status(),
    }
    try:
        return handlers[command_path]()
    except KeyError as exc:
        raise KeyError(f"Unknown placeholder command path: {command_path}") from exc
