from __future__ import annotations


MANAGED_EXPORT_TABLES = (
    "source_evidence",
    "entities",
    "edges",
    "entity_facets",
    "overlay_links",
    "public_api_workflow_index",
    "permission_surface_index",
)

LIFECYCLE_DELETE_TABLES = (
    "ingestion_runs",
    "source_evidence",
    "entities",
    "edges",
    "entity_facets",
    "search_document_associations",
    "search_documents",
    "bundle_cache",
    "overlay_links",
    "public_api_workflow_index",
    "permission_surface_index",
)

FACET_FIELDS = (
    ("alias", "aliases"),
    ("keyword", "keywords"),
    ("tag", "tags"),
    ("domain", "domains"),
    ("integration", "external_integrations"),
)

QUERY_ELIGIBLE_READINESS = frozenset({"searchable", "embedding_pending", "ready", "degraded"})
RETRYABLE_READINESS = frozenset({"registered", "ingesting", "failed"})
DEGRADABLE_READINESS = frozenset({"searchable", "embedding_pending", "ready", "degraded"})
CUTOVER_SAFE_READINESS = frozenset({"searchable", "embedding_pending", "ready"})

REST_SCHEMA = "specitout"
UPSERT_BATCH_SIZE = 500
ENTITY_DELETE_BATCH_SIZE = 5000
DEFAULT_DELETE_BATCH_SIZE = 2_000_000
