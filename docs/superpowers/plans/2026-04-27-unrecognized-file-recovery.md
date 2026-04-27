# Unrecognized-File Recovery: `.tmk` Handler + `.download` Format-Sniff Pipeline

**Status:** Plan — not implemented.
**Author:** v0.32.0 follow-up planning, 2026-04-27.
**Triggers a release:** Yes — implementation produces a versioned cut (likely `v0.32.x` or `v0.33.0`).

---

## Background

While triaging the Pipeline Files **Unrecognized** bucket on the
production instance the operator surfaced two distinct problems
that the current MarkFlow pipeline fails on:

1. **`.tmk`** (5+ files observed, 48–303 bytes each, sitting next
   to `.mp3` recordings in `/mnt/source/11Audio Files to
   Transcribe/...`). MarkFlow has no handler registered for the
   extension, so they always land in `unrecognized`. They are
   tiny so they're not pre-existing audio; they're either a
   sidecar / marker file or a corrupt download.
2. **`.download`** (~30+ files observed, all under
   `.../IBEW White Shirts Receipt_files/`). A spot-check on five
   samples confirms they are **JavaScript files** (`jQuery(function(t){…}`,
   `wc_cart_fragments_params`, `wc_checkout_params`) that a
   browser saved with its "Save Page As → Complete" mode. The
   browser correctly downloaded them but appended its
   `.download` suffix to the filename. The real format is
   `.js`. MarkFlow already has a JavaScript text handler — it
   just can't see past the bogus extension.

The user's request:

> create a plan for a file handler for `*.tmk` files. also to have
> markflow try to recognize what the `.download` file actually is…
> maybe have markflow attempt to view the file via all of the
> handlers. if successful make a note in the search results and
> file details page.

There are two distinct pieces here:
- **Specific:** add a `.tmk` handler so those files stop showing
  as unrecognized.
- **General:** add a format-sniffing fallback so any unrecognized
  file gets one last attempt at classification by trying the
  registered handlers in priority order. When sniffing succeeds,
  surface the discovered real type in the file detail page and
  the search index.

The general fix subsumes the specific one (`.tmk` would be
classified by sniffing if it turns out to be e.g. a PDF
sidecar or plain-text manifest), but the specific fix is
worth shipping in tandem so the common case (audio sidecar
metadata) gets a polished display rather than just "we
sniffed it as text."

---

## Goals

1. **No more unrecognized `.tmk` files** for the audio-transcribe
   workflow. The 5+ instances on the production instance get
   classified, indexed, and previewable.
2. **Recover misnamed downloads** automatically. The `.download`
   files (and other browser-suffix variants like `.crdownload`,
   `.part`, `.partial`) get classified by their real format and
   processed by the correct handler.
3. **Surface the recovery** so operators understand what
   happened. Search results show "(real type: JavaScript)" and
   the file-detail page shows a banner.
4. **Don't regress**: existing handlers run first; sniffing only
   fires on files that would otherwise be `unrecognized`.

---

## Phase 0 — Discovery (must run before Phase 1)

The `.tmk` files on the production instance have all transitioned
to `lifecycle_status='in_trash'` (their bytes vanished from disk
between scans). To design the handler we need fresh samples.

**Action:**
1. Operator places one fresh `.tmk` file in
   `/mnt/source/!discovery/sample.tmk` (or wherever is convenient
   under the source tree).
2. Run a one-shot diagnostic command in the container:
   ```bash
   docker exec doc-conversion-2026-markflow-1 python3 -c "
   from pathlib import Path
   p = Path('/mnt/source/!discovery/sample.tmk')
   data = p.read_bytes()
   print(f'size={len(data)} bytes')
   print(f'magic_bytes={data[:16].hex()}')
   print(f'is_text={all(32 <= b < 127 or b in (9,10,13) for b in data[:200])}')
   print(f'first_200={data[:200]!r}')
   "
   ```
3. Paste the output into this document under "Discovery
   results" (below). The handler design depends on what shows
   up.

### Discovery results (filled in during Phase 0 — currently empty)

```
size: TBD
magic_bytes: TBD
is_text: TBD
first_200: TBD
```

Likely candidates given the audio-transcribe context:
- **Plain-text marker** (e.g., per-file timestamp + speaker
  count) → handle as a text sidecar; render as plain text.
- **Toolkit Mass Mailer / Mailmerge** → unlikely given the audio
  folder; skip.
- **Audio editor metadata (Pro Tools / Audacity)** → small
  binary blob with strings. Extract any embedded text.
- **Empty / corrupt file** → the smallest sample is 48 bytes;
  handle gracefully.

---

## Phase 1 — `.tmk` handler

Once Phase 0 reveals the format, register a handler in
`formats/`. Three likely paths:

### 1a. Plain-text marker (most likely)

If the file is UTF-8 text with audio metadata (timestamps,
speaker labels, etc.):
- Add `.tmk` to `formats/txt_handler.py`'s extension list
  alongside `.txt` / `.log` / `.md`.
- No new handler module needed.
- File renders inline on the preview page via the existing
  `text` viewer kind.
- One-line PR.

### 1b. Sidecar of an `.mp3` recording

If the file pairs with a same-stem `.mp3` (e.g.,
`260324_1114.tmk` next to `260324_1114.mp3`):
- Add a `.tmk` extension entry that **routes through the audio
  handler** so the conversion output is the same Markdown the
  Whisper transcription produces, with the `.tmk` content
  appended as a "Source notes" section.
- New module: `formats/tmk_handler.py` (~80 LOC). Uses
  `core.audio_handler` as its inner engine; adds a small
  parser for the `.tmk` text/binary content.
- Updates `core/handlers.py` registry to register `.tmk`.

### 1c. Standalone unknown format

If the format doesn't match any known shape:
- Register a minimal `.tmk` handler that extracts whatever
  text is recoverable (UTF-8 decode with `errors='replace'`)
  and emits a Markdown stub:
  ```markdown
  # 260324_1114.tmk

  *Source format: TMK (303 bytes)*

  ## Recovered text

  <whatever was decodable>
  ```
- Operator can iterate from there if more structure is
  needed.

### Files (Phase 1, all paths)

- `formats/tmk_handler.py` (new — only if 1b or 1c)
- `formats/txt_handler.py` (extension list update — 1a)
- `core/handlers.py` (registry — 1b/1c)
- `tests/test_tmk_handler.py` (basic round-trip)
- `docs/help/unrecognized-files.md` (mention `.tmk` in the
  supported list)

---

## Phase 2 — Format-sniff fallback for unrecognized files

This is the meatier chunk. Goal: when a file's extension has no
registered handler (or the registered handler fails on the file),
MarkFlow tries each handler in priority order and uses the first
one that succeeds. If sniffing succeeds, the file is processed
by the matched handler and a note is emitted that explains what
happened.

### Where it fires

The current pipeline classifies files by extension in
`core/mime_classifier.py` and dispatches to handlers via the
registry in `core/handlers.py`. After:
- the registry returns "no handler for extension X", OR
- the matched handler raises a "format mismatch" exception
  (we'll define this contract below)

…we hit a new function `try_format_sniff(path)` that:

1. **Reads the first 4 KB** of the file (cheap probe).
2. **Magic-byte test** against a curated list:
   ```python
   MAGIC_BYTES = {
       b'%PDF': 'pdf',
       b'PK\x03\x04': 'zip',          # also docx/xlsx/pptx/odt/epub
       b'\xff\xd8\xff': 'jpg',
       b'\x89PNG\r\n\x1a\n': 'png',
       b'GIF8': 'gif',
       b'BM': 'bmp',
       b'RIFF': 'wav-or-webp',         # disambiguate by bytes 8-11
       b'ID3': 'mp3',
       b'\xff\xfb': 'mp3',
       b'OggS': 'ogg',
       b'fLaC': 'flac',
       b'\x1f\x8b': 'gz',
       b'7z\xbc\xaf\x27\x1c': '7z',
       b'Rar!': 'rar',
       b'<!DOCTYPE': 'html',
       b'<?xml': 'xml',
       b'<svg': 'svg',
       b'{': 'json',                   # heuristic; only if last char also `}`
   }
   ```
3. **Text-content heuristics** when magic bytes don't match:
   - All bytes printable ASCII / UTF-8 → likely text.
   - Looks like JS/CSS/Python/etc. → fingerprint via
     keywords (`function(`, `import `, `def `,
     `package main`, etc.).
4. **Final attempt — hand off to `python-magic`** (already in
   the image) for any file that survives the first three
   passes.

The output of sniffing is a `SniffResult`:

```python
@dataclass
class SniffResult:
    matched_format: str | None      # "javascript", "pdf", "json", ...
    matched_handler: str | None     # handler module to use
    confidence: float               # 0.0–1.0
    method: str                     # "magic", "text-heuristic", "python-magic"
    matched_bytes: int              # how many bytes contributed
```

### Calling the matched handler

If `SniffResult.matched_handler` is set, the dispatcher loads
that handler and runs it on the file. The handler must be
willing to process a file with an unexpected extension — every
existing handler already accepts a `Path` argument and reads
based on content, so this should be a near-no-op on the handler
side. The dispatcher records the discovered format on the
`bulk_files` row:

```sql
ALTER TABLE bulk_files ADD COLUMN sniffed_format TEXT;
ALTER TABLE bulk_files ADD COLUMN sniffed_method TEXT;
ALTER TABLE bulk_files ADD COLUMN sniffed_confidence REAL;
```

(Migration `core/db/migrations.py:add_sniff_columns_v0_32_x`.)

### Surfacing the recovery in the UI

Three places mention the discovered format:

1. **Search results** — when `bulk_files.sniffed_format` is
   set, the result card adds a small badge:
   `[ext: .download → js (sniffed)]`. Implementation: add
   field to the Meili index doc, render in `search.html`.
2. **File detail page** (`/static/preview.html`) — the Conversion
   sidebar card gains a "Sniffed format" row:
   `Sniffed format: javascript (text-heuristic, 92% confidence)`.
3. **Pipeline Files** — the Unrecognized chip count drops
   accordingly. Files that sniffed successfully move from
   `unrecognized` to `converted` (or `pending` until the next
   pipeline tick).

### Performance / safety bounds

- **Sniff only on `unrecognized`**, never on a file that has a
  registered handler (avoids regressions).
- **4 KB probe cap** — never read more than that for sniffing.
- **Skip if `file_size_bytes` < 16** — meaningless to sniff.
- **Skip if `file_size_bytes` > 500 MB** — defensive bound.
- **Per-job sniffing budget** — cap at 1000 sniffs per bulk
  job to bound the slowest case (huge `_files/` directory of
  partial downloads).

### Files (Phase 2)

- `core/format_sniffer.py` (new, ~150 LOC) — `SniffResult`
  dataclass + `try_format_sniff()` + magic-byte table.
- `core/handlers.py` — call `try_format_sniff()` in the
  unrecognized fallback path.
- `core/db/migrations.py` — add `sniffed_format`,
  `sniffed_method`, `sniffed_confidence` columns.
- `core/search_indexer.py` — pass sniffed_format into the Meili
  document.
- `static/search.html` — render the badge on result cards.
- `static/preview.html` — render the row in the Conversion
  sidebar card.
- `tests/test_format_sniffer.py` — round-trip tests for each
  magic-byte / heuristic case.

---

## Phase 3 — Browser-download-suffix shim (cheap special case)

Even with the general sniff fallback, the `.download` /
`.crdownload` / `.part` / `.partial` cases are SO common (every
modern browser leaves them around) that handling them with a
tiny shim is worth the small extra code:

1. In `core/mime_classifier.py`, when an extension matches the
   set `{'.download', '.crdownload', '.part', '.partial'}`,
   strip the trailing suffix and re-classify on the
   "real" extension.
2. If the stripped name has a recognized extension, route to
   that handler.
3. Otherwise fall through to the Phase 2 sniffer.

Example:
- `add-to-cart.min.js.download` → strip `.download` →
  `.js` → JS text handler.
- `report.pdf.crdownload` → strip → `.pdf` → PDF handler.
- `mystery.tmk.part` → strip → `.tmk` → uses Phase 1 handler.

This is a pre-Phase-2 optimization — handles the 95% case
without paying the cost of opening the file.

### Files (Phase 3)

- `core/mime_classifier.py` — extension-suffix stripper.
- `tests/test_mime_classifier.py` — test cases for each suffix.

---

## Implementation order (recommended)

1. **Phase 0** — discovery (operator + me, 5 minutes).
2. **Phase 3** — browser-suffix shim. Smallest, highest-impact
   for the user's actual data. Recovers all 30+ `.download` files
   in one go.
3. **Phase 1** — `.tmk` handler. Variant 1a, 1b, or 1c per
   discovery results.
4. **Phase 2** — general format sniffer. Bigger surface, more
   testing, longer iteration.

If schedule pressure forces a cut, ship 0+3+1 and defer 2.
That gets the operator's specific files recovered and the
generic sniffer can land in a follow-up release.

---

## Testing strategy

### Phase 1 (`.tmk`)
- Unit test: `formats/tmk_handler` round-trips a sample byte
  sequence to Markdown and back (or to-md only if 1c).
- Integration test: a fixture `.tmk` file plus a sample `.mp3`
  routes through the bulk pipeline and lands in `converted`
  with the expected output Markdown.

### Phase 2 (sniffer)
- Unit test per magic-byte case: PDF, ZIP, JPG, PNG, MP3,
  HTML, JSON, etc. each correctly classified with high
  confidence.
- Negative test: random bytes → `matched_format=None`.
- Edge cases: file < 16 bytes, file > 500 MB, file with mixed
  text + binary, file with a magic-byte match in the middle
  (should NOT match).
- Integration test: a `.download` file containing JS routes
  through sniff → JS handler → indexed Markdown excerpt.

### Phase 3 (suffix-strip shim)
- Unit test: each of `.download` / `.crdownload` / `.part` /
  `.partial` strips correctly.
- Integration test: `script.js.download` → JS handler → output
  Markdown.

---

## Risks & open questions

- **`.tmk` may turn out to be proprietary binary** with no
  recovery path. In that case the handler emits a "format
  unsupported" stub but at least we stop showing it as
  unrecognized. Phase 1c covers this.
- **Sniffing on huge files** — the 500 MB cap is defensive but
  could be lowered if real-world bulk jobs hit it. Watchable
  via the per-job sniffing budget metric.
- **Confidence threshold** — what minimum confidence triggers
  handler dispatch vs. labeling as unrecognized-with-sniff-hint?
  Suggested default: 0.5. Worth revisiting after seeing
  production sniff distributions.
- **`.html` saved-as-page directories** (`*_files/` siblings
  to a `.html` file) — these contain hundreds of tiny CSS /
  JS / image / JSON files that all sniff successfully but
  probably should be processed *as a unit* with the parent
  HTML. Out of scope for this plan; flagged as a follow-up if
  the volume becomes visible.
- **Meili re-index** — adding `sniffed_format` to the index
  doc means a re-index on deploy. Cost: ~10 min on the current
  size of the corpus.

---

## Done criteria

Phase 1: zero `.tmk` rows in the Unrecognized bucket on the
production instance after the next bulk scan. The 5+
representative files convert to Markdown (or skip with a
clear reason).

Phase 2 + 3: zero `.download` / `.crdownload` / `.part` /
`.partial` rows in Unrecognized after the next scan. Search
result cards show the discovered format. The Unrecognized
chip count on Pipeline Files drops by the count of recovered
files.

Both: a v0.32.x release entry in `docs/version-history.md`
and `CLAUDE.md` describing the changes; help article
`docs/help/unrecognized-files.md` updated to mention the
sniffer + suffix-strip + `.tmk` support.
