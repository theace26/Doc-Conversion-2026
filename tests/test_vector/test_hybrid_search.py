"""Tests for core.vector.hybrid_search — RRF merging and hybrid_search().

Pure-function tests (rrf_merge, deduplicate_chunks) need no mocks.
hybrid_search tests use AsyncMock to simulate a vector_manager.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from core.vector.hybrid_search import (
    RRF_K,
    deduplicate_chunks,
    hybrid_search,
    rrf_merge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kw(*ids) -> list[dict]:
    """Build a minimal keyword hit list from a sequence of string IDs."""
    return [{"id": str(i), "title": f"KW doc {i}"} for i in ids]


def _vec(*doc_ids, score_start: float = 0.9) -> list[dict]:
    """Build a minimal vector hit list from a sequence of string doc_IDs."""
    hits = []
    for idx, doc_id in enumerate(doc_ids):
        hits.append(
            {
                "doc_id": str(doc_id),
                "score": round(score_start - idx * 0.05, 3),
                "title": f"VEC doc {doc_id}",
                "source_index": "docs",
                "source_path": f"/path/{doc_id}",
                "source_format": "pdf",
            }
        )
    return hits


def _ids(results: list[dict]) -> list[str]:
    """Extract the canonical document ID from each result dict.

    Keyword hits use ``id``; raw vector hits (from deduplicate_chunks) use
    ``doc_id``.  After rrf_merge both use ``id``.
    """
    return [str(r.get("id") or r.get("doc_id")) for r in results]


# ---------------------------------------------------------------------------
# deduplicate_chunks
# ---------------------------------------------------------------------------


class TestDeduplicateChunks:
    def test_empty_list(self):
        assert deduplicate_chunks([]) == []

    def test_no_duplicates_unchanged(self):
        hits = _vec("a", "b", "c")
        result = deduplicate_chunks(hits)
        assert _ids(result) == ["a", "b", "c"]

    def test_keeps_best_score_per_doc(self):
        hits = [
            {"doc_id": "x", "score": 0.5, "title": "chunk 1"},
            {"doc_id": "x", "score": 0.9, "title": "chunk 2"},  # higher score
            {"doc_id": "x", "score": 0.3, "title": "chunk 3"},
        ]
        result = deduplicate_chunks(hits)
        assert len(result) == 1
        assert result[0]["score"] == 0.9
        assert result[0]["title"] == "chunk 2"

    def test_preserves_relative_order_of_first_occurrences(self):
        hits = [
            {"doc_id": "b", "score": 0.8},
            {"doc_id": "a", "score": 0.7},
            {"doc_id": "b", "score": 0.6},  # duplicate of b, lower score
            {"doc_id": "c", "score": 0.5},
        ]
        result = deduplicate_chunks(hits)
        assert [r["doc_id"] for r in result] == ["b", "a", "c"]

    def test_multiple_docs_with_duplicates(self):
        hits = [
            {"doc_id": "a", "score": 0.4},
            {"doc_id": "b", "score": 0.9},
            {"doc_id": "a", "score": 0.8},  # best for a
            {"doc_id": "b", "score": 0.6},
        ]
        result = deduplicate_chunks(hits)
        assert len(result) == 2
        by_id = {r["doc_id"]: r for r in result}
        assert by_id["a"]["score"] == 0.8
        assert by_id["b"]["score"] == 0.9

    def test_hit_without_doc_id_skipped(self):
        hits = [
            {"score": 0.9},          # no doc_id
            {"doc_id": "x", "score": 0.5},
        ]
        result = deduplicate_chunks(hits)
        assert len(result) == 1
        assert result[0]["doc_id"] == "x"


# ---------------------------------------------------------------------------
# rrf_merge — both sources present
# ---------------------------------------------------------------------------


class TestRrfMergeCombinesBothSources:
    def test_docs_from_both_lists_appear_in_result(self):
        kw = _kw("a", "b")
        vec = _vec("c", "d")
        result = rrf_merge(kw, vec)
        result_ids = _ids(result)
        for doc_id in ["a", "b", "c", "d"]:
            assert doc_id in result_ids

    def test_doc_in_both_lists_ranks_higher_than_doc_in_one(self):
        # "overlap" appears in both lists at reasonable ranks.
        # "kw_only" and "vec_only" each appear in only one list.
        kw = _kw("overlap", "kw_only")
        vec = _vec("overlap", "vec_only")
        result = rrf_merge(kw, vec)
        result_ids = _ids(result)

        overlap_pos = result_ids.index("overlap")
        kw_only_pos = result_ids.index("kw_only")
        vec_only_pos = result_ids.index("vec_only")

        assert overlap_pos < kw_only_pos, (
            f"overlap ({overlap_pos}) should rank above kw_only ({kw_only_pos})"
        )
        assert overlap_pos < vec_only_pos, (
            f"overlap ({overlap_pos}) should rank above vec_only ({vec_only_pos})"
        )

    def test_rrf_score_attached_to_each_result(self):
        result = rrf_merge(_kw("a"), _vec("a"))
        assert all("_rrf_score" in r for r in result)
        # Document in both lists should have a higher score than 1/(k+1)
        score = result[0]["_rrf_score"]
        max_single = 1.0 / (RRF_K + 1)
        assert score > max_single

    def test_ordering_reflects_rrf_score(self):
        result = rrf_merge(_kw("a", "b", "c"), _vec("a", "b", "c"))
        scores = [r["_rrf_score"] for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# rrf_merge — keyword tiebreaker
# ---------------------------------------------------------------------------


class TestRrfTiebreaker:
    def test_keyword_hit_beats_vector_only_on_equal_score(self):
        """
        Create a situation where a keyword-only doc and a vector-only doc
        have the same RRF score (same rank in their respective lists, neither
        overlaps).  The keyword doc must rank first.
        """
        # Both appear at rank 0 in their respective single-element lists,
        # so both earn exactly 1/(k + 0 + 1).
        kw = _kw("kw_doc")
        vec = _vec("vec_doc")
        result = rrf_merge(kw, vec)
        result_ids = _ids(result)

        assert result_ids.index("kw_doc") < result_ids.index("vec_doc"), (
            "Keyword hit should beat vector-only hit when RRF scores are equal"
        )


# ---------------------------------------------------------------------------
# rrf_merge — empty inputs
# ---------------------------------------------------------------------------


class TestRrfMergeEmptyInputs:
    def test_empty_vector_results_returns_keyword_results(self):
        kw = _kw("a", "b", "c")
        result = rrf_merge(kw, [])
        result_ids = _ids(result)
        assert result_ids == ["a", "b", "c"]

    def test_empty_keyword_results_returns_vector_results(self):
        vec = _vec("x", "y")
        result = rrf_merge([], vec)
        result_ids = _ids(result)
        assert set(result_ids) == {"x", "y"}

    def test_both_empty_returns_empty(self):
        assert rrf_merge([], []) == []

    def test_vector_only_hits_have_minimal_metadata(self):
        vec = _vec("42")
        result = rrf_merge([], vec)
        assert len(result) == 1
        doc = result[0]
        assert doc["id"] == "42"
        assert doc["_vector_only"] is True
        for field in ("title", "source_index", "source_path", "source_format"):
            assert field in doc

    def test_keyword_only_hits_preserve_metadata(self):
        kw = [{"id": "99", "title": "Policy Doc", "extra_field": "hello"}]
        result = rrf_merge(kw, [])
        assert result[0]["extra_field"] == "hello"
        assert "_vector_only" not in result[0]


# ---------------------------------------------------------------------------
# rrf_merge — limit parameter
# ---------------------------------------------------------------------------


class TestRrfMergeLimit:
    def test_limit_truncates_results(self):
        kw = _kw("a", "b", "c", "d", "e")
        vec = _vec("f", "g", "h")
        result = rrf_merge(kw, vec, limit=3)
        assert len(result) == 3

    def test_limit_zero_returns_all(self):
        kw = _kw("a", "b")
        vec = _vec("c", "d")
        result = rrf_merge(kw, vec, limit=0)
        assert len(result) == 4

    def test_limit_larger_than_results_returns_all(self):
        kw = _kw("a")
        vec = _vec("b")
        result = rrf_merge(kw, vec, limit=100)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# rrf_merge — RRF formula correctness
# ---------------------------------------------------------------------------


class TestRrfFormula:
    def test_score_formula_matches_expected(self):
        """Manually compute expected RRF score for a doc at rank 0 in both lists."""
        kw = _kw("a")
        vec = _vec("a")
        result = rrf_merge(kw, vec)
        expected = 1.0 / (RRF_K + 0 + 1) + 1.0 / (RRF_K + 0 + 1)
        assert abs(result[0]["_rrf_score"] - expected) < 1e-10

    def test_higher_rank_yields_lower_score(self):
        """A doc at rank 0 must score higher than one at rank 1 (same single list)."""
        kw = _kw("first", "second")
        result = rrf_merge(kw, [])
        scores = {r["id"]: r["_rrf_score"] for r in result}
        assert scores["first"] > scores["second"]

    def test_custom_k_affects_scores(self):
        kw = _kw("a")
        r_default = rrf_merge(kw, [], k=RRF_K)
        r_small_k = rrf_merge(kw, [], k=1)
        # Smaller k → less dampening → higher score for top-ranked doc
        assert r_small_k[0]["_rrf_score"] > r_default[0]["_rrf_score"]


# ---------------------------------------------------------------------------
# hybrid_search — async
# ---------------------------------------------------------------------------


class TestHybridSearch:
    @pytest.fixture
    def make_vector_manager(self):
        """Factory: return a mock vector_manager that yields given hits."""

        def _factory(hits: list[dict] | None = None, raises: Exception | None = None):
            mock = AsyncMock()
            if raises is not None:
                mock.search.side_effect = raises
            else:
                mock.search.return_value = hits or []
            return mock

        return _factory

    async def test_returns_keyword_results_when_vector_manager_is_none(self):
        kw = _kw("a", "b")
        result = await hybrid_search("test", kw, None)
        assert result == kw

    async def test_returns_keyword_results_when_vector_search_raises(
        self, make_vector_manager
    ):
        kw = _kw("a", "b")
        vm = make_vector_manager(raises=RuntimeError("Qdrant down"))
        result = await hybrid_search("test", kw, vm)
        assert result == kw

    async def test_merges_results_from_both_sources(self, make_vector_manager):
        kw = _kw("a", "b")
        vm = make_vector_manager(_vec("c", "d"))
        result = await hybrid_search("test", kw, vm, limit=10)
        result_ids = _ids(result)
        for doc_id in ["a", "b", "c", "d"]:
            assert doc_id in result_ids

    async def test_doc_in_both_ranks_highest(self, make_vector_manager):
        kw = _kw("overlap", "kw_only")
        vm = make_vector_manager(_vec("overlap", "vec_only"))
        result = await hybrid_search("test", kw, vm, limit=10)
        result_ids = _ids(result)
        assert result_ids[0] == "overlap"

    async def test_limit_is_respected(self, make_vector_manager):
        kw = _kw("a", "b", "c")
        vm = make_vector_manager(_vec("d", "e", "f"))
        result = await hybrid_search("test", kw, vm, limit=4)
        assert len(result) == 4

    async def test_vector_manager_called_with_correct_args(self, make_vector_manager):
        kw = _kw("a")
        vm = make_vector_manager(_vec("b"))
        filters = {"source_format": "pdf"}
        await hybrid_search("my query", kw, vm, filters=filters, limit=15)
        vm.search.assert_awaited_once_with("my query", filters=filters, limit=15)

    async def test_empty_vector_results_returns_keyword_results(
        self, make_vector_manager
    ):
        kw = _kw("a", "b", "c")
        vm = make_vector_manager([])
        result = await hybrid_search("test", kw, vm, limit=10)
        result_ids = _ids(result)
        assert result_ids == ["a", "b", "c"]

    async def test_empty_keyword_results_returns_vector_only(
        self, make_vector_manager
    ):
        vm = make_vector_manager(_vec("x", "y"))
        result = await hybrid_search("test", [], vm, limit=10)
        result_ids = _ids(result)
        assert set(result_ids) == {"x", "y"}
        for doc in result:
            assert doc.get("_vector_only") is True
