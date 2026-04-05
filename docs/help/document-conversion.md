# Document Conversion

MarkFlow converts documents between their original format and Markdown. This article covers every supported format, how to use the upload interface, and how to download your results.


## Supported Formats

MarkFlow supports these file types in both directions — original to Markdown, and Markdown back to original:

| Category | Extensions | What it is | Notes |
|----------|-----------|------------|-------|
| Word | `.docx`, `.doc`, `.docm`, `.wpd`, `.wbk` | Microsoft Word and compatible | `.doc`/`.wbk`/`.wpd` converted via LibreOffice |
| PDF | `.pdf` | Portable Document Format | Text-based and scanned (via OCR) |
| PowerPoint | `.pptx`, `.ppt`, `.pptm` | Microsoft PowerPoint | `.ppt` converted via LibreOffice; `.pptm` macros stripped |
| Excel | `.xlsx`, `.xls` | Microsoft Excel spreadsheets | `.xls` converted via LibreOffice |
| CSV/Data | `.csv`, `.tsv`, `.tab` | Delimited data files | Auto-detects delimiter and encoding |
| Publisher | `.pub`, `.p65` | Microsoft Publisher / PageMaker | Converted via LibreOffice |
| Text | `.txt`, `.log`, `.text`, `.lst` | Plain text files | Heading detection, encoding fallback |
| Code | `.cc`, `.css` | Source code files | Treated as plain text with syntax hints |
| Config | `.ini`, `.cfg`, `.conf`, `.properties` | Configuration files | Section-aware parsing |
| Markup | `.md`, `.html`, `.htm`, `.xml`, `.json`, `.yaml`, `.yml` | Structured text formats | Full round-trip support |
| RTF | `.rtf` | Rich Text Format | Control-word parser |
| OpenDocument | `.odt`, `.ods`, `.odp` | LibreOffice native formats | Via odfpy |
| Email | `.eml`, `.msg` | Email messages | Recursive attachment conversion |
| EPUB | `.epub` | Electronic publications | Chapter extraction |
| Images | `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.bmp`, `.gif`, `.eps`, `.cr2`, `.heic`, `.heif` | Raster images and RAW photos | EXIF metadata extraction |
| Vector | `.svg` | Scalable Vector Graphics | XML parsing, text extraction |
| Fonts | `.otf`, `.ttf` | OpenType and TrueType fonts | Metadata: family, style, glyph count |
| Adobe | `.psd`, `.psb`, `.ai`, `.indd`, `.aep`, `.prproj`, `.xd` | Creative suite files | Text layer extraction, metadata |
| Audio | `.mp3`, `.wav`, `.flac`, `.ogg`, `.m4a`, `.wma`, `.aac` | Audio files | Whisper transcription |
| Video | `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.m4v`, `.webm` | Video files | Transcription + scene detection |
| Archives | `.zip`, `.tar`, `.tar.gz`, `.7z`, `.rar`, `.cab`, `.iso` | Compressed archives | Recursive extraction + conversion |
| Contacts | `.vcf` | vCard contact files | Multi-contact parsing |
| Shortcuts | `.lnk`, `.url` | Windows shortcuts and URL files | Target path/URL extraction |
| Temporary | `.tmp` | Temporary files | MIME-detected and routed to correct handler |
| Binary | `.bin`, `.cl4`, `.exe`, `.dll`, `.so`, `.msi`, `.sys`, `.drv`, `.ocx`, `.cpl`, `.scr`, `.com`, `.dylib`, `.app`, `.dmg`, `.img`, `.vhd`, `.vhdx`, `.vmdk`, `.vdi`, `.qcow2`, `.sqlite`, `.db`, `.mdb`, `.accdb`, `.rom`, `.fw`, `.efi`, `.class`, `.pyc`, `.pyo`, `.o`, `.obj`, `.lib`, `.a`, `.dat`, `.dmp` | Binary and executable files | Metadata only (size, MIME, magic bytes) |

> **Tip:** If you are not sure whether your file type is supported, just try uploading it. MarkFlow will tell you immediately if it cannot handle the format.

### Format Details

**Word (.docx)** is the best-supported format. Headings, paragraphs, bold, italic, code, tables, images, footnotes, and nested tables all come through cleanly. Legacy formats (`.doc`, `.wbk`, `.wpd`) and Publisher files (`.pub`, `.p65`) are first converted to `.docx` via LibreOffice headless.

**PDF (.pdf)** works well for text-based PDFs. If your PDF is a scanned image (no selectable text), MarkFlow uses OCR to read the text. See [OCR Pipeline](/help#ocr-pipeline) for details on how that works.

**PowerPoint (.pptx, .pptm)** treats each slide as a separate section. Slide titles become headings, and bullet points become lists. Speaker notes are included. Images on slides are extracted. Macro-enabled `.pptm` files are processed identically (macros are not executed).

**Excel (.xlsx)** converts each worksheet into a Markdown table with the sheet name as a heading. Formulas, merged cells, and cell formatting are preserved in the style sidecar for round-trip fidelity.

**CSV/TSV/TAB (.csv, .tsv, .tab)** files are read as data tables. MarkFlow detects the delimiter (comma, tab, semicolon) and character encoding automatically.

**Images (.jpg, .png, .tif, .bmp, .gif, .eps, .cr2)** are catalogued with EXIF metadata extraction. Canon RAW (`.cr2`) files are processed via Pillow with graceful fallback.

**Fonts (.otf, .ttf)** have metadata extracted via fonttools: family name, style, glyph count, supported Unicode ranges, and a sample of characters.

**Shortcuts (.lnk, .url)** have their target path or URL extracted. `.url` files are parsed as INI format; `.lnk` binary shortcuts are scanned for readable path strings.

**Temporary files (.tmp)** are MIME-detected and routed to the correct handler. If the content type cannot be determined, they are catalogued with basic metadata.

> **Note:** Legacy formats like `.doc`, `.xls`, `.ppt`, `.pub`, and `.p65` are converted via LibreOffice headless before processing. This requires LibreOffice to be installed in the container (included in the base image).


## The Upload Interface

The Convert page is where single-file conversions happen. Here is what you will find on the page.

### Direction Toggle

At the top of the page is a toggle that controls the conversion direction:

| Setting            | What happens                                                |
|--------------------|-------------------------------------------------------------|
| **To Markdown**    | Upload an original file, get Markdown back                  |
| **From Markdown**  | Upload a Markdown file, get the original format back        |

When converting **from Markdown**, MarkFlow looks for a style sidecar file (a `.styles.json` file) alongside your Markdown. If it finds one, the output will include more of the original formatting. See [Fidelity Tiers](/help#fidelity-tiers) for the full explanation.

### The Upload Area

The large area in the center of the page is where you add your files. You can:

- **Drag and drop** files directly from your desktop or file explorer.
- **Click the area** to open a standard file picker dialog.

Once you add a file, it appears as a card showing:

- The filename
- A badge with the file type (DOCX, PDF, etc.)
- The file size

You can upload multiple files at once. Each one gets its own card.

> **Tip:** To remove a file before converting, click the X button on its card.

### The Convert Button

After adding your files, click **Convert** to start. The button is disabled until at least one valid file is added.


## Batch Progress

After you click Convert, MarkFlow takes you to the progress screen. This is a live view — it updates automatically as each file is processed.

What you will see:

| Element            | What it shows                                              |
|--------------------|------------------------------------------------------------|
| **Progress bar**   | Overall completion percentage across all files             |
| **File list**      | Each file with its current status: waiting, converting, done, or failed |
| **OCR banner**     | Appears if a PDF needs OCR — lets you know it may take longer |
| **Time elapsed**   | How long the conversion has been running                   |

The progress screen uses a live connection to the server, so you do not need to refresh the page. Just watch the progress bar fill up.

> **Warning:** If you close the browser tab during conversion, the conversion continues in the background. You can find the results in [History](/help#getting-started) when it finishes.

### What If a File Fails?

If a file cannot be converted, it shows a red "Failed" status on the progress screen. The rest of the files in the batch continue normally — one bad file never stops the others.

Common reasons a file might fail:

- The file is password-protected
- The file is corrupt or incomplete
- The file is extremely large and runs out of memory
- A scanned PDF has unreadable text (see [OCR Pipeline](/help#ocr-pipeline))


## Downloading Results

Once conversion is complete, you have several ways to get your files.

### From the Progress Screen

When the batch finishes, download links appear next to each completed file. You can:

- **Download individual files** — Click the link next to any single file.
- **Download All as ZIP** — Get everything in one archive, including images, sidecars, and the manifest.

### From History

Every conversion is recorded in History. Go to **History** in the navigation bar to see all your past conversions. From there you can:

- Search and filter by date, format, or filename
- Click any conversion to see its details
- Re-download any file or the entire batch

> **Tip:** History is the best place to find a conversion you did last week or last month. Use the search bar to filter by filename.


## What Gets Produced

A typical conversion creates several files, not just one. Here is what to expect:

| File                         | What it is                                                     |
|------------------------------|----------------------------------------------------------------|
| `filename.md`                | The converted Markdown file (your main output)                 |
| `filename.styles.json`       | Style sidecar — formatting details for round-trip conversion   |
| `_originals/filename.docx`   | A copy of your original file                                   |
| `manifest.json`              | Metadata about the batch: file list, timestamps, settings used |
| Image files (`.png`)         | Any images extracted from the document                         |

The style sidecar and manifest are created automatically. You do not need to do anything with them unless you plan to convert the Markdown back to the original format later.


## Converting Back to the Original Format

To turn a Markdown file back into a Word document (or PDF, or any other format):

1. Go to the **Convert** page.
2. Set the direction toggle to **From Markdown**.
3. Upload your `.md` file.
4. Optionally, upload the `.styles.json` sidecar and the original file alongside it. The more files you provide, the better the output will look. See [Fidelity Tiers](/help#fidelity-tiers).
5. Click **Convert**.

MarkFlow detects the target format from the sidecar metadata or asks you to specify it.

> **Tip:** For the best results when converting back, keep the `.md`, `.styles.json`, and original file together. MarkFlow will use all three to produce the highest fidelity output.


## Settings That Affect Conversion

These preferences on the Settings page influence how conversions behave:

| Setting                   | What it controls                                        | Default   |
|---------------------------|---------------------------------------------------------|-----------|
| **OCR Confidence Threshold** | Minimum confidence for accepting OCR text            | 60%       |
| **Unattended Mode**       | Skip OCR review prompts and accept all text automatically | Off     |
| **Worker Count**          | Number of files processed in parallel during bulk jobs  | 2         |

For more on OCR settings, see [OCR Pipeline](/help#ocr-pipeline). For bulk job settings, see [Bulk Conversion](/help#bulk-conversion).


## Troubleshooting

**My converted Markdown is missing some formatting.**
This is normal for complex documents. MarkFlow captures structure (headings, tables, lists) reliably. Fine-grained formatting like exact font sizes and colors is stored in the style sidecar, not in the Markdown itself. See [Fidelity Tiers](/help#fidelity-tiers).

**My PDF conversion has garbled text.**
The PDF may be a scanned image. MarkFlow uses OCR for these, but results depend on scan quality. Check the [OCR Pipeline](/help#ocr-pipeline) article for tips on improving OCR results.

**The conversion is taking a very long time.**
Large PDFs with many pages, especially scanned ones requiring OCR, can take minutes. The progress screen shows live updates so you can track where it is.

**I uploaded the wrong file.**
You cannot cancel a conversion that has already started, but the original file is always preserved in `_originals/`. Just start a new conversion with the correct file.


## Related

- [Getting Started](/help#getting-started)
- [Fidelity Tiers](/help#fidelity-tiers)
- [OCR Pipeline](/help#ocr-pipeline)
- [Bulk Conversion](/help#bulk-conversion)
- [Search](/help#search)
