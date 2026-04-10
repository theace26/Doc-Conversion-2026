# Search

MarkFlow indexes the content of every converted document so you can
find it later — across Word, PDF, PowerPoint, Excel, CSV, Adobe
creative files, databases, video transcripts, and more. This article
covers the three layers of search MarkFlow uses (keyword, vector, and
AI Assist), how to write effective queries, and worked examples for
each.

## The Three Layers of MarkFlow Search

MarkFlow combines three searches in one search bar. You do not pick
between them — they run together automatically.

| Layer | What it does | When it wins |
|-------|--------------|--------------|
| **Keyword** (Meilisearch) | Finds documents by literal words and phrases, with typo tolerance | Filenames, proper nouns, exact quotes, codes, part numbers |
| **Vector / Semantic** (Qdrant) | Finds documents by *meaning*, even if they use different words than your query | Concepts, natural-language questions, "documents about X" |
| **AI Assist** (Claude) | Reads the top results and synthesizes a direct answer with citations | When you want an *answer*, not just a list |

Behind the scenes, the keyword and vector results are merged with
**Reciprocal Rank Fusion** so documents strong in either layer float
to the top. If vector search is offline, the bar silently falls back
to keyword-only — you will not see an error.

---

## Basic Search

1. Click the search bar at the top of the Search page (it is focused
   automatically when you land on the page).
2. Type one or more keywords.
3. Press Enter or wait ~200 ms — results appear below the bar.

Autocomplete suggestions appear as you type, sourced from real
document titles in your index. Use arrow keys to move through
suggestions, Enter to select.

> **Tip:** Click **Browse All** next to the search button to see
> every indexed document sorted by most recently converted. Useful
> when you just want to poke around.

### Keyboard shortcuts on the Search page

A handful of single-keystroke shortcuts speed up common tasks:

| Key | What it does |
|-----|--------------|
| `/` | Jump to the search box from anywhere on the page |
| `Alt + Shift + A` | Toggle **AI Assist** on/off |
| `Alt + A` | Select every result on the current page |
| `Alt + C` | Clear the batch selection |
| `Alt + Shift + D` | Download the current batch as a ZIP |
| `Alt + B` | Trigger **Browse All** |
| `Alt + R` | Re-run the current search |
| `Esc` | Close the preview popup / AI drawer / flag modal (in that order), then clear selection, then blur the search box |
| `Alt + Click` a result | Download the original source file directly, skipping the viewer |
| `Shift + Click` a checkbox | Range-select every row between the last click and this one |

For the complete list including Esc priority order and other pages,
see [Keyboard Shortcuts](/help#keyboard-shortcuts).

---

## Keyword Search — Syntax Cheatsheet

Keyword search uses Meilisearch under the hood. It is typo-tolerant,
case-insensitive, and supports prefix matching. Here are the operators
you can use **inside the search bar**:

| Syntax | Example | What it does |
|--------|---------|--------------|
| Single word | `budget` | Finds documents with "budget" anywhere; prefix-matches "budgetary", "budgeted", etc. |
| Multiple words | `Q3 revenue forecast` | Finds documents that contain *all three* words, ranking ones where they appear near each other higher |
| **Exact phrase** | `"quarterly revenue"` | Only matches the phrase exactly — "quarterly" followed by "revenue" |
| **Negative term** | `contract -draft` | Matches "contract" but excludes documents containing "draft" |
| Prefix match | `fin` | Matches "finance", "financial", "financing" — you do not need a wildcard |
| Typo tolerance | `finacial` | Still matches "financial" (Meilisearch auto-corrects short typos) |

### What keyword search does **not** support

MarkFlow does **not** support traditional Boolean operators like
`AND`, `OR`, or `NOT` as typed words — Meilisearch ignores them.
Instead:

- To require **both** of two terms: just type both words. All terms
  are treated as a soft "must-match" in ranking. `budget forecast`
  ranks documents with both words higher than documents with only
  one.
- To exclude a term: use the minus sign, e.g. `budget -draft`. There
  is no `NOT` keyword.
- To search for an exact phrase: wrap it in double quotes, e.g.
  `"final approved"`.
- To **filter** results (instead of changing the query), use the
  **format chips** or the **sort dropdown** above the results list.

### Keyword Search Examples

```
"safety policy"                ← exact-phrase search
wage sheet -draft              ← documents about wage sheets, excluding drafts
PENINSULA SMALL WORKS          ← case-insensitive; matches PENINSULA_SMALL_WORKS.pdf
IBEW Local 46                  ← word splitter also handles IBEWLocal46 filenames
q3 2026 forecast               ← multi-token, ranked by proximity
```

> **Tip:** Filenames are normalized at index time — underscores,
> dashes, dots, and camelCase boundaries are split into separate
> tokens. That is why `IBEW Local 46` matches `IBEWLocal46.pdf` and
> `wage sheet` matches `wage.sheet.pdf`.

---

## Vector / Semantic Search

Vector search finds documents by **meaning**, not by literal words.
This is automatic — there is no toggle. Every query runs through both
keyword and vector search in parallel, then the results are merged.

### When vector search helps

- When you know the **concept** but not the exact wording used in
  the document.
- When asking **natural-language questions** — the question prefix
  is automatically stripped (`what is`, `where are`, `tell me
  about`, etc.).
- When you want to find "documents about" a topic — rephrasings,
  paraphrases, and synonyms all surface.
- When words in your query have **temporal intent** ("latest",
  "recent", "current", "new"), MarkFlow detects this and boosts
  recent documents in the ranking.

### Vector Search Examples

```
budget overrun
  → finds documents that say "cost exceeded plan",
    "went over estimate", or "project ran over budget"

how do I request PTO?
  → normalized to "request PTO" — finds the PTO request form,
    employee handbook PTO section, HR policies

latest safety bulletin
  → "latest" boosts recent docs; finds the most recent safety
    communications even if they don't contain the word "bulletin"

what is the procedure for onboarding a new electrician?
  → question prefix stripped; semantic match against training
    docs, new-hire checklists, apprentice materials
```

> **Tip:** If a purely semantic query gives vague results, fall back
> to keyword search with quotes: `"new hire checklist"`. Exact
> phrases always beat paraphrase matching when you know the phrase.

### When vector search is less helpful

- Looking up a **specific filename** or exact quote → use quotes
  instead.
- Searching for **codes, part numbers, or identifiers** like
  `SP-4421-B` → keyword is better.
- When your repository has fewer than a few hundred documents —
  there is not enough corpus for semantic matching to find useful
  paraphrases. Keyword will dominate anyway.

---

## AI Assist — Ask Questions, Get Answers

AI Assist reads the top 8 search results and streams a direct,
grounded answer from Claude with inline citations.

### Turning It On

Click the **AI Assist** button next to the search bar (the sparkle
icon). The button toggles on/off and the state is remembered between
sessions. When on:

1. Run any search as normal.
2. A side drawer opens on the right.
3. Claude streams an answer, word by word, as it reads the top results.
4. Each citation (`[1]`, `[2]`, etc.) is a link — click to jump to
   the source document.
5. At the end, the drawer shows the list of source documents Claude
   used.

### Requirements

AI Assist currently requires an **Anthropic** provider:

1. Go to **Settings → Providers**
2. Add (or select) an Anthropic provider with a valid API key
3. Tick the **Use for AI Assist** checkbox on that provider
4. Save

If you have an active OpenAI / Gemini / Ollama provider but no
Anthropic provider opted in, the AI Assist drawer will show a clear
error explaining how to opt in an Anthropic provider.

### What to Ask

AI Assist is not just a search — it is a *question-answering*
interface. Instead of thinking in keywords, think in questions.

### AI Assist Examples

**Fact lookup:**
```
What is the current vacation accrual rate for apprentices?
```
→ Claude reads the top HR / onboarding documents and returns a
direct answer citing `[1] Apprentice Handbook`, `[2] Benefits
Overview`.

**Cross-document synthesis:**
```
Summarize the main safety requirements for working at height
```
→ Claude pulls together bullet points from multiple safety
bulletins, OSHA guides, and internal procedures, citing each
source.

**Comparisons:**
```
What changed between the 2024 and 2026 wage agreements?
```
→ Claude identifies the relevant documents and calls out
differences, citing each version.

**Decision support:**
```
Which documents cover drug testing policy for journeymen?
```
→ Claude lists the relevant documents with a one-line summary
of what each covers.

**Timeline questions:**
```
When was the last time we updated the grievance procedure?
```
→ The word "last" triggers temporal boosting; Claude finds the
most recent revision and cites it.

> **Tip:** AI Assist is grounded in your documents only — it will
> never make up information. If the top 8 results do not contain an
> answer, Claude will say so explicitly rather than guess. If you
> suspect the answer is in your repository but AI Assist cannot find
> it, **turn AI Assist off** and use keyword search to locate the
> document directly, then turn AI Assist back on.

### Document Expand

For a deeper dive into a single document, click **Expand** on any
search result (or in the AI Assist sources list). Claude re-reads
the full document (up to ~12,000 characters) and provides a focused
analysis in the context of your original query.

Useful for:

- Getting the "executive summary" of a long document without
  opening it
- Extracting key dates, decisions, or entities from a single contract
- Understanding *how* a document answers your original question

### Token Usage

AI Assist uses tokens on your Anthropic account. Every search +
assist runs ~1.5k–4k input tokens and up to ~700 output tokens.
Document Expand uses more (up to ~900 output tokens and much more
input). You can monitor usage on the Resources page.

---

## Filtering, Sorting, and Browsing

Above the results list you will find:

### Format chips

Click format badges (DOCX, PDF, PPTX, XLSX, CSV, etc.) to filter
results. Clicking a second time deselects. With no chips selected,
all formats are shown. The chip labels show live facet counts —
you know how many results exist for each format before filtering.

### Sort dropdown

| Option | What it sorts by |
|--------|------------------|
| **Relevance** | Default — the hybrid keyword+vector ranking |
| **Date (newest)** | Most recently converted first |
| **File size** | Largest first |
| **Format** | Grouped by file type |

If your query contains temporal words ("latest", "recent"), sort
automatically falls back to **Date** regardless of the dropdown,
since that is almost certainly what you meant.

### Per-page buttons

Choose 10, 30, 50, or 100 results per page. The default is 10.

### Browse All

With no query at all, click **Browse All** to see every indexed
document sorted by date. Useful for poking around a new repository.

---

## Batch Download

After searching, select multiple result checkboxes and click
**Download ZIP** in the toolbar that appears. MarkFlow builds a ZIP
of all selected source files (not the converted Markdown) and
streams it to your browser. Up to 500 files per ZIP.

Flagged files are silently excluded for non-admins — the batch
download response includes an `X-Skipped-Flagged` header with the
count.

---

## Hover Preview

Hover over any search result for ~400 ms to see a preview popup:

| File type | Preview content |
|-----------|----------------|
| PDF, images, text, HTML, CSV | Original source file rendered inline |
| Word, PowerPoint, Excel, databases, Adobe | First portion of the converted Markdown text |
| Files with no preview | "Cannot render preview" message |

The popup is **interactive** — you can scroll its content and click
the **Open** link inside it. If you move your mouse onto the popup,
it stays. After 2 seconds of inactivity on the popup, it slides
offscreen to get out of your way; move back into it to bring it
back.

Configure hover delay, popup size, and enable/disable from
**Settings → Search Preview**.

---

## Three Search Indexes, One Search Bar

MarkFlow maintains three separate Meilisearch indexes. A single
query hits all three in parallel and merges the results:

| Index | What it contains |
|-------|------------------|
| **Documents** | Every converted file (Word, PDF, PPTX, XLSX, CSV, RTF, ODT, HTML, EPUB, databases, etc.) |
| **Adobe Files** | Metadata + embedded text layers from `.ai`, `.psd`, `.indd`, `.aep`, `.prproj`, `.xd` |
| **Transcripts** | Full transcripts of audio and video files (with timestamps) |

Every result is tagged with its source index in the UI so you can
tell at a glance where each match came from.

---

## What Is Searchable

| Content | Source |
|---------|--------|
| Document body text | Paragraphs, headings, lists, tables, footnotes |
| Table cells | Excel sheets, Word tables, CSV rows |
| Speaker notes | PowerPoint |
| Captions & transcripts | Audio/video files — full text with timestamps |
| Database schema & samples | Table names, column names, first N sample rows |
| Adobe file metadata | Title, author, keywords, embedded text layers |
| Image descriptions | AI-generated frame descriptions from video keyframes |
| OCR text | Scanned PDFs and image files — including LLM handwriting transcription |
| Filenames (normalized) | Split on underscores, dashes, dots, and camelCase |
| Source file paths | Where the file lives in the source directory |

---

## Rebuilding the Search Index

If the index ever gets out of sync (after a restore or migration),
an administrator can rebuild it from the Bulk page **Pipeline
Controls → Rebuild Search Index** button.

Rebuilding walks every converted document in the database and
re-sends it to Meilisearch. Depending on repo size this takes
seconds to several minutes. A live progress indicator shows
"Rebuilding (X docs)..." until all sub-indexes finish.

> **Warning:** During a rebuild, results may be incomplete until
> the process finishes. The search page still works — it just may
> not show every result until rebuilding is done.

---

## Search and Deleted Files

Deleted or trashed files may appear briefly in search until the
index catches up. Lifecycle-affected results show a badge ("marked
for deletion", "in trash") so you know they are no longer active.
The index is updated at every lifecycle scan, so deleted files
eventually drop out.

Flagged files are hidden from non-admin users entirely — they do
not appear in search results, cannot be opened, and cannot be
batch-downloaded. Admins still see them with a warning banner.

---

## Common Questions

**Why does a natural-language question work better for some
searches than keywords?**
When you ask a question, vector search turns the question into a
semantic "meaning vector" and finds documents whose content is
close in meaning — even if they use totally different words.
Keyword search only matches literal tokens. Both run together, so
you get the best of both automatically.

**Can I search inside images?**
Yes, via two paths: (1) OCR extracts text from scanned PDFs and
image files, and that text is indexed; (2) if LLM vision is
enabled, handwritten pages are transcribed and indexed; (3)
visual enrichment generates descriptions of video keyframes which
are also indexed.

**Is search case-sensitive?**
No. `Budget`, `budget`, `BUDGET` all return the same results.

**Can I search by date?**
Not directly in the search bar, but the **Sort → Date (newest)**
option orders results chronologically, and temporal words in the
query ("latest", "recent") automatically boost recent documents.
For exact date filtering, use the History page.

**Why isn't my just-converted file showing up yet?**
There is a brief delay (usually under a second) between conversion
completing and the file appearing in search. If it has been more
than a minute, Meilisearch may be temporarily unavailable — check
the Status page.

**Can I use Google-style `site:` or `filetype:` operators?**
Not as typed operators. Use the **format chips** above the results
to filter by file type, and the **index** tag on each result to see
where it came from.

**Why does AI Assist show "provider not compatible"?**
AI Assist requires an Anthropic provider with a valid API key.
Go to **Settings → Providers**, add one, and tick **Use for AI
Assist** on that provider.

---

## Related

- [What's New](/help#whats-new)
- [Getting Started](/help#getting-started)
- [LLM Provider Setup](/help#llm-providers)
- [Database Files](/help#database-files)
- [OCR Pipeline](/help#ocr-pipeline)
- [File Lifecycle](/help#file-lifecycle)
- [Settings Reference](/help#settings-guide)
