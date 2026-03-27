# MarkFlow — Integration Brief

## What MarkFlow Is

MarkFlow is a standalone Python web application that converts documents bidirectionally between their original format and Markdown (`.md`). It runs locally, has a browser-based UI, and is designed as a lightweight utility tool — not a platform.

**Core capabilities:**
- Converts `.docx`, `.doc`, `.pdf` (text + scanned/image), `.pptx`, `.xlsx`, and `.csv` → Markdown
- Converts Markdown back to the original format with best-effort pixel-perfect fidelity
- Automatic OCR on scanned/image-based content (Tesseract-based)
- Interactive OCR error review — flags low-confidence text, shows original vs. best guess side-by-side, lets the user approve/edit/skip individually or batch-accept all remaining
- Batch processing — upload multiple files, process as a group
- Metadata preservation for round-trip fidelity (YAML frontmatter per `.md` file + batch manifest JSON + per-file style sidecar JSON)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | **FastAPI** (Python, async) |
| Frontend | Simple browser UI (vanilla HTML/JS or htmx — no SPA framework) |
| OCR | **Tesseract** via `pytesseract` |
| Document parsing | `python-docx`, `mammoth`, `pdfplumber`, `pdf2image`, `python-pptx`, `openpyxl`, `pandas` |
| Document generation | `python-docx`, `weasyprint` or `fpdf2`, `python-pptx`, `openpyxl` |
| Storage | Local filesystem (`output/` directory, organized by batch) |

---

## API Surface

MarkFlow is built on FastAPI, which auto-generates OpenAPI/Swagger docs. Key endpoints (planned):

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/convert` | POST | Upload file(s), specify direction (to-md or from-md), returns job ID |
| `/api/batch/{batch_id}/status` | GET | Poll batch progress (per-file status, OCR flags pending) |
| `/api/batch/{batch_id}/review` | GET | Retrieve OCR-flagged items for review |
| `/api/batch/{batch_id}/review/{flag_id}` | POST | Submit resolution for an OCR flag (accept, edit, skip) |
| `/api/batch/{batch_id}/review/accept-all` | POST | Accept all remaining OCR flags |
| `/api/batch/{batch_id}/download` | GET | Download converted files (individual or zip) |
| `/api/batch/{batch_id}/manifest` | GET | Retrieve the batch manifest JSON |

All endpoints return JSON. File uploads use multipart/form-data. The API is stateless per-request — batch state lives on the filesystem.

---

## Metadata System

Every conversion produces three metadata artifacts:

1. **YAML frontmatter** (embedded at top of each `.md` file) — source filename, format, conversion timestamp, version, OCR flag, style reference pointer
2. **Batch manifest** (`manifest.json` per batch) — lists all files in the batch, their status, OCR flag counts, and style reference paths
3. **Style sidecar** (`.styles.json` per file) — format-specific layout/styling metadata used to reconstruct the original format on round-trip (fonts, spacing, table widths, slide layouts, cell formats, etc.)

This metadata is what enables the "convert back to original format" feature. Without it, round-trip conversion loses formatting.

---

## Integration Considerations

### MarkFlow as a service for another application

MarkFlow's FastAPI backend is designed to be callable programmatically — any system that can make HTTP requests can use it. Integration patterns to consider:

- **Direct API calls**: UnionCore sends documents to MarkFlow's `/api/convert` endpoint, polls for completion, retrieves results. MarkFlow handles all OCR and conversion logic.
- **Shared filesystem**: If both apps run on the same machine, UnionCore could write files to a directory that MarkFlow watches, or simply point to MarkFlow's output directory to pick up converted files.
- **Embedded library**: If tighter coupling is needed, MarkFlow's `core/` and `formats/` modules could be imported directly as Python packages (no HTTP layer). This requires both apps to be Python.

### What MarkFlow does NOT handle

- User authentication or permissions — it trusts whoever can reach the API
- Database storage — everything is filesystem-based (no SQL, no ORM)
- Document versioning — it converts files, it doesn't track version history
- Search or indexing of converted content
- Workflow orchestration — it's a tool, not a pipeline manager

### Questions for the integration conversation

1. **What role would document conversion play in UnionCore?** (e.g., normalizing uploaded documents to a standard format for indexing/search, generating printable outputs from stored data, OCR-ing scanned intake forms)
2. **Does UnionCore need the round-trip capability**, or just one-direction conversion (originals → markdown for storage/processing)?
3. **Where would converted files live?** MarkFlow defaults to local filesystem — if UnionCore uses a database or object storage, someone needs to bridge that gap.
4. **Does the OCR review workflow need to be embedded in UnionCore's UI**, or is it acceptable for users to be redirected to MarkFlow's review page for flagged items?
5. **What's the expected volume?** MarkFlow is built for small-to-medium batch sizes (dozens of files). If UnionCore needs to process hundreds or thousands of documents, MarkFlow's architecture would need a proper task queue (Celery/Redis) instead of in-process background tasks.
6. **Deployment**: Will both apps run on the same machine, or separate? Same Python environment, or containerized separately?

---

## Current Status

MarkFlow is in the **pre-build / prompt-complete** stage. A detailed Claude Code build prompt exists covering the full spec, phased build plan, and project structure. No code has been written yet. The build is estimated at 3-4 Claude Code sessions.

Integration architecture decisions should ideally be made **before** the build starts, since choices like "embedded library vs. HTTP service" and "filesystem vs. database storage" affect the core design.
