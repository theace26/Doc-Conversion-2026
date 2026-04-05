"""
Tests for core.vector.embedder — LocalEmbedder and get_embedder().

sentence_transformers may not be installed in all environments.  Every test
that requires the library is collected under the ``st`` mark and the whole
module skips gracefully when the import fails.
"""

import importlib
import math
import os

import pytest

# Skip the entire module if sentence_transformers is not available.
# pytest.importorskip raises Skipped (not an error) so CI stays green.
sentence_transformers = pytest.importorskip("sentence_transformers")

from core.vector.embedder import LocalEmbedder, _DEFAULT_MODEL, get_embedder  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two pre-normalised vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def embedder() -> LocalEmbedder:
    """Single LocalEmbedder instance shared across tests in this module."""
    return LocalEmbedder(model_name=_DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_model_name_property(embedder: LocalEmbedder) -> None:
    assert embedder.model_name == _DEFAULT_MODEL


def test_dimension_property_known_model(embedder: LocalEmbedder) -> None:
    """all-MiniLM-L6-v2 must report dimension 384 without loading the model."""
    assert embedder.dimension == 384


def test_dimension_matches_actual_output(embedder: LocalEmbedder) -> None:
    """The reported dimension must equal the length of a real embedding."""
    vectors = embedder.embed(["sanity check"])
    assert len(vectors[0]) == embedder.dimension


# ---------------------------------------------------------------------------
# Embed — basic correctness
# ---------------------------------------------------------------------------


def test_embed_empty_list(embedder: LocalEmbedder) -> None:
    result = embedder.embed([])
    assert result == []


def test_embed_single_text(embedder: LocalEmbedder) -> None:
    result = embedder.embed(["hello world"])
    assert len(result) == 1
    vec = result[0]
    assert isinstance(vec, list)
    assert len(vec) == 384
    # All elements must be floats
    assert all(isinstance(v, float) for v in vec)


def test_embed_multiple_texts(embedder: LocalEmbedder) -> None:
    texts = ["first sentence", "second sentence", "third sentence"]
    result = embedder.embed(texts)
    assert len(result) == len(texts)
    for vec in result:
        assert len(vec) == 384


def test_embed_returns_correct_dimension(embedder: LocalEmbedder) -> None:
    """Vectors must have exactly `dimension` elements."""
    texts = ["one", "two", "three", "four", "five"]
    result = embedder.embed(texts)
    for vec in result:
        assert len(vec) == embedder.dimension


def test_embed_vectors_are_normalised(embedder: LocalEmbedder) -> None:
    """Embeddings should be unit-norm (L2) within floating-point tolerance."""
    result = embedder.embed(["normalisation test sentence"])
    vec = result[0]
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"


# ---------------------------------------------------------------------------
# Semantic similarity
# ---------------------------------------------------------------------------


def test_similar_texts_have_higher_cosine_similarity(embedder: LocalEmbedder) -> None:
    """
    Two semantically related sentences should be closer to each other than
    either is to a completely unrelated sentence.
    """
    texts = [
        "The cat sat on the mat.",        # anchor
        "A cat is resting on a rug.",     # similar to anchor
        "Quantum entanglement in physics.", # unrelated
    ]
    vectors = embedder.embed(texts)
    anchor, similar, unrelated = vectors

    sim_related = _cosine_similarity(anchor, similar)
    sim_unrelated = _cosine_similarity(anchor, unrelated)

    assert sim_related > sim_unrelated, (
        f"Expected similar pair ({sim_related:.4f}) > "
        f"unrelated pair ({sim_unrelated:.4f})"
    )


def test_identical_texts_have_similarity_one(embedder: LocalEmbedder) -> None:
    """Two identical strings must have cosine similarity ≈ 1.0."""
    text = "MarkFlow document conversion pipeline"
    v1, v2 = embedder.embed([text, text])
    sim = _cosine_similarity(v1, v2)
    assert abs(sim - 1.0) < 1e-5, f"Expected similarity ~1.0, got {sim}"


# ---------------------------------------------------------------------------
# get_embedder singleton
# ---------------------------------------------------------------------------


def test_get_embedder_returns_local_embedder() -> None:
    result = get_embedder()
    assert isinstance(result, LocalEmbedder)


def test_get_embedder_is_singleton() -> None:
    a = get_embedder()
    b = get_embedder()
    assert a is b


def test_get_embedder_respects_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When EMBEDDING_MODEL is set *before* the first singleton creation, the
    embedder's model_name should reflect it.

    We reset the module-level cache to simulate a fresh import.
    """
    import core.vector.embedder as embedder_module

    # Patch the cache so we force re-creation
    monkeypatch.setattr(embedder_module, "_cached_embedder", None)
    monkeypatch.setenv("EMBEDDING_MODEL", "all-MiniLM-L12-v2")

    try:
        fresh = get_embedder()
        assert fresh.model_name == "all-MiniLM-L12-v2"
    finally:
        # Always restore the cache to avoid polluting other tests
        monkeypatch.setattr(embedder_module, "_cached_embedder", None)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
