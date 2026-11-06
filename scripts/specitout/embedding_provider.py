from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Protocol

from specitout.progress import timed_reporter
from specitout.runtime import SpecItOutRuntimeError
from specitout.runtime_paths import resolve_embedding_cache_dir


DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_LOCAL_EMBEDDING_DIMENSIONS = 384
DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE = 32


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int
    batch_size: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class _SentenceTransformerModel(Protocol):
    def encode(self, texts: list[str], **kwargs: object) -> object:
        raise NotImplementedError


ModelFactory = Callable[..., _SentenceTransformerModel]


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LOCAL_EMBEDDING_MODEL,
        model: _SentenceTransformerModel | None = None,
        model_factory: ModelFactory | None = None,
        normalize_embeddings: bool = True,
        dimensions: int = DEFAULT_LOCAL_EMBEDDING_DIMENSIONS,
        batch_size: int = DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE,
        device: str | None = None,
        cache_folder: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._model = model
        self._model_factory = model_factory
        self._normalize_embeddings = normalize_embeddings
        self._device = device
        self._cache_folder = cache_folder

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        normalized_texts = [str(text) for text in texts]
        if not normalized_texts:
            raise SpecItOutRuntimeError("SpecItOut local embeddings input cannot be empty.")
        if any(not text.strip() for text in normalized_texts):
            raise SpecItOutRuntimeError("SpecItOut local embeddings input cannot be empty or whitespace.")

        encoded = self._load_model().encode(
            normalized_texts,
            batch_size=self.batch_size,
            normalize_embeddings=self._normalize_embeddings,
            convert_to_numpy=False,
            show_progress_bar=False,
        )
        embeddings = [_coerce_embedding(row) for row in encoded]
        if len(embeddings) != len(normalized_texts):
            raise SpecItOutRuntimeError("SpecItOut local embeddings response count did not match the submitted inputs.")
        for embedding in embeddings:
            if len(embedding) != self.dimensions:
                raise SpecItOutRuntimeError(
                    f"SpecItOut local embedding row expected {self.dimensions} dimensions, got {len(embedding)}."
                )
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def _load_model(self) -> _SentenceTransformerModel:
        if self._model is not None:
            return self._model
        with timed_reporter("embedding model") as report:
            if self._model_factory is None:
                report("loading_library", 0, 0, "loading local embedding library; first startup may take time")
                self._model_factory = _load_sentence_transformer_factory()
            kwargs: dict[str, object] = {}
            if self._device:
                kwargs["device"] = self._device
            if self._cache_folder:
                kwargs["cache_folder"] = self._cache_folder
            report("loading_model", 0, 0, f"loading local embedding model {self.model_name}; first use may download model weights into {self._cache_folder or 'the model cache'}")
            self._model = self._model_factory(self.model_name, **kwargs)
            report("model_ready", 0, 0, "local embedding model ready")
        return self._model


def create_local_embedding_provider(*, model_factory: ModelFactory | None = None) -> EmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        model_name=os.getenv("SPECITOUT_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL),
        model_factory=model_factory,
        dimensions=_positive_int_env("SPECITOUT_EMBEDDING_DIMENSIONS", DEFAULT_LOCAL_EMBEDDING_DIMENSIONS),
        batch_size=_positive_int_env("SPECITOUT_EMBEDDING_BATCH_SIZE", DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE),
        device=_optional_env("SPECITOUT_EMBEDDING_DEVICE"),
        cache_folder=resolve_embedding_cache_dir(),
    )


def _load_sentence_transformer_factory() -> Callable[[str], _SentenceTransformerModel]:
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise SpecItOutRuntimeError(
            "sentence-transformers is required for SpecItOut local embeddings. "
            "Install the local embedding extras before running embedding generation."
        ) from exc
    return SentenceTransformer


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SpecItOutRuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise SpecItOutRuntimeError(f"{name} must be a positive integer.")
    return value


def _coerce_embedding(row: object) -> list[float]:
    try:
        values = list(row)  # type: ignore[arg-type]
    except TypeError as exc:
        raise SpecItOutRuntimeError("SpecItOut local embedding rows must be iterable numeric vectors.") from exc
    return [float(value) for value in values]
