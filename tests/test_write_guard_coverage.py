"""Static analysis: every file-write call in converter.py / bulk_worker.py
has a preceding `is_write_allowed()` guard or an explicit
`# write-guard:skip` opt-out.

This is the keep-the-fence-up test for the broad /host/rw Docker mount
introduced in v0.25.0. If you add a new write to either module without
gating it on `is_write_allowed()`, this test fails. If the write is
provably internal (e.g., to /tmp), add `# write-guard:skip <reason>`
on the same line or just above.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_WRITE_PATTERNS = [
    r"\bopen\([^)]*['\"][wax][b+]?['\"]",   # open(..., "w" / "a" / "x" / "wb" / "ab" / etc.)
    r"\.write_text\(",
    r"\.write_bytes\(",
    r"\bshutil\.(?:copy|copy2|copyfile|copytree|move)\(",
    r"\bos\.rename\(",
    r"\bos\.replace\(",
    r"\.mkdir\(",
]
_COMBINED = re.compile("|".join(_WRITE_PATTERNS))

# Look back ~700 chars (≈ 12-15 lines) for the guard or skip-comment
_LOOKBACK_CHARS = 700


@pytest.mark.parametrize("target", ["core/converter.py", "core/bulk_worker.py"])
def test_all_writes_guarded(target: str) -> None:
    src = (_PROJECT_ROOT / target).read_text()
    failures: list[str] = []
    for m in _COMBINED.finditer(src):
        # Get text from up to LOOKBACK_CHARS before the line containing the write
        line_start = src.rfind("\n", 0, m.start()) + 1
        window_start = max(0, line_start - _LOOKBACK_CHARS)
        preceding = src[window_start:m.start()]
        if "is_write_allowed(" in preceding or "# write-guard:skip" in preceding:
            continue
        # Identify the failing call so the diagnostic is useful
        snippet = src[m.start():m.end() + 40].split("\n", 1)[0]
        # Also find the line number for navigation
        line_no = src[:m.start()].count("\n") + 1
        failures.append(f"{target}:{line_no} — unguarded write: {snippet!r}")
    assert not failures, "Unguarded writes found:\n  " + "\n  ".join(failures)
