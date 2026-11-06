from __future__ import annotations

from copy import deepcopy

import pytest

from specitout import backend_retrieval
from specitout.backend import PostgresLocalBackend
from specitout.bundle_service import BundleService
from specitout.retrieval_service import RetrievalService


class RetrievalDatabase:
    """Synthetic DB boundary: source exports and retrieval RPC rows only."""

    def __init__(self, documents=(), *, ready=False):
        self.export = {"id": "export-a", "app_id": "app-demo", "version_label": "v1", "readiness_status": "ready" if ready else "embedding_pending"}
        self.documents = list(documents)
        self.rpc_scopes = []
        self.search_limits = []
        self.semantic_available = ready
        self.root_entities = []
        self.root_lookups = []

    def app(self, slug):
        return {"id": "app-demo", "slug": slug}

    def fetch(self, query, params=None):
        params = params or {}
        if "as source_root_entities" in query:
            self.root_lookups.append(params)
            roots = [row for row in self.root_entities if row["source_path"] in params["root_paths"]
                     or row["source_id"] in params["root_ids"] or row["source_key"] in params["root_ids"]]
            return {"source_root_entities": roots}
        if "from specitout.apps" in query:
            return self.app(params.get("app_slug", "demo"))
        if "from specitout.exports" in query:
            return dict(self.export)
        if "from specitout.resolve_retrieval_scope" in query:
            return {"semantic_available": self.semantic_available}
        self.rpc_scopes.append(params.get("export_id"))
        scope = params.get("export_id") or self.export["id"]
        payload = {"resolved_export_id": scope, "semantic_available": self.semantic_available, "semantic_used": bool(params.get("query_embedding"))}
        if "as search_entities" in query:
            self.search_limits.append(params["limit"])
            payload["results"] = deepcopy(self.documents[:min(params["limit"], 25)])
            return {"search_entities": payload}
        if "as get_entity" in query:
            payload.update(status="found", entity={"entity_key": "backend_workflow:send", "display_name": "Send"})
            # Simulate activation changing after anchor lookup. Neighbors must keep v1.
            self.export = {**self.export, "id": "export-b", "version_label": "v2"}
            return {"get_entity": payload}
        if "as get_neighbors" in query:
            payload["neighbors"] = []
            return {"get_neighbors": payload}
        if "as find_paths" in query:
            payload["paths"] = []
            return {"find_paths": payload}
        if "as build_context_bundle" in query:
            payload.update(status="found", resolved_anchors=[], selected_entities=[], related_edges=[])
            return {"build_context_bundle": payload}
        raise AssertionError(f"Unexpected query {query}")

    def kwargs(self):
        return {"fetch_one": self.fetch, "get_application": self.app, "app_slug": "demo", "version_label": None, "export_id": None}


def document(key, name, number=1, score=0.5):
    return {"document_key": f"doc:{key}:{number}", "primary_entity_key": key, "primary_entity_display_name": name,
            "primary_entity_type": "backend_workflow", "ranking_score": score,
            "ranking_reasons": [{"type": "lexical_match", "score": score}],
            "evidence_links": [{"kind": "entity_source_path", "source_path": f"workflows.{key}.actions.{number}"}]}


@pytest.mark.parametrize("command", ["search", "entity", "usage", "paths", "bundle"])
def test_omitted_version_returns_pinned_provenance(command):
    db = RetrievalDatabase([document("backend_workflow:send", "Send")])
    kwargs = db.kwargs()
    if command == "search":
        payload = backend_retrieval.query_search(**kwargs, query_text="send", mode="root", limit=5)
    elif command == "entity":
        payload = backend_retrieval.query_entity(**kwargs, entity_lookup="Send")
    elif command == "usage":
        payload = backend_retrieval.query_usage(**kwargs, entity_lookup="Send", direction="both", relation=None, limit=5)
    elif command == "paths":
        payload = backend_retrieval.query_paths(**kwargs, from_lookup="Send", to_lookup="Email", direction="both", relation=None, max_hops=2, max_paths=3)
    else:
        payload = backend_retrieval.build_context_bundle(**kwargs, query_text="send", entity_key=None, mode="root", anchor_limit=3, max_hops=1, entity_limit=10, edge_limit=20)
    assert payload["version_label"] == "v1"
    assert payload["resolved_export_id"] == "export-a"
    assert all(scope == "export-a" for scope in db.rpc_scopes)


def test_search_fills_unique_entity_limit_and_keeps_duplicate_document_evidence():
    db = RetrievalDatabase([document("backend_workflow:a", "Send", i) for i in range(7)] + [document(f"backend_workflow:{key}", f"Send {key}") for key in "bcde"])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=5)
    results = payload["results"]
    assert [row["primary_entity_key"] for row in results] == [f"backend_workflow:{key}" for key in "abcde"]
    assert len(results[0]["matched_documents"]) == 7
    assert len(results[0]["evidence_links"]) == 7
    assert max(db.search_limits) <= 25


def test_ordinary_discovery_demotes_name_hints_preserving_scores_and_uncertainty():
    db = RetrievalDatabase([document("backend_workflow:old", "DEPRECATED send", score=0.99), document("backend_workflow:maybe", "DEPR? send", score=0.9), document("backend_workflow:send", "Send", score=0.5)])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=3)
    assert [row["primary_entity_key"] for row in payload["results"]] == ["backend_workflow:send", "backend_workflow:old", "backend_workflow:maybe"]
    uncertain = payload["results"][2]
    assert uncertain["ranking_score"] == 0.9
    assert uncertain["name_hints"][0]["uncertain"] is True
    assert uncertain["name_hints"][0]["basis"] == "name_only"
    assert any("runtime" in warning.lower() for warning in payload["warnings"])


@pytest.mark.parametrize("query", ["DEPRECATED send", "backend_workflow:old", "deprecated workflows"])
def test_explicit_deprecated_discovery_is_retained(query):
    db = RetrievalDatabase([document("backend_workflow:old", "DEPRECATED send", score=0.99), document("backend_workflow:send", "Send", score=0.5)])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text=query, mode="root", limit=2)
    assert payload["results"][0]["primary_entity_key"] == "backend_workflow:old"


def test_deprecated_inventory_request_does_not_return_unfiltered_inventory():
    db = RetrievalDatabase([document("backend_workflow:old", "DEPRECATED send")])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="list deprecated backend workflows", mode="root", limit=5)
    assert payload["results"][0]["primary_entity_key"] == "backend_workflow:old"
    assert not payload.get("answer_type")


@pytest.mark.parametrize("bundle", [False, True])
def test_embedding_pending_never_loads_query_model(bundle):
    class ExplodingProvider:
        def embed_query(self, query):
            pytest.fail("Embedding model must not be loaded without indexed vectors")
    db = RetrievalDatabase()
    if bundle:
        payload = backend_retrieval.build_context_bundle(**db.kwargs(), query_text="send", entity_key=None, mode="root", anchor_limit=3, max_hops=1, entity_limit=10, edge_limit=20, embedding_provider=ExplodingProvider())
    else:
        payload = backend_retrieval.query_search(**db.kwargs(), query_text="send", mode="root", limit=5, embedding_provider=ExplodingProvider())
    assert payload["semantic_used"] is False


def test_no_vectors_even_with_ready_status_skips_query_model():
    db = RetrievalDatabase(ready=True)
    db.semantic_available = False
    class ExplodingProvider:
        def embed_query(self, query):
            pytest.fail("No indexed vectors means no model load")
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="send", mode="root", limit=5, embedding_provider=ExplodingProvider())
    assert payload["semantic_used"] is False


def test_shortfall_at_document_cap_is_visible_and_never_filled_with_duplicates():
    db = RetrievalDatabase([document("backend_workflow:send", "Send", i) for i in range(30)])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=5)
    assert len(payload["results"]) == 1
    assert any("25" in warning and "unique" in warning for warning in payload["warnings"])


def test_command_envelopes_preserve_scope_id_and_search_hints():
    db = RetrievalDatabase([document("backend_workflow:old", "DEPR? send")])
    backend = PostgresLocalBackend(runtime_status=None, embedding_provider_factory=lambda: None)
    backend._fetch_one = db.fetch
    envelope = RetrievalService(lambda: backend).search(app_slug="demo", query_text="send", version_label=None, mode="root", limit=5)
    assert envelope["scope"] == {"app_slug": "demo", "version_label": "v1", "export_id": "export-a"}
    assert envelope["data"]["results"][0]["name_hints"][0]["uncertain"] is True
    assert envelope["data"]["results"][0]["evidence_links"]
    assert envelope["data"]["results"][0]["matched_documents"]
    assert envelope["data"]["ranking_policy"]


@pytest.mark.parametrize("selector", [{"version_label": "v1"}, {"export_id": "export-a"}])
def test_explicit_export_selection_retains_label_and_pins_rpc(selector):
    db = RetrievalDatabase([document("backend_workflow:send", "Send")])
    payload = backend_retrieval.query_search(**{**db.kwargs(), **selector}, query_text="send", mode="root", limit=5)
    assert payload["version_label"] == "v1"
    assert payload["resolved_export_id"] == "export-a"
    assert db.rpc_scopes == ["export-a"]


def test_matching_version_and_export_id_is_required():
    from specitout.runtime import SpecItOutRuntimeError
    db = RetrievalDatabase()
    with pytest.raises(SpecItOutRuntimeError, match="different versions"):
        backend_retrieval.query_entity(**{**db.kwargs(), "version_label": "v2", "export_id": "export-a"}, entity_lookup="Send")


def test_exact_ambiguous_display_name_documents_still_preserve_explicit_priority():
    old = document("backend_workflow:old", "DEPR? Send", score=0.9)
    old["ranking_reasons"] = [{"type": "ambiguous_display_name"}]
    db = RetrievalDatabase([old, document("backend_workflow:send", "Send", score=0.5)])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="DEPR? Send", mode="root", limit=2)
    assert payload["results"][0]["primary_entity_key"] == "backend_workflow:old"
    assert payload["results"][0]["ranking_score"] == 0.9


def test_semantic_used_describes_returned_candidates_instead_of_discarded_pool():
    lexical = document("backend_workflow:send", "Send", score=0.5)
    semantic = document("backend_workflow:old", "DEPRECATED send", score=0.9)
    semantic["ranking_reasons"] = [{"type": "semantic_similarity", "score": 0.9}]
    db = RetrievalDatabase([semantic, lexical], ready=True)
    class Provider:
        def embed_query(self, query):
            return [1.0, 0.0]
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=1, embedding_provider=Provider())
    assert payload["results"][0]["primary_entity_key"] == "backend_workflow:send"
    assert payload["semantic_available"] is True
    assert payload["semantic_used"] is False


@pytest.mark.parametrize("command", ["search", "entity", "usage", "paths", "bundle"])
def test_source_paths_are_normalized_on_every_retrieval_payload(command):
    db = RetrievalDatabase([document("backend_workflow:send", "Send")])
    original_fetch = db.fetch
    def fetch(query, params=None):
        row = original_fetch(query, params)
        for key in ("search_entities", "get_entity", "get_neighbors", "find_paths", "build_context_bundle"):
            if key in row:
                row[key]["evidence_links"] = [{"kind": "entity_source_path", "source_path": "%p3.PAGE.%wf.EVENT"}]
        return row
    kwargs = {**db.kwargs(), "fetch_one": fetch}
    if command == "search":
        payload = backend_retrieval.query_search(**kwargs, query_text="send", mode="root", limit=5)
    elif command == "entity":
        payload = backend_retrieval.query_entity(**kwargs, entity_lookup="Send")
    elif command == "usage":
        payload = backend_retrieval.query_usage(**kwargs, entity_lookup="Send", direction="both", relation=None, limit=5)
    elif command == "paths":
        payload = backend_retrieval.query_paths(**kwargs, from_lookup="Send", to_lookup="Email", direction="both", relation=None, max_hops=2, max_paths=3)
    else:
        payload = backend_retrieval.build_context_bundle(**kwargs, query_text=None, entity_key="backend_workflow:send", mode="root", anchor_limit=3, max_hops=1, entity_limit=10, edge_limit=20)
    assert payload["evidence_links"][0]["source_path"] == "pages.PAGE.workflows.EVENT"
    assert payload["evidence_links"][0]["source_path_alias"] == "%p3.PAGE.%wf.EVENT"


@pytest.mark.parametrize("command", ["entity", "usage", "paths", "bundle"])
def test_targeted_command_envelopes_return_resolved_scope_from_database(command):
    db = RetrievalDatabase()
    backend = PostgresLocalBackend(runtime_status=None, embedding_provider_factory=lambda: None)
    backend._fetch_one = db.fetch
    service = RetrievalService(lambda: backend)
    kwargs = {"app_slug": "demo", "version_label": None}
    if command == "entity":
        envelope = service.entity(**kwargs, entity_lookup="Send")
    elif command == "usage":
        envelope = service.usage(**kwargs, entity_lookup="Send", direction="both", relation=None, limit=5)
    elif command == "paths":
        envelope = service.paths(**kwargs, from_lookup="Send", to_lookup="Email", direction="both", relation=None, max_hops=2, max_paths=3)
    else:
        envelope = BundleService(lambda: backend).build(**kwargs, query_text=None, entity_key="backend_workflow:send", mode="root", anchor_limit=3, max_hops=1, entity_limit=10, edge_limit=20)
    assert envelope["scope"] == {"app_slug": "demo", "version_label": "v1", "export_id": "export-a"}


def test_maintenance_names_mentioning_deprecated_records_are_not_stale_markers():
    db = RetrievalDatabase([
        document("backend_workflow:cleanup", "Remove deprecated records", score=0.99),
        document("backend_workflow:old", "[DEPR?:] Send", score=0.9),
        document("backend_workflow:send", "Send", score=0.5),
    ])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=3)
    assert [row["primary_entity_key"] for row in payload["results"]] == ["backend_workflow:cleanup", "backend_workflow:send", "backend_workflow:old"]
    assert not payload["results"][0].get("name_hints")
    assert payload["results"][2]["name_hints"][0]["uncertain"] is True


@pytest.mark.parametrize("name", ["Deprecated: Send", "[DEPRECATED] Send", "DEPR?: Send", "(obsolete) Send"])
def test_leading_deprecation_name_markers_are_annotated(name):
    db = RetrievalDatabase([document("backend_workflow:old", name)])
    payload = backend_retrieval.query_search(**db.kwargs(), query_text="sending", mode="root", limit=1)
    assert payload["results"][0]["name_hints"][0]["basis"] == "name_only"


@pytest.mark.parametrize("command", ["search", "entity", "usage", "paths", "bundle"])
def test_projected_evidence_resolves_root_ids_to_actual_export_keys(command):
    db = RetrievalDatabase([document("backend_workflow:send", "Send")])
    db.root_entities = [
        {"source_path": "%p3.page-id", "source_id": "page-id", "source_domain": "pages", "source_key": "page-key"},
        {"source_path": "%ed.component-id", "source_id": "component-id", "source_domain": "element_definitions", "source_key": "component-key"},
        {"source_path": "mobile_views.mobile-id", "source_id": "mobile-id", "source_domain": "mobile_views", "source_key": "mobile-key"},
    ]
    original_fetch = db.fetch
    def fetch(query, params=None):
        row = original_fetch(query, params)
        for key in ("search_entities", "get_entity", "get_neighbors", "find_paths", "build_context_bundle"):
            if key in row:
                row[key]["evidence_links"] = [
                    {"kind": "entity_source_path", "source_path": "%p3.page-id.%wf.event-id"},
                    {"kind": "entity_source_path", "source_path": "%ed.component-id.%el.element-id"},
                    {"kind": "entity_source_path", "source_path": "mobile_views.mobile-id.elements.element-id"},
                ]
                row[key]["relation"] = {"from_source_path": "%p3.page-id", "to_source_path": "%ed.component-id"}
        return row
    kwargs = {**db.kwargs(), "fetch_one": fetch}
    if command == "search":
        payload = backend_retrieval.query_search(**kwargs, query_text="send", mode="root", limit=5)
    elif command == "entity":
        payload = backend_retrieval.query_entity(**kwargs, entity_lookup="Send")
    elif command == "usage":
        payload = backend_retrieval.query_usage(**kwargs, entity_lookup="Send", direction="both", relation=None, limit=5)
    elif command == "paths":
        payload = backend_retrieval.query_paths(**kwargs, from_lookup="Send", to_lookup="Email", direction="both", relation=None, max_hops=2, max_paths=3)
    else:
        payload = backend_retrieval.build_context_bundle(**kwargs, query_text=None, entity_key="backend_workflow:send", mode="root", anchor_limit=3, max_hops=1, entity_limit=10, edge_limit=20)
    assert [link["source_path"] for link in payload["evidence_links"]] == [
        "pages.page-key.workflows.event-id", "element_definitions.component-key.elements.element-id", "mobile_views.mobile-key.elements.element-id"]
    assert payload["evidence_links"][0]["source_path_alias"] == "%p3.page-id.%wf.event-id"
    assert payload["relation"]["from_source_path"] == "pages.page-key"
    assert payload["relation"]["to_source_path"] == "element_definitions.component-key"
    assert len(db.root_lookups) == 1
    assert db.root_lookups[0]["export_id"] == "export-a"


def test_payload_without_root_locators_needs_no_root_lookup():
    db = RetrievalDatabase([document("backend_workflow:send", "Send")])
    backend_retrieval.query_search(**db.kwargs(), query_text="send", mode="root", limit=5)
    assert db.root_lookups == []
