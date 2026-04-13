"""
Occurrence-aware sidecar element lookup with fuzzy-match fallback.

Lookup cascade:
  1. Exact hash+occurrence: "{hash}:{n}" where n = nth time this hash seen
  2. Bare hash fallback:   "{hash}" (v1 sidecar backward compat)
  3. Fuzzy text match:      normalized Levenshtein ratio >= 0.90 against _text fields
"""

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from core.document_model import compute_content_hash

import structlog

log = structlog.get_logger(__name__)

_FUZZY_THRESHOLD = 0.90  # SequenceMatcher ratio; 0.90 ~ <=10% edit distance

# Regex to strip markdown inline markers (same logic as docx_handler._plain_text_hash)
_MD_BOLD_ITALIC = re.compile(r"\*{1,3}(.+?)\*{1,3}", re.DOTALL)
_MD_CODE = re.compile(r"`(.+?)`", re.DOTALL)


class OccurrenceTracker:
    """Counts how many times each content hash has been seen during a single
    export pass."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def next(self, content_hash: str) -> int:
        """Return the current occurrence index for *content_hash*, then increment."""
        n = self._counts[content_hash]
        self._counts[content_hash] += 1
        return n


def _strip_md_markers(text: str) -> str:
    """Strip inline markdown markers (**bold**, *italic*, `code`)."""
    plain = _MD_BOLD_ITALIC.sub(r"\1", str(text))
    plain = _MD_CODE.sub(r"\1", plain)
    return plain


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def resolve_sidecar_entry(
    elements_map: dict[str, Any],
    content_text: str,
    tracker: OccurrenceTracker,
) -> dict[str, Any] | None:
    """Look up the sidecar style entry for *content_text*.

    Args:
        elements_map: The "elements" dict from a loaded sidecar.
        content_text: The element's text content (may include markdown markers).
        tracker: Shared occurrence tracker for this export pass.

    Returns:
        The matching style entry dict, or None if no match found.
    """
    # Hash the plain text (strip markdown markers first)
    plain = _strip_md_markers(content_text)
    h = compute_content_hash(plain)
    n = tracker.next(h)

    # 1. Exact v2 key: "{hash}:{n}"
    v2_key = f"{h}:{n}"
    entry = elements_map.get(v2_key)
    if entry is not None:
        return entry

    # 1b. Overflow: occurrence exceeds stored entries -> try last stored
    if n > 0:
        for fallback_n in range(n - 1, -1, -1):
            entry = elements_map.get(f"{h}:{fallback_n}")
            if entry is not None:
                return entry

    # 2. Bare hash fallback (v1 compat)
    entry = elements_map.get(h)
    if entry is not None:
        return entry

    # 3. Also try hashing with markers intact
    h_raw = compute_content_hash(content_text)
    if h_raw != h:
        for key_candidate in [f"{h_raw}:{n}", h_raw]:
            entry = elements_map.get(key_candidate)
            if entry is not None:
                return entry

    # 4. Fuzzy match -- compare normalized text against all _text fields
    normalized = _normalize(plain)
    if not normalized:
        return None

    best_entry: dict[str, Any] | None = None
    best_ratio = _FUZZY_THRESHOLD

    for _key, candidate in elements_map.items():
        if not isinstance(candidate, dict):
            continue
        stored_text = candidate.get("_text")
        if not stored_text:
            continue
        ratio = SequenceMatcher(None, normalized, str(stored_text)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_entry = candidate

    if best_entry is not None:
        log.debug(
            "sidecar.fuzzy_match",
            content=content_text[:40],
            ratio=round(best_ratio, 3),
        )

    return best_entry
