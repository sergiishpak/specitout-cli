from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from .overlay import OverlayManager
from .source_paths import canonical_index_paths
from .shared import load_json, now_iso, write_json, write_jsonl, write_text


@dataclass
class ContextPackDependencies:
    export_loader: Callable[[Any], dict[str, Any]]
    overlay_manager_factory: Callable[[Any], Any]
    clock: Callable[[], str]
    json_writer: Callable[[Any, Any], None]
    jsonl_writer: Callable[[Any, Any], None]
    text_writer: Callable[[Any, str], None]


@dataclass
class ContextPackState:
    data: dict[str, Any]
    settings: dict[str, Any]
    settings_client_safe: dict[str, Any]
    settings_secure: dict[str, Any]
    overlay_manager: Any
    id_to_path: dict[str, str]
    entities: list[dict[str, Any]] = field(default_factory=list)
    registry_items: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"styles": [], "comments": []}
    )
    id_registry: Any = field(default_factory=lambda: defaultdict(list))
    path_registry: dict[str, str] = field(default_factory=dict)
    edge_rows: list[dict[str, Any]] = field(default_factory=list)
    unresolved_edges: list[dict[str, Any]] = field(default_factory=list)
    reverse_usage: Any = field(default_factory=lambda: defaultdict(list))
    entity_lookup_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    entity_lookup_by_id: Any = field(default_factory=lambda: defaultdict(list))
    alias_to_entity: Any = field(default_factory=lambda: defaultdict(list))
    semantic_records: list[dict[str, Any]] = field(default_factory=list)
    semantic_lookup: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_index: Any = field(default_factory=lambda: defaultdict(list))
    integration_index: Any = field(default_factory=lambda: defaultdict(list))
    glossary_terms: Any = field(default_factory=lambda: defaultdict(list))
    query_hints: dict[str, Any] = field(default_factory=dict)
    integration_ref_lookup: dict[str, str] = field(default_factory=dict)
    public_api_workflows: list[dict[str, Any]] = field(default_factory=list)
    synthetic_entity_keys: set[str] = field(default_factory=set)
    counts: dict[str, Any] = field(
        default_factory=lambda: {
            "source_domains": {},
            "emitted_entities": Counter(),
            "emitted_registries": {},
        }
    )
    root_artifact_paths: dict[str, str] = field(default_factory=dict)
    manual_edge_rows: list[dict[str, Any]] = field(default_factory=list)


def make_dependencies(
    *,
    export_loader=None,
    overlay_manager_factory=None,
    clock=None,
    json_writer=None,
    jsonl_writer=None,
    text_writer=None,
):
    return ContextPackDependencies(
        export_loader=export_loader or load_json,
        overlay_manager_factory=overlay_manager_factory or OverlayManager,
        clock=clock or now_iso,
        json_writer=json_writer or write_json,
        jsonl_writer=jsonl_writer or write_jsonl,
        text_writer=text_writer or write_text,
    )


def make_initial_state(data, overlay_manager):
    settings = data.get("settings", {})
    return ContextPackState(
        data=data,
        settings=settings,
        settings_client_safe=settings.get("client_safe", {}),
        settings_secure=settings.get("secure", {}),
        overlay_manager=overlay_manager,
        id_to_path=canonical_index_paths(data),
    )
