from __future__ import annotations

from typing import Literal, Protocol, TypedDict


CapabilityState = Literal["available", "unavailable"]


class SearchCapabilityReport(TypedDict):
    fts: CapabilityState
    fuzzy_identifier: CapabilityState
    vector_search: CapabilityState
    bulk_load: CapabilityState
    result_shape_compatible: CapabilityState


class SearchSpikeScope(TypedDict):
    app_slug: str
    version_label: str
    query_text: str


class SearchSpikeDocument(TypedDict):
    document_key: str
    identifier_text: str
    match_stage: str


class SearchSpikeData(TypedDict):
    results: list[SearchSpikeDocument]
    result_count: int


class SearchSpikeResult(TypedDict):
    status: str
    scope: SearchSpikeScope
    data: SearchSpikeData
    warnings: list[str]
    degraded: bool
    capabilities: SearchCapabilityReport


class SearchSpikeBackendProtocol(Protocol):
    def seed_fixture(self) -> None: ...

    def search_exact(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult: ...

    def search_lexical(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult: ...

    def search_fuzzy(self, *, query_text: str, app_slug: str, version_label: str) -> SearchSpikeResult: ...

    def search_vector(
        self,
        *,
        query_text: str,
        query_embedding: list[float],
        app_slug: str,
        version_label: str,
    ) -> SearchSpikeResult: ...

    def capabilities(self) -> SearchCapabilityReport: ...


FIXTURE_DOCUMENTS: tuple[dict[str, object], ...] = (
    {
        "document_key": "doc:chat-search",
        "identifier_text": "OpenAIChatSearch",
        "lexical_text": "OpenAI chat search workflow and result ranking for messages.",
        "semantic_text": "Natural language search for chat messages with OpenAI assistance.",
        "embedding_vector": [0.91, 0.08, 0.01],
    },
    {
        "document_key": "doc:message-panel",
        "identifier_text": "MessagePanel",
        "lexical_text": "Message panel layout and filter state for the chat UI.",
        "semantic_text": "User interface for reading and filtering chat messages.",
        "embedding_vector": [0.55, 0.35, 0.10],
    },
    {
        "document_key": "doc:billing-sync",
        "identifier_text": "BillingSyncJob",
        "lexical_text": "Billing synchronization for license task accounting.",
        "semantic_text": "Back office billing workflow unrelated to chat search.",
        "embedding_vector": [0.15, 0.75, 0.10],
    },
)


def default_capabilities(
    *,
    fts: CapabilityState,
    fuzzy_identifier: CapabilityState,
    vector_search: CapabilityState,
    bulk_load: CapabilityState,
) -> SearchCapabilityReport:
    return {
        "fts": fts,
        "fuzzy_identifier": fuzzy_identifier,
        "vector_search": vector_search,
        "bulk_load": bulk_load,
        "result_shape_compatible": "available",
    }


def build_result(
    *,
    query_text: str,
    app_slug: str,
    version_label: str,
    results: list[SearchSpikeDocument],
    capabilities: SearchCapabilityReport,
    warnings: list[str] | None = None,
    degraded: bool = False,
) -> SearchSpikeResult:
    return {
        "status": "ok",
        "scope": {
            "app_slug": app_slug,
            "version_label": version_label,
            "query_text": query_text,
        },
        "data": {
            "results": results,
            "result_count": len(results),
        },
        "warnings": warnings or [],
        "degraded": degraded,
        "capabilities": capabilities,
    }
