# Fidelity Tiers

When MarkFlow converts a document, it captures your content at different levels of detail. These levels are called **fidelity tiers**. The tier determines how closely the converted output matches the original document's appearance — especially when you convert the Markdown back to the original format.

Understanding tiers helps you decide what files to keep and when to use the round-trip feature.


## The Three Tiers at a Glance

| Tier | Name                | What it preserves                           | When it applies                              |
|------|---------------------|---------------------------------------------|----------------------------------------------|
| 1    | **Structure**       | Headings, paragraphs, tables, lists, images | Always — every conversion gets at least this |
| 2    | **Styles**          | Fonts, sizes, colors, spacing, page layout  | When a style sidecar is available            |
| 3    | **Original Patch**  | Exact original appearance via file patching  | When the original file is also provided      |


## Tier 1: Structure (Always Guaranteed)

Every conversion produces at least Tier 1. This means the **content and structure** of your document are faithfully represented in Markdown:

- Headings at the correct level (Heading 1, Heading 2, etc.)
- Paragraphs of body text
- Bold, italic, and inline code formatting
- Bulleted and numbered lists
- Tables with rows and columns
- Images (extracted as separate PNG files)
- Footnotes and endnotes
- Metadata (title, author, dates) in a YAML header

What Tier 1 does **not** capture:

- Exact font names and sizes
- Text colors and highlighting
- Paragraph spacing and indentation
- Page margins and orientation
- Cell shading in tables

> **Tip:** For most everyday uses — reading, searching, editing text — Tier 1 gives you everything you need. Markdown is designed for content, not pixel-perfect layout.

### When Tier 1 Is All You Get

If you upload a single file and convert it to Markdown, then later convert that Markdown back without any additional files, you get Tier 1. The structure is correct, but the visual styling uses default formatting.


## Tier 2: Styles (With the Sidecar)

Tier 2 adds **visual formatting** on top of Tier 1. This happens when MarkFlow has access to a **style sidecar** — a small JSON file that records every formatting detail from the original document.

### What Is the Style Sidecar?

When you convert a document to Markdown, MarkFlow automatically creates a file named `filename.styles.json` alongside the Markdown output. This sidecar contains information like:

| Style property      | Example values                     |
|---------------------|------------------------------------|
| Font name           | Calibri, Times New Roman, Arial    |
| Font size           | 11pt, 14pt, 24pt                   |
| Text color          | Black, navy, custom hex colors     |
| Bold / Italic       | Applied at the run level           |
| Paragraph spacing   | Before: 6pt, After: 12pt          |
| Line spacing        | Single, 1.15, Double               |
| Indentation         | Left: 0.5in, Hanging: 0.25in      |
| Page margins        | Top: 1in, Bottom: 1in             |
| Page orientation    | Portrait or Landscape              |
| Table cell shading  | Background colors per cell         |

The sidecar uses **content-hash keying** — each entry is linked to the actual text content of the paragraph or table it describes. This means even if you rearrange paragraphs in the Markdown, the correct style still gets applied when converting back.

### How to Get Tier 2

When converting from Markdown back to the original format:

1. Upload your `.md` file.
2. Upload the `.styles.json` file alongside it (in the same batch).

MarkFlow detects the sidecar automatically and uses it to apply the original formatting.

> **Tip:** Always keep the `.styles.json` file alongside your Markdown if you plan to convert it back later. Without it, you lose the visual formatting.

### What Tier 2 Looks Like

A Word document converted at Tier 2 will have the correct fonts, sizes, spacing, and colors for each paragraph. Tables will have their cell shading. The document will look very close to the original, though some complex features (like text boxes or shapes) may not be perfectly reproduced.


## Tier 3: Original Patch (Best Possible Fidelity)

Tier 3 is the highest level. Instead of building a new document from scratch, MarkFlow **patches the original file** with your Markdown changes. This preserves everything — including features that neither Markdown nor the sidecar can capture.

### What Tier 3 Preserves That Tier 2 Does Not

| Feature                    | Tier 2          | Tier 3               |
|----------------------------|-----------------|----------------------|
| Text boxes and shapes      | Lost            | Preserved            |
| Embedded charts            | Lost            | Preserved            |
| Conditional formatting     | Lost            | Preserved            |
| Macros and VBA             | Lost            | Preserved            |
| Custom XML parts           | Lost            | Preserved            |
| Exact image positioning    | Approximate     | Exact                |
| Headers and footers        | Basic           | Exact                |
| Complex table layouts      | Simplified      | Exact                |
| Slide animations (PPTX)    | Lost            | Preserved            |
| Cell formulas (XLSX)       | In sidecar only | Live in spreadsheet  |

### How to Get Tier 3

When converting from Markdown back to the original format:

1. Upload your `.md` file.
2. Upload the `.styles.json` sidecar.
3. Upload the **original file** (the `.docx`, `.pptx`, or `.xlsx` you started with).

MarkFlow detects all three files and applies Tier 3 patching automatically. It takes your edited Markdown content, finds what changed compared to the original, and patches those changes into the original file — leaving everything else untouched.

> **Warning:** Tier 3 is not available for PDF files. PDF internal structure is too complex for reliable patching. PDFs always use Tier 1 or Tier 2.

### How Patching Works

Think of Tier 3 like editing a Word document with Track Changes, except MarkFlow does it for you:

1. MarkFlow reads the Markdown to find the current content.
2. It reads the original document to find the old content.
3. It matches paragraphs, tables, and cells between the two using content hashes.
4. For anything that changed, it updates the text in the original file.
5. For anything that did not change, the original formatting stays exactly as it was.

This means if you only changed one paragraph in the Markdown, only that paragraph is touched in the output. Everything else — images, charts, headers, footers, shapes — remains identical to the original.


## Which Tier Should I Use?

Here is a simple decision guide:

| Your situation                                             | Recommended tier |
|------------------------------------------------------------|------------------|
| I just need the text content in a readable format          | Tier 1           |
| I want to edit the text and rebuild a nice-looking document | Tier 2          |
| I made small edits and need the document to look identical | Tier 3           |
| I am converting PDFs                                       | Tier 1 or 2      |
| I am archiving documents for search                        | Tier 1           |
| I am sending the document to a client or printing it       | Tier 3           |

> **Tip:** When in doubt, keep all three files (Markdown, sidecar, and original) together. That way you always have the option of Tier 3 later. Storage is cheap; redoing work is not.


## Tier Detection Is Automatic

You do not need to choose a tier from a menu. MarkFlow detects which files are available and picks the highest tier possible:

| Files you provide                          | Tier selected |
|--------------------------------------------|---------------|
| `.md` only                                 | Tier 1        |
| `.md` + `.styles.json`                     | Tier 2        |
| `.md` + `.styles.json` + original file     | Tier 3        |

The conversion results will tell you which tier was used.


## Format-Specific Notes

### Word (.docx)
All three tiers work. Tier 3 is especially effective because the DOCX format is well-structured and easy to patch.

### PowerPoint (.pptx)
Tier 3 patches slide text while preserving animations, transitions, and slide layouts. Images and shapes on slides are untouched.

### Excel (.xlsx)
Tier 3 restores formulas, merged cells, conditional formatting, and cell styles. Tier 2 can restore most formatting but formulas exist only in the sidecar. Tier 1 produces a basic spreadsheet with values only.

### CSV (.csv, .tsv)
CSV files are plain text, so tiers are less relevant. The sidecar records the original delimiter and encoding so round-trip conversion preserves those details.

### PDF (.pdf)
Only Tier 1 and Tier 2 are supported. MarkFlow converts Markdown to PDF by rendering it as HTML first, then generating a new PDF. The output looks clean but will not match the original PDF layout exactly.


## Keeping Your Files Organized

A good practice for round-trip conversion is to keep the three related files together:

```
project/
  report.md              <- The Markdown (your working copy)
  report.styles.json     <- The style sidecar
  report.docx            <- The original document
```

If you are using [Bulk Conversion](/help#bulk-conversion), MarkFlow stores these files in a structured output directory automatically. The sidecar and original are always placed alongside the Markdown output.


## Related

- [Getting Started](/help#getting-started)
- [Document Conversion](/help#document-conversion)
- [OCR Pipeline](/help#ocr-pipeline)
- [Bulk Conversion](/help#bulk-conversion)
- [File Lifecycle](/help#file-lifecycle)
