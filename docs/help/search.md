# Search

MarkFlow indexes the content of every converted document so you can find it later by keyword. The search feature works across all file types — Word, PDF, PowerPoint, Excel, CSV — and even includes metadata from Adobe creative files. This article explains how indexing works, how to use the search page, and what is searchable.


## How Indexing Works

Every time a file is converted, MarkFlow sends the text content to a search engine called Meilisearch. This engine builds an index — think of it as a very fast table of contents for every word in every document you have ever converted.

### What Gets Indexed

| Content type                | Example                                           |
|-----------------------------|---------------------------------------------------|
| Full document text          | Every paragraph, heading, and list item            |
| Table contents              | Text inside table cells                            |
| Image descriptions          | AI-generated descriptions of video keyframes       |
| Document metadata           | Title, author, creation date, format               |
| File path and name          | Where the file lives in the source directory       |
| Adobe file metadata         | Embedded text and properties from creative files   |

Indexing happens automatically after conversion. You do not need to trigger it or wait for it — by the time you see a file in History, it is already searchable.

> **Tip:** Indexing also happens during bulk conversion. As each file finishes converting, it immediately becomes searchable. You do not have to wait for the entire bulk job to complete.

### Two Search Indexes

MarkFlow maintains two separate indexes:

| Index              | What it contains                                             |
|--------------------|--------------------------------------------------------------|
| **Documents**      | All converted documents (Word, PDF, PowerPoint, Excel, CSV)  |
| **Adobe Files**    | Adobe creative files (.ai, .psd, .indd, .aep, .prproj, .xd) |

Both indexes are searched at the same time when you type a query. Results from both appear together, clearly labeled by their source.


## The Search Page

The Search page is the default landing page when you open MarkFlow. It has a single search bar at the top and shows results below.

### Basic Search

1. Click into the search bar (or just start typing — it is focused automatically).
2. Type one or more keywords.
3. Results appear as you type, updating live after a brief pause.

You do not need to press Enter. Results update automatically after you stop typing for about 200 milliseconds.

### Autocomplete

As you type, a dropdown appears below the search bar with suggested completions. These suggestions come from actual document content and filenames in the index.

| Autocomplete feature | How it works                                           |
|----------------------|--------------------------------------------------------|
| **Live suggestions** | Updates with every keystroke after a short delay       |
| **Keyboard navigation** | Use arrow keys to move through suggestions, Enter to select |
| **Deduplication**    | The same suggestion does not appear twice even if it matches in both indexes |

> **Tip:** Autocomplete is great for remembering exact filenames or finding the right spelling of a term. If you know part of a filename, start typing it and the suggestion list will narrow down quickly.

### Search Results

Each result shows:

| Element            | What it displays                                          |
|--------------------|-----------------------------------------------------------|
| **Title**          | The document title or filename                            |
| **File type badge**| A colored badge showing the format (DOCX, PDF, etc.)     |
| **Path**           | Where the source file lives                               |
| **Snippet**        | A highlighted excerpt showing where your keywords appear  |
| **Date**           | When the file was converted                               |

Keywords in the snippet are highlighted so you can quickly see why each result matched.


## Filtering Results

Below the search bar, you will find filter controls that let you narrow down results:

### Format Filter

Click format badges to show only results of a specific type:

- DOCX
- PDF
- PPTX
- XLSX
- CSV
- Adobe

You can select multiple formats at once. Click a selected format again to deselect it. With no formats selected, all types are shown.

### Index Filter

Choose which index to search:

| Filter        | What it searches                       |
|---------------|----------------------------------------|
| **All**       | Both documents and Adobe files         |
| **Documents** | Only converted documents               |
| **Adobe**     | Only Adobe creative file metadata      |


## What Is Searchable

Here is a detailed breakdown of what you can search for and where it comes from:

### Document Content

When you convert a Word document that says "The quarterly revenue exceeded expectations," you can search for "quarterly revenue" or "expectations" and that document will appear.

The full text of every converted document is searchable, including:

- Headings and body paragraphs
- Text inside tables
- List items
- Footnotes and endnotes
- Speaker notes (from PowerPoint)
- Sheet content (from Excel)

### Metadata

Each document carries metadata that is also searchable:

| Metadata field   | Example                                    |
|------------------|--------------------------------------------|
| Title            | "Q3 Financial Report"                      |
| Author           | "Jane Smith"                               |
| Format           | "docx", "pdf"                              |
| Source path      | "finance/reports/q3-report.docx"           |
| Conversion date  | Stored but typically filtered, not searched |

### AI-Generated Descriptions

If your team uses the visual enrichment feature, MarkFlow extracts keyframes from video files and generates text descriptions of what appears in each frame. These descriptions are indexed and searchable.

For example, if a video contains a frame described as "presenter standing in front of whiteboard with workflow diagram," you could search for "workflow diagram" and find that video.

> **Tip:** Visual enrichment and frame descriptions require an active AI provider to be configured. Ask your administrator if this feature is available.


## Adobe Files in Search

MarkFlow has special handling for Adobe creative files. While these files cannot be converted to Markdown (their formats are too specialized), MarkFlow extracts what text and metadata it can and indexes it for search.

### Supported Adobe Formats

| Format                  | Extension | What is extracted                            |
|-------------------------|-----------|----------------------------------------------|
| Adobe Illustrator       | `.ai`     | Embedded text layers, document metadata       |
| Adobe Photoshop         | `.psd`    | Text layers from the PSD, metadata            |
| Adobe InDesign          | `.indd`   | Document metadata (title, author, keywords)   |
| Adobe After Effects     | `.aep`    | Project metadata                              |
| Adobe Premiere Pro      | `.prproj` | Project metadata                              |
| Adobe XD                | `.xd`     | Project metadata                              |

### How Adobe Indexing Works

During a bulk scan, MarkFlow identifies Adobe files and runs a metadata extraction tool (exiftool) against them. For Illustrator and Photoshop files, it also reads embedded text layers directly from the file.

The extracted information is sent to the Adobe Files search index. When you search, results from this index are labeled with an "Adobe" badge so you can distinguish them from regular document results.

> **Tip:** Adobe files often have useful metadata that was set by the creator — things like document title, description, keywords, and copyright info. Even if the file itself cannot be converted, you can find it through this metadata.


## Rebuilding the Search Index

If the search index ever gets out of sync (for example, after a server migration or database restore), an administrator can rebuild it.

This is done from the Search page or the Admin panel. Rebuilding walks through all converted documents in the database and re-sends them to Meilisearch. Depending on how many documents you have, this can take anywhere from seconds to several minutes.

> **Warning:** During a rebuild, search results may be incomplete until the process finishes. The search page will still work — it just may not show all results until rebuilding is done.


## Search and Deleted Files

If a file has been deleted or moved to trash (see [File Lifecycle](/help#file-lifecycle)), it may still appear in search results briefly until the index catches up. Deleted files in search results show a visual indicator so you know they are no longer active.

If you see a search result for a file that has been deleted:

- The result will have a lifecycle badge showing its status (marked for deletion, in trash, etc.)
- You can still see the document content that was indexed
- The original file may no longer be available for download

The index is updated during lifecycle scans, so deleted files are eventually removed from search results.


## Search Settings

There are no user-facing search settings to configure. Search works automatically once documents are converted. The following are managed by administrators:

| Setting                  | What it controls                                  | Managed by    |
|--------------------------|---------------------------------------------------|---------------|
| **Meilisearch connection** | The search engine URL and API key               | Administrator |
| **Index rebuild**        | Triggering a full re-index of all documents       | Administrator |
| **Searchable attributes** | Which fields are searched (all by default)       | System default |


## Tips for Effective Searching

**Use specific terms.** Searching for "report" will return thousands of results. Searching for "Q3 revenue forecast" will return exactly what you need.

**Search for phrases.** Type multiple words and Meilisearch will find documents containing all of them, with priority given to documents where the words appear near each other.

**Try partial words.** Meilisearch supports prefix search. Typing "finan" will match "finance," "financial," and "financing."

**Use the format filter.** If you know you are looking for a spreadsheet, click the XLSX badge to eliminate all other formats from the results.

**Check autocomplete.** The suggestions often reveal the exact phrasing used in a document, which can help you refine your search.


## Common Questions

**Why is my recently converted file not showing up in search?**
There is a brief delay (usually under a second) between conversion completing and the file appearing in search. If it has been more than a minute, the search engine may be temporarily unavailable. Try again shortly.

**Can I search inside images?**
Not directly. However, if a PDF's text was extracted via OCR, that text is indexed and searchable. And if visual enrichment is enabled, AI-generated descriptions of video keyframes are searchable.

**Is search case-sensitive?**
No. Searching for "Budget," "budget," or "BUDGET" all return the same results.

**Can I search by date?**
Not directly in the search bar, but you can use the History page to filter conversions by date range.


## Related

- [Getting Started](/help#getting-started)
- [Document Conversion](/help#document-conversion)
- [Bulk Conversion](/help#bulk-conversion)
- [File Lifecycle](/help#file-lifecycle)
- [OCR Pipeline](/help#ocr-pipeline)
