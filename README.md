# MarkFlow — Document Conversion

Convert documents bidirectionally between their original format and Markdown (`.md`).
Runs OCR automatically on scanned content, supports batch processing, and persists
all conversion history across restarts.

**Supported formats:** DOCX, DOC, PDF, PPTX, XLSX, CSV, TSV, RTF, ODT, ODS, ODP, HTML,
EPUB, EML, MSG, JSON, YAML, XML, INI, TXT, ZIP, TAR, 7z, RAR, and Adobe creative files
(PSD, AI, INDD, AEP, PRPROJ, XD). Bidirectional conversion to/from Markdown.

---

## Quick Start

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)

```bash
git clone https://github.com/theace26/Doc-Conversion-2026.git
cd Doc-Conversion-2026
docker-compose up -d
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Usage

### Web UI

1. Drop files onto the upload zone (or click to browse).
2. Select direction: **Document → Markdown** or **Markdown → Document**.
3. Click **Preview** to inspect the file before converting.
4. Click **Convert** — a batch progress page opens automatically.
5. Review any OCR-flagged items (scanned PDFs), then download results.

### API

Full interactive API docs at [http://localhost:8000/docs](http://localhost:8000/docs).

```bash
# Convert a file to Markdown
curl -X POST http://localhost:8000/api/convert \
  -F "files=@report.docx" \
  -F "direction=to_md"

# Check batch status
curl http://localhost:8000/api/batch/<batch_id>/status

# Download converted files
curl -O http://localhost:8000/api/batch/<batch_id>/download
```

### Input / Output Volumes

| Volume | Purpose |
|--------|---------|
| `./input` | Drop source files here for bulk processing |
| `./output` | Converted files written here, organized by batch |
| `./logs` | Application logs (JSON structured) |

---

## Configuration

Environment variables (set in `docker-compose.yml` or `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug logging + intermediate file dumps |
| `WORKERS` | `1` | Uvicorn worker count |
| `DB_PATH` | `/app/data/markflow.db` | SQLite database path |

### User Preferences

Adjust in the **Settings** page (`/settings.html`) or via the API:

```bash
# Get all preferences
curl http://localhost:8000/api/preferences

# Change OCR confidence threshold
curl -X PUT http://localhost:8000/api/preferences/ocr_confidence_threshold \
  -H "Content-Type: application/json" \
  -d '"75"'
```

Key preferences:

| Key | Default | Description |
|-----|---------|-------------|
| `ocr_confidence_threshold` | `80` | Flag words below this % confidence |
| `default_direction` | `to_md` | Default conversion direction |
| `max_upload_size_mb` | `100` | Per-file upload limit |
| `retention_days` | `30` | Days before auto-cleanup of output files |
| `pdf_engine` | `pymupdf` | PDF extraction engine (pymupdf / pdfplumber) |
| `pdf_export_engine` | `weasyprint` | PDF export engine (weasyprint / fpdf2) |
| `unattended_default` | `false` | Auto-accept all OCR without review |

---

## Development Setup

```bash
# Install Python dependencies locally
pip install -r requirements.txt

# Run without Docker (requires Tesseract + LibreOffice + Poppler installed)
uvicorn main:app --reload

# Run tests
pytest tests/

# Build Docker image
docker-compose build

# View logs
docker-compose logs -f markflow
```

### System Requirements (non-Docker)

- Python 3.12+
- Tesseract OCR 5.x (`tesseract-ocr`, `tesseract-ocr-eng`)
- Poppler utilities (`poppler-utils`)
- LibreOffice headless (`libreoffice-writer`, `libreoffice-impress`)
- WeasyPrint C libraries (`libpango`, `libcairo2`, `libgdk-pixbuf2.0-0`)

---

## Architecture

MarkFlow uses a **format-agnostic intermediate representation** (`DocumentModel`).
All format handlers convert to/from this model, reducing N×M converters to N+M.

```
.docx / .pdf / .pptx / .xlsx
         ↓  ingest()
    DocumentModel
         ↓  export()
    .md / .docx / .pdf / .pptx / .xlsx
```

**Fidelity tiers:**
- **Tier 1** (guaranteed): Headings, paragraphs, lists, tables, images — structure always survives.
- **Tier 2** (sidecar): Fonts, spacing, colors — restored from `.styles.json` sidecar when available.
- **Tier 3** (original): Complex layouts — restored by patching against the preserved original file.

---

## Project Structure

```
Doc-Conversion-2026/
├── main.py              # FastAPI app entry point
├── api/                 # Route handlers + middleware
├── core/                # Orchestration, OCR, DB, metadata
├── formats/             # Per-format handlers (docx, pdf, pptx, xlsx, md)
├── static/              # HTML/CSS/JS frontend
└── tests/               # pytest test suite
```

---

## Phase Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Docker scaffold, project structure, DB schema | ✅ Complete |
| 1 | DOCX → Markdown pipeline | ✅ Complete |
| 2 | Markdown → DOCX round-trip with fidelity tiers | ✅ Complete |
| 3 | OCR pipeline (multi-signal detection, review UI) | ✅ Complete |
| 4 | PDF, PPTX, XLSX/CSV format handlers | ✅ Complete |
| 4b | Universal format support (RTF, ODT, HTML, EPUB, EML, archives) | ✅ Complete |
| 5 | Testing & debug infrastructure | ✅ Complete |
| 6 | Full UI, batch progress, history, settings | ✅ Complete |
| 7 | Bulk conversion, Adobe indexing, Meilisearch, Cowork | ✅ Complete |
| 8b | Visual enrichment: scene detection, keyframe extraction | ✅ Complete |
| 8c | Unknown & unrecognized file cataloging | ✅ Complete |
| 9 | File lifecycle management, version tracking, DB health | ✅ Complete |
| 10 | Auth layer, role guards, API keys, UnionCore integration | ✅ Complete |

**Current version:** v0.12.1

---

## License

MIT
