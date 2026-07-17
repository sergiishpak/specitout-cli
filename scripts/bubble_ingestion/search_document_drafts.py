from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from bubble_ingestion.errors import IngestionError


@dataclass(frozen=True)
class SearchDocumentDraft:
    document: dict[str, Any]
    associations: list[dict[str, Any]]


def _nonempty(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _join_text(parts: list[str | None], *, separator: str = " | ") -> str:
    text = separator.join(_nonempty(parts))
    if not text:
        raise IngestionError("search document text unexpectedly empty")
    return text


def _join_search_text(parts: list[str | None]) -> str:
    return _join_text(parts)


def _join_semantic_text(parts: list[str | None]) -> str:
    normalized = [part.rstrip(".") for part in _nonempty(parts)]
    return _join_text([f"{part}." for part in normalized], separator=" ")


def _entity_semantic_text(entity: dict[str, Any], semantic: dict[str, Any]) -> str:
    display_name = str(entity.get("display_name") or entity.get("entity_key") or "Unknown").strip()
    entity_type = str(entity.get("entity_type") or "entity").replace("_", " ").strip()
    structural = dict(entity.get("structural_json") or {})
    aliases = _nonempty([str(alias) for alias in list(semantic.get("aliases") or [])])
    keywords = _nonempty([str(keyword) for keyword in list(semantic.get("keywords") or [])])
    tags = _nonempty([str(tag) for tag in list(semantic.get("tags") or [])])
    domains = _nonempty([str(domain) for domain in list(semantic.get("domains") or [])])
    integrations = _nonempty([str(item) for item in list(semantic.get("external_integrations") or [])])
    behaviors = _semantic_behavior_descriptions(structural, semantic)
    return _join_semantic_text(
        [
            f"{display_name} is a {entity_type}",
            _entity_summary(entity),
            _semantic_context(entity, structural),
            f"Behavior includes {', '.join(behaviors)}" if behaviors else None,
            f"Also known as {', '.join(aliases)}" if aliases else None,
            f"Relevant terms include {', '.join(keywords)}" if keywords else None,
            f"Tagged with {', '.join(tags)}" if tags else None,
            f"Related domains: {', '.join(domains)}" if domains else None,
            f"Integrates with {', '.join(integrations)}" if integrations else None,
            f"Defined at {entity.get('source_path')}" if entity.get("source_path") else None,
        ]
    )


def _semantic_context(entity: dict[str, Any], structural: dict[str, Any]) -> str | None:
    context = str(structural.get("context") or "").strip()
    if context:
        return context
    parent = entity.get("parent_entity_key") or structural.get("parent_entity_key")
    if parent:
        return f"Context parent is {parent}"
    return None


def _semantic_behavior_descriptions(structural: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    descriptions: list[str | None] = []
    for source in (semantic, structural):
        raw = source.get("behavior_descriptions", source.get("behaviors"))
        if isinstance(raw, list):
            descriptions.extend(str(item) for item in raw)
        elif isinstance(raw, str):
            descriptions.append(raw)
    return _nonempty(descriptions)


def _endpoint_semantic_text(
    *,
    entity: dict[str, Any],
    workflow_name: str,
    trigger_option: str | None,
    requires_auth: bool,
    accepts_request_data: bool,
    request_source_path: str | None,
) -> str:
    display_name = str(entity.get("display_name") or workflow_name).strip()
    auth_text = "requires authentication" if requires_auth else "is publicly callable"
    request_text = "accepts request data" if accepts_request_data else "does not accept a request body"
    return _join_semantic_text(
        [
            f"Public API workflow {workflow_name} for {display_name}",
            f"It uses the {trigger_option} trigger" if trigger_option else None,
            auth_text,
            request_text,
            _entity_summary(entity),
            f"Request metadata comes from {request_source_path}" if request_source_path else None,
            f"Entity source path is {entity.get('source_path')}" if entity.get("source_path") else None,
        ]
    )


def _data_api_surface_semantic_text(
    *,
    app_settings: dict[str, Any],
    data_api_surface: dict[str, Any],
    supporting_names: list[str],
) -> str:
    return _join_semantic_text(
        [
            "The application exposes a data API surface",
            "Workflow API is enabled" if data_api_surface.get("exposes_wf_api") else "Workflow API is disabled",
            "GET API is enabled" if data_api_surface.get("exposes_get_api") else "GET API is disabled",
            f"Public workflow count {int(data_api_surface.get('public_workflow_count') or 0)}",
            _entity_summary(app_settings),
            f"Related public workflows: {', '.join(supporting_names)}" if supporting_names else None,
        ]
    )


def _permission_surface_semantic_text(
    *,
    entity: dict[str, Any],
    user_type: dict[str, Any],
    role_descriptions: list[str],
) -> str:
    return _join_semantic_text(
        [
            f"Permission surface for {entity.get('display_name') or entity.get('entity_key')}",
            _entity_summary(entity),
            f"Defined at {user_type.get('source_path')}" if user_type.get("source_path") else None,
            f"Privacy role count {int(user_type.get('privacy_role_count') or 0)}",
            f"Granted roles: {'; '.join(role_descriptions)}" if role_descriptions else None,
        ]
    )


def _search_modes(semantic: dict[str, Any]) -> list[str]:
    modes: list[str] = []
    if semantic.get("searchable_in_root", semantic.get("searchable", True)):
        modes.append("root")
    if semantic.get("searchable_in_deep", True):
        modes.append("deep")
    return modes


def _entity_summary(entity: dict[str, Any]) -> str | None:
    return str(entity.get("summary") or "").strip() or None


def _decode_json_bytes(payload: bytes) -> dict[str, Any]:
    raw = payload.decode("utf-8").strip()
    if not raw:
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise IngestionError("semantic index payload must decode to an object")
    return loaded


def decode_semantic_index_bytes(payload: bytes) -> dict[str, Any]:
    return _decode_json_bytes(payload)


def _app_settings_flags(entity_rows: list[dict[str, Any]]) -> dict[str, Any]:
    app_settings = next((row for row in entity_rows if row.get("entity_type") == "app_settings"), None)
    if app_settings is None:
        return {}
    structural = dict(app_settings.get("structural_json") or {})
    return dict(structural.get("client_safe_flags") or {})


def build_local_semantic_indexes(pack_dir: Any) -> dict[str, dict[str, Any]]:
    base = pack_dir / "semantic/indexes"
    return {
        "permission_surface_index": _decode_json_bytes((base / "permission_surface_index.json").read_bytes()),
        "data_api_surface": _decode_json_bytes((base / "data_api_surface.json").read_bytes()),
    }


def build_relational_semantic_indexes(
    *,
    entity_rows: list[dict[str, Any]],
    public_api_rows: list[dict[str, Any]],
    permission_surface_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    flags = _app_settings_flags(entity_rows)
    public_workflow_entity_keys = _nonempty([str(row["entity_key"]) for row in public_api_rows])
    return {
        "permission_surface_index": {
            "count": len(permission_surface_rows),
            "user_types": [
                {
                    "entity_key": row["entity_key"],
                    "source_path": row.get("source_path"),
                    "privacy_role_count": int(row.get("privacy_role_count") or 0),
                    "roles": list(row.get("roles_json") or []),
                }
                for row in permission_surface_rows
            ],
        },
        "data_api_surface": {
            "exposes_get_api": bool(flags.get("exposes_get_api")),
            "exposes_wf_api": bool(flags.get("exposes_wf_api")) or bool(public_api_rows),
            "public_workflow_count": len(public_api_rows),
            "user_type_count": len(permission_surface_rows),
            "public_workflow_entity_keys": public_workflow_entity_keys,
        },
    }


def build_search_documents(
    *,
    export_id: str,
    entity_rows: list[dict[str, Any]],
    public_api_rows: list[dict[str, Any]],
    semantic_indexes: dict[str, dict[str, Any]],
) -> list[SearchDocumentDraft]:
    entity_by_key = {str(row["entity_key"]): row for row in entity_rows}
    drafts: list[SearchDocumentDraft] = []

    for entity in entity_rows:
        semantic = dict(entity.get("semantic_json") or {})
        modes = _search_modes(semantic)
        if not modes:
            continue
        entity_key = str(entity["entity_key"])
        drafts.append(
            SearchDocumentDraft(
                document={
                    "id": str(uuid.uuid4()),
                    "export_id": export_id,
                    "document_key": f"entity:{entity_key}",
                    "primary_entity_key": entity_key,
                    "document_type": "entity",
                    "lexical_text": _join_search_text(
                        [
                            entity.get("display_name"),
                            entity.get("entity_type"),
                            *list(semantic.get("aliases") or []),
                            *list(semantic.get("keywords") or []),
                            *list(semantic.get("tags") or []),
                            *list(semantic.get("domains") or []),
                            *list(semantic.get("external_integrations") or []),
                            entity.get("source_path"),
                        ]
                    ),
                    "semantic_text": _entity_semantic_text(entity, semantic),
                    "summary_text": _entity_summary(entity),
                    "rank_signals_json": {
                        "search_modes": modes,
                        "entity_type": entity.get("entity_type"),
                        "synthetic": bool(semantic.get("synthetic")),
                        "virtual": bool(semantic.get("virtual")),
                    },
                },
                associations=[{"search_document_id": "", "export_id": export_id, "entity_key": entity_key, "association_role": "primary"}],
            )
        )

    for row in public_api_rows:
        entity_key = str(row["entity_key"])
        entity = entity_by_key.get(entity_key)
        if entity is None:
            raise IngestionError(f"public API workflow references unknown entity {entity_key}")
        workflow_name = str(row["workflow_name"])
        requires_auth = "requires authentication" if row.get("requires_auth") else "publicly callable"
        request_data = "accepts request data" if row.get("accepts_request_data") else "no request body"
        drafts.append(
            SearchDocumentDraft(
                document={
                    "id": str(uuid.uuid4()),
                    "export_id": export_id,
                    "document_key": f"endpoint:{entity_key}:{workflow_name}",
                    "primary_entity_key": entity_key,
                    "document_type": "endpoint_surface",
                    "lexical_text": _join_search_text(
                        [
                            entity.get("display_name"),
                            workflow_name,
                            row.get("trigger_option"),
                            (row.get("request_metadata_json") or {}).get("source_path"),
                            entity.get("source_path"),
                        ]
                    ),
                    "semantic_text": _endpoint_semantic_text(
                        entity=entity,
                        workflow_name=workflow_name,
                        trigger_option=str(row.get("trigger_option") or "").strip() or None,
                        requires_auth=bool(row.get("requires_auth")),
                        accepts_request_data=bool(row.get("accepts_request_data")),
                        request_source_path=(row.get("request_metadata_json") or {}).get("source_path"),
                    ),
                    "summary_text": _entity_summary(entity),
                    "rank_signals_json": {
                        "surface_type": "public_api_workflow",
                        "search_modes": ["root"],
                        "requires_auth": bool(row.get("requires_auth")),
                        "accepts_request_data": bool(row.get("accepts_request_data")),
                    },
                },
                associations=[{"search_document_id": "", "export_id": export_id, "entity_key": entity_key, "association_role": "primary"}],
            )
        )

    data_api_surface = semantic_indexes.get("data_api_surface") or {}
    if data_api_surface:
        app_settings = next((row for row in entity_rows if row.get("entity_type") == "app_settings"), None)
        if app_settings is not None:
            supporting_keys = _nonempty([
                str(entity_key)
                for entity_key in data_api_surface.get("public_workflow_entity_keys") or []
                if str(entity_key) in entity_by_key
            ])
            associations = [{"search_document_id": "", "export_id": export_id, "entity_key": str(app_settings["entity_key"]), "association_role": "primary"}]
            for entity_key in supporting_keys:
                if entity_key == app_settings["entity_key"]:
                    continue
                associations.append({"search_document_id": "", "export_id": export_id, "entity_key": entity_key, "association_role": "supporting"})
            supporting_names = [
                str(entity_by_key[entity_key].get("display_name") or entity_key)
                for entity_key in supporting_keys
                if entity_key in entity_by_key
            ]
            drafts.append(
                SearchDocumentDraft(
                    document={
                        "id": str(uuid.uuid4()),
                        "export_id": export_id,
                        "document_key": "endpoint:data_api_surface",
                        "primary_entity_key": str(app_settings["entity_key"]),
                        "document_type": "endpoint_surface",
                        "lexical_text": _join_search_text(
                            [
                                "data api surface",
                                "workflow api surface" if data_api_surface.get("exposes_wf_api") else None,
                                "get api enabled" if data_api_surface.get("exposes_get_api") else None,
                                app_settings.get("display_name"),
                                *supporting_names,
                            ]
                        ),
                        "semantic_text": _data_api_surface_semantic_text(
                            app_settings=app_settings,
                            data_api_surface=data_api_surface,
                            supporting_names=supporting_names,
                        ),
                        "summary_text": _entity_summary(app_settings),
                        "rank_signals_json": {
                            "surface_type": "data_api_surface",
                            "search_modes": ["root"],
                            "public_workflow_count": int(data_api_surface.get("public_workflow_count") or 0),
                        },
                    },
                    associations=associations,
                )
            )

    permission_surface = semantic_indexes.get("permission_surface_index") or {}
    for user_type in permission_surface.get("user_types") or []:
        entity_key = str(user_type["entity_key"])
        entity = entity_by_key.get(entity_key)
        if entity is None:
            raise IngestionError(f"permission surface references unknown entity {entity_key}")
        associations = [{"search_document_id": "", "export_id": export_id, "entity_key": entity_key, "association_role": "primary"}]
        associated_entity_keys = {entity_key}
        role_descriptions: list[str] = []
        for role in user_type.get("roles") or []:
            permissions = role.get("permissions") or {}
            granted = [permission.replace("_", " ") for permission, enabled in sorted(permissions.items()) if enabled]
            if granted:
                role_descriptions.append(f"{role.get('display') or role.get('role_key')}: {', '.join(granted)}")
            condition_entity_key = role.get("condition_entity_key")
            if condition_entity_key:
                supporting_key = str(condition_entity_key)
                if supporting_key not in entity_by_key:
                    raise IngestionError(f"permission surface references unknown condition entity {supporting_key}")
                if supporting_key in associated_entity_keys:
                    continue
                associated_entity_keys.add(supporting_key)
                associations.append({"search_document_id": "", "export_id": export_id, "entity_key": supporting_key, "association_role": "supporting"})
        drafts.append(
            SearchDocumentDraft(
                document={
                    "id": str(uuid.uuid4()),
                    "export_id": export_id,
                    "document_key": f"permission:{entity_key}",
                    "primary_entity_key": entity_key,
                    "document_type": "permission_surface",
                    "lexical_text": _join_search_text(
                        [entity.get("display_name"), "permission surface", user_type.get("source_path"), *role_descriptions]
                    ),
                    "semantic_text": _permission_surface_semantic_text(
                        entity=entity,
                        user_type=user_type,
                        role_descriptions=role_descriptions,
                    ),
                    "summary_text": _entity_summary(entity),
                    "rank_signals_json": {
                        "surface_type": "permission_surface",
                        "search_modes": ["root"],
                        "privacy_role_count": int(user_type.get("privacy_role_count") or 0),
                    },
                },
                associations=associations,
            )
        )

    for draft in drafts:
        for association in draft.associations:
            association["search_document_id"] = draft.document["id"]
    return drafts
