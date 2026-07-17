from __future__ import annotations


class IngestionError(RuntimeError):
    """Raised when the ingestion workflow cannot complete safely."""


class IngestionCanceledError(IngestionError):
    """Raised when an ingestion workflow is canceled cooperatively by operator request."""
