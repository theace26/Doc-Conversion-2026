# MarkFlow Supported Formats

Canonical reference for every file type MarkFlow can scan, convert, transcribe, or catalog.
This is the single source of truth — `README.md` and `CLAUDE.md` both link here rather than
duplicating the list.

All document formats support **bidirectional conversion** (original → Markdown → original).
Media files produce timestamped transcripts. Archives are recursively extracted and each
inner file is converted. Binary files are cataloged with metadata (size, MIME type, magic
bytes) for searchability.

---

## Full Format Table

| Category | Extensions | Handler |
|----------|-----------|---------|
| Office | `.docx` `.doc` `.docm` `.wbk` `.pub` `.p65` `.pdf` `.pptx` `.ppt` `.pptm` `.xlsx` `.xls` `.csv` `.tsv` `.tab` | DocxHandler, PdfHandler, PptxHandler, XlsxHandler, CsvHandler |
| WordPerfect | `.wpd` | DocxHandler (via LibreOffice preprocessing) |
| Rich Text | `.rtf` | RtfHandler |
| OpenDocument | `.odt` `.ods` `.odp` | OdtHandler, OdsHandler, OdpHandler |
| Markdown & Text | `.md` `.txt` `.log` `.text` `.lst` | MarkdownHandler, TxtHandler |
| Code | `.cc` `.css` | TxtHandler |
| Web & Data | `.html` `.htm` `.xml` `.epub` | HtmlHandler, XmlHandler, EpubHandler |
| Data & Config | `.json` `.yaml` `.yml` `.ini` `.cfg` `.conf` `.properties` | JsonHandler, YamlHandler, IniHandler |
| Email & Contacts | `.eml` `.msg` (recursive attachment conversion), `.vcf` | EmlHandler |
| Archives | `.zip` `.tar` `.tar.gz` `.tgz` `.tar.bz2` `.tbz2` `.tar.xz` `.txz` `.7z` `.rar` `.cab` `.iso` | ArchiveHandler |
| Adobe Creative | `.psd` `.psb` `.ai` `.indd` `.aep` `.prproj` `.xd` `.ait` `.indt` | AdobeHandler |
| Images | `.jpg` `.jpeg` `.png` `.tif` `.tiff` `.bmp` `.gif` `.eps` `.cr2` `.heic` `.heif` | ImageHandler |
| Vector | `.svg` | ImageHandler |
| Fonts | `.otf` `.ttf` | BinaryHandler |
| Audio | `.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.wma` | AudioHandler |
| Video | `.mp4` `.mov` `.avi` `.mkv` `.webm` `.m4v` `.wmv` | MediaHandler |
| Captions | `.srt` `.vtt` `.sbv` | CaptionIngestor (via AudioHandler) |
| Shortcuts | `.lnk` `.url` | BinaryHandler |
| Temporary | `.tmp` (MIME-detected and routed to the correct handler) | BinaryHandler + MIME detection |
| Database | `.sqlite` `.db` `.sqlite3` `.s3db` `.mdb` `.accdb` `.dbf` `.qbb` `.qbw` | DatabaseHandler |
| Binary (metadata) | `.bin` `.cl4` `.exe` `.dll` `.so` `.msi` `.sys` `.drv` `.ocx` `.cpl` `.scr` `.com` `.dylib` `.app` `.dmg` `.img` `.vhd` `.vhdx` `.vmdk` `.vdi` `.qcow2` `.rom` `.fw` `.efi` `.class` `.pyc` `.pyo` `.o` `.obj` `.lib` `.a` `.dat` `.dmp` | BinaryHandler |

---

## Notes

- **Compound extensions** (`.tar.gz`, `.tar.bz2`, `.tar.xz`) require compound extension
  lookup in both `formats/base.py` and `core/bulk_scanner.py`. `Path.suffix` only returns
  `.gz` — use `_get_compound_extension()` / `_get_effective_extension()`.
- **Legacy Office** formats (`.doc`, `.xls`, `.ppt`, `.wpd`, `.docm`) are preprocessed via
  LibreOffice headless (`core/libreoffice_helper.py`) into modern equivalents before
  being handled by the existing DocxHandler / XlsxHandler / PptxHandler pipelines.
- **HEIC/HEIF** support was added in v0.19.6.8.
- **EPS** files now convert via Pillow + Ghostscript. Ghostscript was added to
  `Dockerfile.base` in v0.22.14 (with a temporary `apt-get install ghostscript` shim
  in the app `Dockerfile` so the fix ships without a 25-min base rebuild).
- **Handler registry** — `ALLOWED_EXTENSIONS` is derived from the handler registry, so
  new format handlers automatically extend scan coverage.

See [`key-files.md`](key-files.md) for the list of handler source files and
[`version-history.md`](version-history.md) for when each format was added.
