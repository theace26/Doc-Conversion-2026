"""
Local sentence-transformers embedding provider for MarkFlow vector search.

The SentenceTransformer model is lazy-loaded on first use (same pattern as
Whisper in this codebase) so importing this module at startup has zero cost.

Configuration
-------------
EMBEDDING_MODEL env var — name of the sentence-transformers model to use.
Defaults to "all-MiniLM-L6-v2" (384-dim, fast, good quality).

Usage
-----
    from core.vector.embedder import get_embedder

    embedder = get_embedder()
    vectors = embedder.embed(["hello world", "another text"])
"""

import os
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# Module-level singleton cache
_cached_embedder: Optional["LocalEmbedder"] = None

# Known dimensions for common models — used to answer `.dimension` before the
# model is loaded.  Falls back to loading the model when the name is unknown.
_KNOWN_DIMENSIONS: dict[str, int] = {
    "all-MiniLM-L6-v2": 384,
    "all-MiniLM-L12-v2": 384,
    "all-mpnet-base-v2": 768,
    "multi-qa-MiniLM-L6-cos-v1": 384,
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
}

_DEFAULT_MODEL = "all-MiniLM-L6-v2"


class LocalEmbedder:
    """
    Sentence-transformers embedding provider with lazy model loading.

    The underlying SentenceTransformer is not instantiated until the first
    call to :meth:`embed` or an explicit call to :meth:`_load_model`.
    This keeps startup fast even if the library is large.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None  # loaded on first use

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """Name of the sentence-transformers model."""
        return self._model_name

    @property
    def dimension(self) -> int:
        """Embedding dimension for the configured model."""
        if self._model_name in _KNOWN_DIMENSIONS:
            return _KNOWN_DIMENSIONS[self._model_name]
        # Unknown model — load it and ask
        model = self._load_model()
        return model.get_sentence_embedding_dimension()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Encode *texts* and return normalized float vectors.

        Parameters
        ----------
        texts:
            List of strings to embed.  An empty list returns ``[]``.

        Returns
        -------
        list[list[float]]
            One vector per input text, each of length :attr:`dimension`.
        """
        if not texts:
            return []

        model = self._load_model()

        log.debug("embedder_encoding", model=self._model_name, count=len(texts))
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        # Convert numpy array rows → plain Python float lists
        return [v.tolist() for v in vectors]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self):
        """Lazy-load the SentenceTransformer model (cached on instance)."""
        if self._model is not None:
            return self._model

        # Lazy import — sentence_transformers is heavy and may not be installed
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        log.info("embedder_loading_model", model=self._model_name)
        self._model = SentenceTransformer(self._model_name)
        log.info("embedder_model_loaded", model=self._model_name)
        return self._model


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------


def get_embedder() -> LocalEmbedder:
    """
    Return a cached :class:`LocalEmbedder` singleton.

    Reads ``EMBEDDING_MODEL`` from the environment on first call; subsequent
    calls always return the same instance regardless of env changes.
    """
    global _cached_embedder
    if _cached_embedder is None:
        model_name = os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)
        log.debug("embedder_creating_singleton", model=model_name)
        _cached_embedder = LocalEmbedder(model_name=model_name)
    return _cached_embedder
