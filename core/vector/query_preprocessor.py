"""Lightweight query preprocessing for MarkFlow hybrid search.

Detects temporal intent and strips question-word prefixes so that the
normalized query can be fed to both keyword and vector search engines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Temporal-intent detection
# ---------------------------------------------------------------------------

# Words / phrases that signal the user wants recent documents.
_TEMPORAL_PATTERNS: list[str] = [
    r"\bup[\s\-]to[\s\-]date\b",
    r"\bmost\s+recent\b",
    r"\bthis\s+year\b",
    r"\bcurrent(?:ly)?\b",
    r"\blatest\b",
    r"\brecent(?:ly)?\b",
    r"\bnewest\b",
    r"\bnew\b",
    r"\btoday\b",
    r"\bnow\b",
]

_TEMPORAL_RE = re.compile(
    "|".join(_TEMPORAL_PATTERNS),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Question-prefix stripping
# ---------------------------------------------------------------------------

# Ordered from longest/most-specific to shortest so the first match wins.
_PREFIX_PATTERNS: list[str] = [
    r"what\s+(?:are|is|were|was)\s+(?:the\s+)?",
    r"where\s+(?:are|is)\s+(?:the\s+)?",
    r"when\s+(?:are|is|was|were)\s+(?:the\s+)?",
    r"who\s+(?:are|is)\s+(?:the\s+)?",
    r"how\s+(?:do|does|can|should|to)\s+(?:i\s+)?(?:the\s+)?",
    r"why\s+(?:are|is|do|does)\s+(?:the\s+)?",
    r"find\s+me\s+(?:the\s+)?",
    r"show\s+me\s+(?:the\s+)?",
    r"give\s+me\s+(?:the\s+)?",
    r"get\s+me\s+(?:the\s+)?",
    r"tell\s+me\s+(?:about\s+)?(?:the\s+)?",
    r"search\s+for\s+(?:the\s+)?",
    r"look\s+up\s+(?:the\s+)?",
    r"i\s+need\s+(?:to\s+(?:know\s+)?(?:about\s+)?)?(?:the\s+)?",
    r"i\s+want\s+(?:to\s+(?:know\s+(?:about\s+)?)?)?(?:the\s+)?",
    r"can\s+you\s+(?:find\s+(?:me\s+)?|show\s+(?:me\s+)?|tell\s+me(?:\s+about)?\s+)(?:the\s+)?",
    r"(?:what|where|when|who|how|why)\s+",
    r"(?:what|where|when|who|how|why)\b",
]

_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(_PREFIX_PATTERNS) + r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class QueryIntent:
    """Holds both the raw and normalized forms of a search query."""

    original_query: str
    normalized_query: str
    has_temporal_intent: bool


def preprocess_query(query: str) -> QueryIntent:
    """Preprocess *query* for hybrid search.

    Steps applied (in order):
    1. Detect temporal intent on the original text.
    2. Strip a leading question-word / filler prefix.
    3. Collapse runs of whitespace to a single space and strip edges.

    Parameters
    ----------
    query:
        Raw user query string.

    Returns
    -------
    QueryIntent
        Dataclass with ``original_query``, ``normalized_query``, and
        ``has_temporal_intent``.
    """
    original = query

    # 1. Temporal intent — check before any stripping so we don't miss words
    #    that appear in the prefix (e.g. "what is the latest policy?").
    has_temporal = bool(_TEMPORAL_RE.search(original))

    # 2. Strip question prefix (at most one pass).
    normalized = _PREFIX_RE.sub("", original.lstrip())

    # 3. Collapse whitespace.
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return QueryIntent(
        original_query=original,
        normalized_query=normalized,
        has_temporal_intent=has_temporal,
    )
