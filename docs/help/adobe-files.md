# Adobe Creative Files

MarkFlow indexes Adobe creative files so their content is searchable alongside
your converted documents. This is called **Level 2 indexing** -- the files are
cataloged and their text and metadata are extracted, but they are not converted
to Markdown the way a DOCX or PDF would be.

---

## Why Level 2?

Most Adobe formats use proprietary binary structures that cannot be reliably
converted to Markdown without the original application. Instead of attempting
a lossy conversion, MarkFlow extracts what it can -- text layers, embedded
text streams, and XMP/EXIF metadata -- and makes that content searchable.

This means you can find a PSD file by searching for the text on one of its
layers, or locate an InDesign file by its author or creation date, without
ever opening the original application.

---

## Supported Adobe Formats

| Extension | Application | What MarkFlow Extracts |
|-----------|-------------|----------------------|
| `.ai` | Adobe Illustrator | Text from the embedded PDF stream + XMP/EXIF metadata |
| `.psd` | Adobe Photoshop | Text layers (including nested groups) + XMP/EXIF metadata |
| `.indd` | Adobe InDesign | XMP/EXIF metadata only |
| `.aep` | Adobe After Effects | XMP/EXIF metadata only |
| `.prproj` | Adobe Premiere Pro | **Deep parse** -- structured Markdown with sequence list, every referenced clip path, bin tree, and parse warnings. See "Premiere Pro Projects (Deep Parse)" below. |
| `.xd` | Adobe XD | XMP/EXIF metadata only |

### Text Extraction Details

**Illustrator (.ai):** AI files contain an embedded PDF stream. MarkFlow opens
this stream with the same PDF library used for regular PDF conversion and
extracts all readable text. If the AI file was saved without PDF compatibility
enabled, the embedded stream may be empty and only metadata will be available.

**Photoshop (.psd):** MarkFlow walks every layer in the PSD file, including
layers nested inside groups. Layers of type "text" (also called type layers)
have their content extracted. Raster layers, adjustment layers, and smart
objects are skipped -- only actual editable text is captured.

> **Tip:** If your PSD files contain important information in rasterized text
> (text that was flattened into a pixel layer), MarkFlow will not find it.
> Keep text layers editable when possible.

### Metadata Extraction

For all six formats, MarkFlow runs **exiftool** to extract XMP and EXIF
metadata fields. Common fields include:

- Author / Creator
- Creation date and modification date
- Document title and description
- Software version used
- Color profile
- Page / artboard dimensions
- Layer count (PSD)
- Duration and frame rate (AEP)

Metadata fields longer than 2,000 characters are truncated. Binary fields
(thumbnails, embedded previews) are excluded.

> **Warning:** Exiftool has a 30-second timeout per file. Very large files
> (multi-gigabyte InDesign documents, for example) may hit this limit. When
> that happens, the metadata section will contain `"_error": "exiftool timeout"`
> but the file is still cataloged and any text layers already extracted are
> preserved.

---

## When Does Indexing Happen?

Adobe files are indexed during **bulk conversion jobs**. When the bulk scanner
walks a source directory and encounters a file with one of the six supported
extensions, it runs the Adobe indexer instead of the normal conversion pipeline.

Single-file uploads on the Convert page do not trigger Adobe indexing. If you
need to index individual Adobe files, include them in a source directory and
run a bulk job.

---

## Searching Adobe Files

Indexed Adobe files appear in MarkFlow's search results alongside converted
documents. The search system uses two separate indexes:

| Index | Contains | Fields Searched |
|-------|----------|----------------|
| **documents** | Converted Markdown files | title, content, source format, tags |
| **adobe-files** | Indexed Adobe files | text layers, metadata fields, file path, extension |

When you search on the [Search page](/search.html), results from both indexes
are returned and displayed together. Adobe file results are labeled with their
format badge (e.g., "PSD", "AI") so you can tell them apart from converted
documents.

### Filtering by Index

The Search page has an **Index** filter dropdown. Select "Adobe Files" to see
only Adobe results, or "Documents" to see only converted Markdown files.

### Searching from Claude (MCP)

If you have connected MarkFlow to Claude via the MCP integration, the
`search` tool queries both indexes by default. Claude can also use the
dedicated `search_adobe` tool to search only Adobe files.

---

## Where Are Adobe Files Stored?

Adobe files are **not copied** to the output repository. They stay in their
original location on the source share. MarkFlow only stores:

- A database record with the file path, size, extension, and indexing timestamp
- The extracted text layers (as a JSON array in the database)
- The extracted metadata (as a JSON object in the database)
- A corresponding entry in the Meilisearch full-text index

If the source file is moved or deleted, the lifecycle scanner will detect the
change and update the database record accordingly. See
[Settings Guide](/help.html#settings-guide) for lifecycle scanner configuration.

---

## Text Truncation

To keep the database and search index manageable, MarkFlow caps the total
extracted text at **500 KB per file**. If a PSD has dozens of text layers
that together exceed this limit, later layers are dropped. The most important
content (layers processed first) is preserved.

In practice, 500 KB of text is a very generous limit. Most creative files
contain far less editable text than that.

---

## Viewing Indexed Data

You can see what MarkFlow extracted from an Adobe file in several places:

1. **Search results** -- click an Adobe file result to see its metadata and
   text layers in the detail panel.
2. **History page** -- Adobe-indexed files appear in the conversion history
   with format type "adobe" and a link to view the extracted data.
3. **API** -- `GET /api/search?q=your+query&index=adobe-files` returns the
   raw indexed data including text layers and metadata.

---

## Premiere Pro Projects (Deep Parse)

As of v0.34.0, Premiere Pro project files (`.prproj`) get a structured
**deep parse** instead of the metadata-only treatment used by other Adobe
formats. Every Premiere project is searchable by the full path of every
clip it references, and operators can answer "which Premiere projects
use this video file?" without leaving MarkFlow.

### What gets extracted

Premiere project files are gzipped XML under the hood. MarkFlow streams
each project through a defensive XML parser and produces a Markdown
summary that contains:

- **Project metadata** -- name, Premiere version (when stamped), frame
  rate / resolution / color space (when present in the root settings),
  schema confidence (`high` / `medium` / `low`), and the count of XML
  elements processed.
- **Sequences** -- one row per timeline with name, duration, resolution,
  clip count, and marker count where the schema exposes them.
- **Media** -- every master clip path, grouped by media type (video,
  audio, image, graphic, unknown) and rendered as a search-friendly
  list. The clip's basename is shown next to the absolute path.
- **Bin tree** -- the project's folder organisation rendered as an
  ASCII tree.
- **Parse warnings** -- anything the parser couldn't make sense of
  (unknown root, malformed sequence node, etc.).

### Worked example

You import `C0042.MP4` into 5 different Premiere projects. After bulk
conversion runs, MarkFlow has indexed all 5 projects. Now:

1. Search for `C0042.MP4` on the Search page -> all 5 projects appear
   as results because the Markdown for each project lists the clip path.
2. Open the **preview page** for `C0042.MP4` -> the right sidebar shows
   a "Used in Premiere projects" card listing all 5 projects with
   click-through links.
3. Click any project -> opens its preview page with the full Markdown
   summary visible.

### When the parser falls back

Premiere has shipped multiple XML schema variants over its history.
Real-world projects can also be encrypted, truncated, or saved by
third-party tools that produce non-standard XML. MarkFlow handles each
case gracefully:

- **Unknown XML root element** -> `schema_confidence` is `low` and the
  parser still records whatever path-shaped strings it found.
- **Truncated or corrupt gzip** -> the handler falls back to
  AdobeHandler-style metadata-only output. The bulk job continues.
- **Encrypted project** -> detected at the gzip layer; same fallback
  with a `prproj.encrypted` log line.

The Markdown output always includes a `Schema confidence` row, so you
can immediately tell whether the deep parse succeeded or fell back.

### Cross-reference API

External programs (asset-management dashboards, IP2A, custom scripts)
can hit the cross-reference endpoints directly. See
[Administration -> Programmatic API access](/help.html#admin-tools)
or the [Developer Reference](/help.html#developer-reference) for full
curl / Python / JavaScript examples covering:

- `GET /api/prproj/references?path=<media_path>` -- reverse lookup
- `GET /api/prproj/{project_id}/media` -- forward lookup
- `GET /api/prproj/stats` -- aggregate counts

All three respect the standard JWT / `X-API-Key` auth.

### Limitations

- **Sequence-clip linkage is not yet recorded.** The Markdown lists
  every sequence and every media path, but does not yet pair them up
  ("clip X was used in sequence Y"). Reserved for a Phase 1.5 walk.
- **Title text is not extracted.** Premiere built-in title text overlays
  use a separate, denser schema. Out of scope for v0.34.0.
- **Marker comment text is not extracted.** Sequence-level markers
  often contain operator-typed comments that are highly searchable.
  Reserved for Phase 1.5.

If your team relies on any of those, drop a `.prproj` sample into
`tests/fixtures/prproj/` and open a follow-up.

---

## Rebuilding the Adobe Index

If you suspect the index is out of date (for example, after restoring files
from backup), you can rebuild it:

1. Go to the **Search** page.
2. Click **Rebuild Index** in the filter bar.
3. Wait for the rebuild to complete -- this re-indexes all documents and
   Adobe files from the database.

Alternatively, run a new bulk job over the same source directory. The scanner
uses modification timestamps to detect changes. Files that have not changed
since the last scan are skipped.

> **Tip:** Rebuilding the Meilisearch index does not re-run exiftool or
> re-extract text layers. It rebuilds the search index from data already
> stored in the database. To force a full re-extraction, delete the
> corresponding database records first (via the API or a fresh database).

---

## Troubleshooting

### "exiftool not found" in metadata

Exiftool must be installed in the Docker container. The standard MarkFlow
Dockerfile includes it. If you are running a custom image, make sure
`exiftool` is on the PATH.

### PSD text layers are empty

Check that your PSD file actually contains editable type layers (not
rasterized text). Open the file in Photoshop and look for the "T" icon
on layers in the Layers panel.

### AI file has no text

The AI file may have been saved without PDF compatibility. In Illustrator,
go to File > Save As and make sure "Create PDF Compatible File" is checked.
Without this, the embedded PDF stream that MarkFlow reads is empty.

---

## Related

- [Settings Guide](/help.html#settings-guide) -- configuring the lifecycle scanner and search
- [Unrecognized Files](/help.html#unrecognized-files) -- what happens to file types MarkFlow cannot index at all
- [LLM Providers](/help.html#llm-providers) -- AI-powered search enhancements
