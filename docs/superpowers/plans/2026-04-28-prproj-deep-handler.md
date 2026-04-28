# `.prproj` deep file handler

**Status:** Plan — not implemented.
**Author:** v0.33.3 follow-up planning, 2026-04-28.
**Triggers a release:** Yes — three release cuts (one per phase).
Suggested tags: `v0.34.0` / `v0.34.1` / `v0.34.2`.

---

## Background

Adobe Premiere Pro project files (`.prproj`) are currently routed to
`formats/adobe_handler.py:AdobeHandler` (its `EXTENSIONS` list includes
`"prproj"` alongside `psd`, `ai`, `indd`, etc). All they get is
exiftool-extracted metadata wrapped in a thin Markdown summary —
filename, file type, creator, modify date.

That's a missed opportunity. `.prproj` files are **gzipped XML** under
the hood, so they're machine-readable. A real Premiere project is
essentially a graph of:

- **Master clips** with paths to source media (video, audio, images,
  graphics) — often hundreds per project
- **Bins / folders** organising those clips into a tree
- **Sequences** (timelines) that arrange clips with in/out points,
  effects, transitions, audio levels, markers
- **Text/title elements** and project-level markers

The interesting MarkFlow-shaped feature here is **cross-reference**:
"which Premiere projects use this video file?" Operators editing in a
shared NAS environment routinely lose track of which project a given
clip belongs to. With a deep `.prproj` handler, MarkFlow becomes the
authority on that relationship — searchable like any other indexed
metadata.

The user's request, distilled:

> *"can we build a file handler for .prproj files? [...] yes, plan
> out a deep version"*

---

## Best practices baked in (mirror the v0.33.x rollout pattern)

| Practice | How |
|---|---|
| **Single source of truth** for parsed schema | One parser module (`formats/prproj/parser.py`) returns a dataclass tree. All callers (handler, indexer, API) consume that tree, not raw XML. |
| **Schema validation on parse** | Defensive walk: missing fields → `None` + warning log. Unrecognised root element → fall back to thin metadata extraction (matching today's behaviour). Bad data does NOT crash the bulk job. |
| **Defensive degradation** | Premiere CS6 / CC 2018 / CC 2024 / CC 2025 have schema differences. Parser tries known shapes in order; "unknown shape" still returns metadata + filename + element count. |
| **Streaming parse** | Premiere projects can be 100 MB+ uncompressed XML. Use `lxml.iterparse` with element clearing (avoid full-DOM blow-up). |
| **Operator transparency** | Markdown output explicitly labels what was parsed, with a "schema confidence" line so the operator can see whether the deep parser succeeded. |
| **Observable** | Structured log lines per parsed project: `prproj.parsed`, `prproj.schema_unknown`, `prproj.media_ref_recorded`. Searchable in Log Viewer with `?q=prproj`. |
| **Tested** | Multi-fixture test suite covering: minimal valid, large project, unknown schema, missing-media references, malformed/truncated gzip stream. |
| **No mutable global state** | Parser is pure-function; no module-level cache. Cross-reference cache (Phase 2) lives in DB, not memory. |
| **Backwards compatible** | New surface is purely additive — no existing endpoint changes, no breaking schema changes. The `bulk_files` row for a `.prproj` keeps its existing shape; new data goes in a new `prproj_media_refs` table. |

---

## Phase 0 — Discovery (mandatory before code)

**Cannot ship blind.** The Premiere XML schema isn't fully published;
real projects are the only source of truth. Operator must place at
least 3 sample `.prproj` files in `tests/fixtures/prproj/`:

1. A minimal project (1 sequence, ~5 clips) — sanity-test fixture
2. A medium project (10+ sequences, ~100 clips) — happy-path fixture
3. A large/old project (CS6 or earlier if available) — schema-variance
   fixture

For each, also note:
- Premiere version that authored it
- Approximate uncompressed XML size
- Whether the source media is reachable from the test environment (so
  cross-reference logic in Phase 2 can be exercised end-to-end)

This phase is **mostly operator action**. The plan body assumes
fixtures exist; if Phase 0 produces surprising findings (e.g. the
"XML" turns out to be a binary container in the latest Premiere
version), all three downstream phases get re-scoped before any code
lands.

---

## Phase 1 — Backend handler + Markdown extraction

**Suggested release: v0.34.0**
**Estimated: ~5 hours**

### Goals

- Replace the thin `AdobeHandler` pass for `.prproj` with a deep
  parser.
- Output a structured Markdown document operators can read +
  Meilisearch can index.
- Log a `prproj.parsed` event per project with summary counts.
- Unit tests using the Phase 0 fixtures.
- **No DB schema changes yet** — cross-reference table waits for
  Phase 2.

### Files to create

#### `formats/prproj/__init__.py`
Empty marker.

#### `formats/prproj/parser.py` (~350 LOC)

```python
"""Stream-parse a .prproj file into structured Python.

Public surface:
    parse_prproj(path: Path) -> PrprojDocument
    PrprojDocument is a frozen dataclass tree (see below).

Implementation:
    - Detect gzip magic bytes; gunzip-stream into the parser
    - lxml.iterparse with element clearing for memory safety
    - Walk known schema shapes (Premiere 2018+, fall-back for older)
    - Return a partial document with `parse_warnings` populated when
      shape is ambiguous; never raise on unknown elements
"""

@dataclass(frozen=True)
class MediaRef:
    """A single piece of source media referenced by the project."""
    path: str                      # absolute or project-relative
    name: str                      # display name in the bin
    media_type: str                # video | audio | image | graphic | unknown
    duration_ticks: int | None
    in_use_in_sequences: list[str] # sequence_ids that reference it

@dataclass(frozen=True)
class Sequence:
    seq_id: str
    name: str
    duration_ticks: int
    frame_rate: float
    width: int
    height: int
    audio_track_count: int
    video_track_count: int
    clip_count: int
    marker_count: int

@dataclass(frozen=True)
class Bin:
    bin_id: str
    name: str
    parent_bin_id: str | None
    item_count: int

@dataclass(frozen=True)
class PrprojDocument:
    schema_version: str            # the version string Premiere wrote
    project_name: str
    created_at: str | None         # ISO if parseable
    modified_at: str | None
    project_settings: dict         # frame rate, working color space, etc.
    media: list[MediaRef]
    sequences: list[Sequence]
    bins: list[Bin]
    parse_warnings: list[str]      # what the parser couldn't make sense of
    schema_confidence: str         # "high" | "medium" | "low" (heuristic)
```

#### `formats/prproj/handler.py` (~200 LOC)

```python
@register_handler
class PrprojHandler(FormatHandler):
    """Premiere Pro project file (.prproj).

    Renders a structured Markdown summary with:
    - Project metadata (name, version, frame rate, dimensions)
    - Bin tree (folder organisation)
    - Sequence list (each with duration + clip count + marker count)
    - Master media table (path + name + duration, grouped by type)
    - Parse warnings (operator-visible if anything was ambiguous)
    """
    EXTENSIONS = ["prproj"]
    PRIORITY = 10  # higher than AdobeHandler so this wins routing

    def ingest(self, file_path: Path) -> DocumentModel:
        # Try deep parse; fall back to AdobeHandler-style metadata-only
        try:
            doc = parse_prproj(file_path)
        except Exception as exc:
            log.warning("prproj.deep_parse_failed",
                        path=str(file_path), error=str(exc))
            return _fallback_to_metadata_only(file_path)
        return _render_markdown(doc, file_path)
```

#### `formats/__init__.py`

Side-effect import to register `PrprojHandler` at import time.
Mirror the existing pattern.

### Files to modify

#### `formats/adobe_handler.py`
Remove `"prproj"` from `EXTENSIONS` list. AdobeHandler now handles
`psd`, `ai`, `indd`, `aep`, `xd`, `ait`, `indt`, `psb` only.

#### `requirements.txt`
Add `lxml>=4.9` if not already present. (Likely already there for
other XML work; verify.)

#### `docs/key-files.md`
Add three rows (parser + handler + new directory).

### Markdown output shape

```markdown
# {project_name}

| Field          | Value                                |
|----------------|--------------------------------------|
| Project file   | example_project.prproj               |
| Premiere ver.  | 24.0.0                               |
| Frame rate     | 23.976 fps                           |
| Dimensions     | 1920×1080                            |
| Created        | 2026-03-12                           |
| Modified       | 2026-04-22                           |
| Schema confidence | high                              |

## Sequences (4)

| Name                | Duration | Clips | Markers |
|---------------------|----------|-------|---------|
| Main edit v3        | 04:12    | 47    | 12      |
| Promo cut 30s       | 00:30    |  9    |  3      |
| ...                 |          |       |         |

## Media (137 master clips)

### Video (89)

- `\\NAS\Footage\BCAMERA\C0042.MP4` — C0042.MP4 (00:14)
- `\\NAS\Footage\BCAMERA\C0043.MP4` — C0043.MP4 (00:23)
- ...

### Audio (28)
- ...

### Images (20)
- ...

## Bin tree

```
Root
  ├── Footage
  │   ├── BCAMERA
  │   └── ACAMERA
  ├── Audio
  │   └── Music
  └── Graphics
```

## Parse warnings (0)
```

This Markdown is what Meilisearch indexes — so a search for
`C0042.MP4` will surface every Premiere project that references it,
even before Phase 2's structured cross-reference table lands.

### Tests

#### `tests/test_prproj_handler.py` (~150 LOC)

- `test_parse_minimal_project` — fixture has 1 sequence + 5 clips;
  verify counts.
- `test_parse_medium_project` — fixture has 10 sequences + 100+
  clips; verify aggregate numbers + media-type breakdown.
- `test_parse_handles_unknown_schema` — feed a stub XML with an
  unrecognised root; verify handler returns metadata-only fallback
  + emits `prproj.schema_unknown`.
- `test_parse_handles_truncated_gzip` — feed a truncated stream;
  verify graceful failure (no crash, fallback emitted).
- `test_parse_records_warnings_in_document` — fixture with a
  malformed sequence node; verify `parse_warnings` populated and
  surfaced in Markdown output.
- `test_handler_priority_wins_over_adobe` — verify `.prproj` lands
  in `PrprojHandler`, not `AdobeHandler`.

### Acceptance (Phase 1)

- ✅ A `.prproj` file goes through bulk conversion and produces a
  Markdown file that includes the project name, sequence count,
  media list (with paths), and bin tree.
- ✅ Meilisearch picks the Markdown up; searching for a referenced
  clip filename returns the project.
- ✅ Existing `.psd` / `.ai` / `.indd` files still work (regression
  guard via the existing Adobe test suite).
- ✅ Unit tests pass with the Phase 0 fixtures.

---

## Phase 2 — Cross-reference table + API

**Suggested release: v0.34.1**
**Estimated: ~3 hours**

### Goals

- Persist the **media → projects** relationship in a queryable form.
- API endpoint: "for this video file path, which projects reference
  it?"
- API endpoint: "for this project, what media does it reference?"
  (already in the Markdown, but easier to consume programmatically)
- External-integrator friendly (same JWT/X-API-Key auth as the rest
  of the API).

### DB schema

#### New table `prproj_media_refs`

```sql
CREATE TABLE prproj_media_refs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,            -- FK to bulk_files.id
    project_path TEXT NOT NULL,            -- redundant for fast joins
    media_path   TEXT NOT NULL,            -- absolute path to media
    media_name   TEXT,                     -- display name in Premiere
    media_type   TEXT,                     -- video|audio|image|graphic|unknown
    duration_ticks INTEGER,                -- nullable
    in_use_in_sequences TEXT,              -- JSON list of sequence ids
    recorded_at  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES bulk_files(id) ON DELETE CASCADE
);

CREATE INDEX idx_prproj_refs_media_path ON prproj_media_refs(media_path);
CREATE INDEX idx_prproj_refs_project_id  ON prproj_media_refs(project_id);
```

#### Migration

`core/db/migrations.py` — new function `migrate_add_prproj_media_refs()`,
gated by the `schema_migrations` version table. Runs in lifespan
after `init_db`. Idempotent.

### Files to create

#### `core/db/prproj_refs.py` (~150 LOC)

```python
async def upsert_media_refs(project_id: str, project_path: str,
                            refs: list[MediaRef]) -> int:
    """Replace this project's refs atomically. Returns rows written."""

async def get_projects_referencing(media_path: str) -> list[dict]:
    """Reverse lookup: which projects use this media file?"""

async def get_media_for_project(project_id: str) -> list[dict]:
    """Forward lookup: what media does this project use?"""

async def delete_refs_for_project(project_id: str) -> int:
    """Called when a .prproj is removed from bulk_files."""
```

#### `api/routes/prproj.py` (~150 LOC)

```
GET  /api/prproj/references?path=<media_path>   -> list of projects
GET  /api/prproj/{project_id}/media             -> list of media refs
GET  /api/prproj/stats                          -> counts: n_projects,
                                                   n_media_refs,
                                                   top_5_most_referenced
```

Auth: OPERATOR+ for reads. Admin for the (future) cleanup endpoint.

### Files to modify

#### `formats/prproj/handler.py`
After successful parse, call `upsert_media_refs(...)`. Wrapped in
try/except so a DB blip doesn't fail the whole conversion.

#### `core/db/bulk.py`
On `bulk_files` row deletion, cascade to `prproj_media_refs` (via
the FK ON DELETE CASCADE — verify SQLite has FKs enabled in this
session; if not, add an explicit cleanup).

#### `main.py`
Register the new router.

### Tests

- `test_upsert_media_refs_replaces` — upserting twice for the same
  project replaces the previous set rather than duplicating.
- `test_get_projects_referencing` — 3 projects all reference one
  clip; reverse lookup returns all 3.
- `test_get_media_for_project` — deep-parsed project has 100 media
  refs; forward lookup returns all 100.
- `test_cascade_delete_on_project_removal` — removing a project's
  bulk_files row deletes its media_refs.
- `test_api_references_endpoint` — full request/response cycle via
  TestClient.

### Acceptance (Phase 2)

- ✅ DB migration runs cleanly on a v0.33.3 database (idempotent).
- ✅ A reanalysis of the Phase 0 fixtures populates
  `prproj_media_refs`.
- ✅ `GET /api/prproj/references?path=<known_clip>` returns at least
  one project.
- ✅ Removing a `.prproj` from `bulk_files` cascades to its refs.
- ✅ External integrator (curl with `X-API-Key`) can pull the same
  data.

---

## Phase 3 — UI surfaces

**Suggested release: v0.34.2**
**Estimated: ~3 hours**

### Goals

- Cross-reference card on the **preview page** for any video / audio /
  image file: "Used in N Premiere projects" → click to expand list.
- Search filter chip: "filter results by file type: prproj".
- Per-project detail link from search results / batch view: open the
  generated Markdown summary.
- Operator + developer documentation in the help wiki (mirroring the
  v0.33.2 cost-subsystem two-section style).

### Files to modify

#### `static/preview.html`
- Add a "Used in Premiere projects" card to the right column for
  files where the extension matches the video/audio/image lists.
- Card body fetches `/api/prproj/references?path=<this_file_path>`
  and renders a list of projects with click-through to each one's
  preview page.
- Empty state: "Not referenced by any indexed Premiere project."

#### `static/search.html`
- Add a `prproj` chip to the filetype filter row.
- Optional: a "show projects that reference this clip" affordance on
  search results for video/audio files (deep-link to preview page's
  cross-ref card).

#### `static/js/prproj-refs.js` (NEW, ~120 LOC)

Shared module exposing:

```javascript
window.PrprojRefs = {
  fetchProjectsReferencing(mediaPath) -> Promise<Array<{project_id, project_path, media_name}>>
  renderReferencesCard(container, refs)  // builds the preview-page card
}
```

All DOM via `createElement` + `textContent` (XSS-safe per project
gotcha, mirroring `cost-estimator.js`).

#### Help docs
- `docs/help/adobe-files.md` — extend with a "Premiere projects (deep
  parse)" section. Operator-friendly explanation of what gets
  extracted + worked example: "I imported `C0042.MP4` into 5 projects;
  search the clip filename and the preview page now shows all 5
  projects under 'Used in Premiere projects'."
- `docs/help/admin-tools.md` — extend the "Programmatic API access"
  section with `/api/prproj/*` endpoints, two-section operator +
  developer treatment with curl/Python/JS samples (matching v0.33.2
  pattern).

### Acceptance (Phase 3)

- ✅ Open the preview page on a `.MP4` referenced by an indexed
  `.prproj` → see the "Used in Premiere projects" card with at least
  one entry.
- ✅ Click the project link → preview page for the `.prproj` opens
  with its Markdown summary visible.
- ✅ Search for a clip filename + filter to `prproj` → only Premiere
  projects appear in results.
- ✅ Help docs include the worked example and full API integrator
  reference.

---

## Cross-phase concerns

### Edge cases to handle

| Edge case | Handling |
|---|---|
| Project references media at a path that no longer exists | Record the path anyway; downstream UI shows "(file not found)" badge. Useful for "what was this project supposed to use?" archeology. |
| Project references media at a different mount path than MarkFlow sees | Record the original path verbatim; Phase 2 API can optionally normalise via the existing storage_manager mounts (defer to Phase 3.x if desired). |
| Project exceeds 500 MB uncompressed XML | Streaming parser handles it; bulk job timeout (configurable per release) is the only practical cap. |
| Premiere version we've never seen before | Schema-confidence drops to `low`; `parse_warnings` lists what was skipped; metadata + filename + raw element count are still emitted. |
| Truncated / corrupt gzip | Caught at the gunzip layer; handler emits `prproj.deep_parse_failed` and falls back to AdobeHandler-style metadata-only. The bulk job continues. |
| Project is encrypted (rare but supported by Premiere) | Detected at gzip layer (header doesn't match); same fallback as above with a more specific log event `prproj.encrypted`. |
| Same media path appears in multiple bins / used multiple times in one project | Deduplicated to one row in `prproj_media_refs` per (project, media_path); `in_use_in_sequences` lists all the sequences. |

### Security

- Parser is a strict XML reader; no `eval`, no DTD resolution, no
  network IO. lxml iterparse with `resolve_entities=False`,
  `no_network=True`, `huge_tree=False`.
- No user-supplied input to the parser (it only reads from disk).
- Cross-reference paths are recorded as-is; the search-index path is
  what's queryable. No path-traversal surface — we never *open* the
  referenced media files; we only record their paths.
- API endpoints respect existing JWT / X-API-Key auth.

### Performance

- `parse_prproj` on a 100 MB uncompressed XML benchmarks at ~2-5
  seconds on this hardware (estimated; verify in Phase 0). Acceptable
  in the bulk worker context where conversions routinely run minutes.
- `prproj_media_refs` is indexed on both directions (`media_path` and
  `project_id`); queries sub-millisecond up to ~100 K rows.
- The reverse-lookup query in Phase 3 (one round-trip per preview
  page load on video/audio/image files) is small enough not to need
  caching. If page-render perf becomes an issue, the existing 30 s
  preview info cache can be extended.

### Backwards compatibility

- New `prproj_media_refs` table: pure additive.
- `.prproj` Markdown output shape changes (deeper) — counts as an
  improvement, not a breaking change. Existing search index entries
  for `.prproj` files get refreshed on the next bulk pass.
- AdobeHandler's `EXTENSIONS` list shrinks by 1 — operationally
  irrelevant since handler routing picks the new dedicated handler.
- No env-var or DB-pref changes. No new dependencies if `lxml` is
  already installed (very likely; verify).

### Rollback story

Each phase is independently rollback-able:

- **Phase 1**: revert `formats/prproj/`, restore `"prproj"` to
  `AdobeHandler.EXTENSIONS`. Existing `.prproj` files re-acquire
  thin metadata-only treatment on next bulk pass. No data lost.
- **Phase 2**: drop `prproj_media_refs` table + revert
  `core/db/prproj_refs.py` + `api/routes/prproj.py` + `main.py`
  router registration. Phase 1's Markdown output continues to work.
- **Phase 3**: revert UI files. Phase 1+2 unaffected.

### Logged events for the audit trail

| Event | When it fires |
|-------|---------------|
| `prproj.parsed` | Successful deep parse. Includes `schema_confidence`, sequence/media/bin counts. |
| `prproj.schema_unknown` | Parser fell back to metadata-only because shape was unrecognised. Includes the unknown root element name. |
| `prproj.deep_parse_failed` | Hard parse error (gzip corruption, lxml exception). Includes error class. |
| `prproj.encrypted` | Detected encrypted project. |
| `prproj.media_ref_recorded` | Phase 2 only. Per-project summary: `n_refs` written. |
| `prproj.cross_ref_lookup` | Phase 2 API call to `/references` endpoint. |

All searchable in Log Viewer with `?q=prproj`.

---

## Implementation order (within Phase 1, recommended)

1. **Phase 0 fixtures land in `tests/fixtures/prproj/`** (operator action). (~variable)
2. Implement `formats/prproj/parser.py` minimal happy-path: parse the
   minimal-project fixture, get sequence + media counts. Test passes. (~60 min)
3. Extend parser to walk bins recursively + capture project metadata.
   Test against the medium fixture. (~45 min)
4. Implement schema-fallback path: feed the unknown-schema fixture,
   verify graceful degradation. (~30 min)
5. Implement `formats/prproj/handler.py`: render Markdown output from
   the parsed document. Wire register_handler. (~45 min)
6. Remove `prproj` from `AdobeHandler.EXTENSIONS`. Verify routing
   priority via the new test. (~10 min)
7. End-to-end smoke: drop a `.prproj` into the bulk-source mount,
   trigger a scan + convert, verify the Markdown lands in the output
   tree. (~15 min)
8. Docs (CLAUDE.md, version-history.md, whats-new.md, adobe-files.md
   notes), version bump, commit, push, deploy, verify. (~45 min)

---

## Done criteria (overall, after all 3 phases)

- ✅ Premiere project files convert to a structured, searchable
  Markdown summary that lists every referenced media asset.
- ✅ Operators can answer "which Premiere projects reference this
  clip?" without leaving MarkFlow.
- ✅ External integrators (IP2A, asset-management dashboards) can
  query the relationship via documented JWT / X-API-Key API.
- ✅ The subsystem ships in 3 reviewable releases (v0.34.0 →
  v0.34.1 → v0.34.2) — operator can pause after any phase without
  breaking the others.
- ✅ Help docs include user-friendly worked examples + full
  API-integrator reference (matching the v0.33.2 cost-subsystem
  two-section pattern).
- ✅ All `.prproj` parse outcomes — success, fallback, encrypted,
  truncated — are traceable via the Log Viewer.

---

## Open questions / dependencies

1. **Phase 0 fixtures.** Operator must place 3 `.prproj` samples
   covering version variance. Without these, schema-confidence
   heuristics are guesses.
2. **lxml availability.** `requirements.txt` likely already has it;
   verify before Phase 1 starts. If not, add it (small, well-known
   dep — no concerns).
3. **Should Phase 1 also extract sequence-level marker text?**
   Markers contain operator-typed comments that are *highly* useful
   to search. Defer to Phase 1 if the medium-project fixture has
   markers visible in the XML; otherwise punt to Phase 1.5.
4. **Title clip text extraction.** Premiere has built-in titles
   (text overlays). Extracting their text would make the Markdown
   output richer + more searchable, but the schema is genuinely
   nasty. Defer to a Phase 4 if requested.
5. **Should we also handle `.prtl` (legacy title) and `.prfpset`
   (FX preset) files?** Out of scope; if requested, add as a Phase
   1.5 extension.
