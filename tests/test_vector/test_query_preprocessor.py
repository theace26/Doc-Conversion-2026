"""Tests for core.vector.query_preprocessor."""

import pytest

from core.vector.query_preprocessor import QueryIntent, preprocess_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(query: str) -> QueryIntent:
    return preprocess_query(query)


# ---------------------------------------------------------------------------
# Temporal intent detection
# ---------------------------------------------------------------------------

class TestTemporalIntentDetected:
    """Queries that SHOULD set has_temporal_intent=True."""

    @pytest.mark.parametrize("query", [
        "latest security policy",
        "show me the latest report",
        "current guidelines for onboarding",
        "most recent changes to the handbook",
        "newest version of the API spec",
        "recent updates to compliance rules",
        "recently updated tax forms",
        "up to date pricing sheet",
        "up-to-date pricing sheet",
        "this year's budget template",
        "what is the current policy?",
        "find me the newest data retention rules",
        "now that the rules changed, what applies?",
        "today's briefing notes",
    ])
    def test_temporal_flag_set(self, query: str):
        assert _result(query).has_temporal_intent is True, (
            f"Expected temporal intent for: {query!r}"
        )


class TestNoTemporalIntent:
    """Queries that should NOT set has_temporal_intent."""

    @pytest.mark.parametrize("query", [
        "password reset procedure",
        "how do I request a purchase order",
        "find me the employee handbook",
        "where is the printer driver",
        "expense reimbursement form",
        "GDPR data processing agreement",
    ])
    def test_temporal_flag_not_set(self, query: str):
        assert _result(query).has_temporal_intent is False, (
            f"Did not expect temporal intent for: {query!r}"
        )


# ---------------------------------------------------------------------------
# Question-prefix stripping
# ---------------------------------------------------------------------------

class TestPrefixStripping:
    """Prefixes should be removed; the core content must remain."""

    @pytest.mark.parametrize("query, expected_core", [
        ("what are the data retention rules",       "data retention rules"),
        ("what is the password policy",             "password policy"),
        ("where is the printer driver",             "printer driver"),
        ("find me the employee handbook",           "employee handbook"),
        ("show me the expense reimbursement form",  "expense reimbursement form"),
        ("give me the onboarding checklist",        "onboarding checklist"),
        ("get me the travel policy",                "travel policy"),
        ("tell me about the GDPR policy",           "GDPR policy"),
        ("search for the latest API spec",          "latest API spec"),
        ("look up the vendor agreement",            "vendor agreement"),
        ("how do I reset my password",              "reset my password"),
        ("how can I submit an expense report",      "submit an expense report"),
        ("can you find the network diagram",        "network diagram"),
        ("can you show me the org chart",           "org chart"),
        ("who is the compliance officer",           "compliance officer"),
        ("when is the next review cycle",           "next review cycle"),
        ("why is the build failing",                "build failing"),
        ("what",                                    ""),   # degenerate: only prefix
    ])
    def test_prefix_stripped(self, query: str, expected_core: str):
        result = _result(query)
        assert result.normalized_query == expected_core, (
            f"Query {query!r} → expected {expected_core!r}, "
            f"got {result.normalized_query!r}"
        )

    def test_prefix_case_insensitive(self):
        assert _result("FIND ME THE handbook").normalized_query == "handbook"
        assert _result("What Are The rules").normalized_query == "rules"

    def test_only_one_prefix_stripped(self):
        # "what are the" is stripped; the remaining text starts with "show me"
        # which should NOT be stripped again (single pass).
        result = _result("what are the show me documents")
        # First prefix ("what are the") removed; "show me documents" stays.
        assert result.normalized_query == "show me documents"


# ---------------------------------------------------------------------------
# Plain queries — no modification
# ---------------------------------------------------------------------------

class TestPlainQuery:
    def test_plain_query_unchanged(self):
        q = "password reset procedure"
        assert _result(q).normalized_query == q

    def test_plain_query_mixed_case_preserved(self):
        q = "GDPR Data Processing Agreement"
        assert _result(q).normalized_query == q


# ---------------------------------------------------------------------------
# Whitespace collapsing
# ---------------------------------------------------------------------------

class TestWhitespaceCollapsing:
    def test_leading_trailing_whitespace_stripped(self):
        assert _result("  expense form  ").normalized_query == "expense form"

    def test_internal_whitespace_collapsed(self):
        assert _result("employee   handbook").normalized_query == "employee handbook"

    def test_tab_and_newline_collapsed(self):
        assert _result("vendor\t  agreement\nnotes").normalized_query == (
            "vendor agreement notes"
        )

    def test_whitespace_after_prefix_strip_collapsed(self):
        # After stripping "what are the " the remainder might have extra spaces.
        result = _result("what are the   retention   rules")
        assert result.normalized_query == "retention rules"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        result = _result("")
        assert result.original_query == ""
        assert result.normalized_query == ""
        assert result.has_temporal_intent is False

    def test_whitespace_only(self):
        result = _result("   ")
        assert result.normalized_query == ""
        assert result.has_temporal_intent is False

    def test_original_query_always_preserved(self):
        raw = "  what is the  LATEST   policy?  "
        result = _result(raw)
        assert result.original_query == raw

    def test_temporal_word_in_prefix_still_detected(self):
        # "latest" lives inside the prefix region but must still be detected.
        result = _result("what is the latest expense policy")
        assert result.has_temporal_intent is True
        assert result.normalized_query == "latest expense policy"

    def test_returns_query_intent_dataclass(self):
        result = _result("some query")
        assert isinstance(result, QueryIntent)

    def test_single_word_query(self):
        result = _result("handbook")
        assert result.normalized_query == "handbook"
        assert result.has_temporal_intent is False

    def test_question_mark_retained(self):
        result = _result("what is the refund policy?")
        assert result.normalized_query == "refund policy?"
