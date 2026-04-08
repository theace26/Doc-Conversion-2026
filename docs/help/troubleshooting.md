# Troubleshooting

This guide covers the most common issues you might run into with MarkFlow
and how to resolve them. Start with the symptom that matches your situation
and follow the steps.

---

## Diagnostic Tools

Before diving into specific issues, know where to look for information:

### Health Endpoint

The fastest way to check if MarkFlow is running:

```
http://<your-server>:8000/api/health
```

This returns the status of every component: database, Tesseract, LibreOffice,
Poppler, WeasyPrint, disk space, Meilisearch, and mounted drives. If any
component shows `"ok": false`, the problem area is identified immediately.

> **Tip:** The health endpoint does not require authentication. You can check
> it from a browser, curl, or a monitoring tool without logging in.

### Debug Dashboard

Visit `/debug` in your browser. This always-available developer page shows
health pills for each dependency, recent conversion activity, OCR confidence
distribution, and a real-time log viewer.

### Container Logs

The most detailed information lives in the container logs:

```bash
docker compose logs -f app           # live tail
docker compose logs app --tail 200   # last 200 lines
docker compose logs app | grep -i "error"  # filter errors
```

### Log File Downloads

Managers can download log files from **Settings > Logging**:

| File | Contents | Retention |
|------|----------|-----------|
| `markflow.log` | Operational log (always active) | 30 days |
| `markflow-debug.log` | Debug trace (developer mode only) | 7 days |

---

## Container Won't Start

**Symptom:** `docker compose up` fails or the container exits immediately.

**Check for port conflicts.** MarkFlow uses ports 8000, 8001, and 7700. If
another application occupies one of these, the container cannot bind. Stop
the conflicting application or remap ports in `docker-compose.yml`.

**Check environment variables.** These are required in specific situations:

| Variable | Required When |
|----------|---------------|
| `SECRET_KEY` | An LLM provider is configured |
| `API_KEY_SALT` | You need to generate API keys |
| `UNIONCORE_JWT_SECRET` | Running in production auth mode |

In development, `DEV_BYPASS_AUTH=true` (the default) means you do not
need auth-related variables.

**Check volume mounts.** If the container starts but cannot access files,
verify Docker volumes point to the correct host directories:

```bash
docker volume ls | grep markflow
```

---

## Conversion Fails

**Symptom:** A file uploads but the conversion returns an error.

**Check the file format.** Supported formats are `.docx`, `.pdf`, `.pptx`,
`.xlsx`, `.csv`, and `.tsv`. Old `.doc` files need to be converted to
`.docx` first.

**Check for password protection.** Encrypted documents cannot be converted.
See [Password-Protected Documents](/help#password-recovery) for workarounds.

**Read the error message.** The History page shows the specific failure:

| Error Pattern | Likely Cause |
|---------------|-------------|
| "Unsupported format" | Extension not in the handler registry |
| "zip bomb detected" | File failed the decompression safety check |
| "LibreOffice not found" | Dependency missing in the container |
| "Tesseract not found" | OCR needed but Tesseract unavailable |

---

## Audio or Video Transcription Fails

**Symptom:** An MP3, WAV, MP4, or other media file uploads but the conversion
returns an error mentioning transcription, Whisper, or "no cloud provider."

MarkFlow transcribes media files using a three-step fallback chain:
**caption file → local Whisper → cloud provider**. If all three fail, the
conversion is marked as an error. Here is how to diagnose each step.

**Error: "No cloud provider configured that supports audio transcription"**

This means local Whisper failed (or is unavailable) and none of your
configured AI providers can handle audio. Note that **Anthropic / Claude
does not currently support audio transcription** — only OpenAI (Whisper API)
and Google Gemini do. If you only have an Anthropic key configured, the
fallback chain has nothing to fall back *to*.

Fix: In **Settings > AI Providers**, add an API key for OpenAI or Gemini.
Even a free-tier Gemini key works. Alternatively, make sure local Whisper is
functioning (see next section).

**Whisper is running but transcription is extremely slow**

Check whether Whisper is running on GPU. Visit `/api/health` and look for
the `whisper` section:

```json
"whisper": { "cuda_available": true, "gpu_name": "NVIDIA ..." }
```

If `cuda_available` is `false` on a machine that has an NVIDIA GPU, Whisper
is stuck on CPU — a 75-minute audio file can take many hours on CPU with
the `medium` model, versus 10-15 minutes on GPU. Two things must be true:

1. The **NVIDIA Container Toolkit** must be installed inside WSL2 (not just
   Windows). Smoke test from your terminal:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
   ```
   If this does not list your GPU, fix the toolkit installation first.
2. The `markflow` service in `docker-compose.yml` must have the
   `deploy.resources.reservations.devices` block requesting an NVIDIA GPU.
   This ships enabled by default; if you commented it out for a CPU-only
   deployment, uncomment it on the GPU host.

**Whisper fails with a "tensor reshape" or "cannot reshape" error**

The audio file is corrupt or has zero decodable frames. Re-encode the file
to a clean MP3 or WAV using ffmpeg:

```bash
ffmpeg -i broken.mp3 -c:a libmp3lame -b:a 128k fixed.mp3
```

Then retry the conversion. If the re-encoded file also fails, the source
media is unrecoverable.

**Whisper model preference is wrong for your hardware**

In **Settings > Transcription**, pick a Whisper model size based on your
hardware:

| Model | VRAM (GPU) | RAM (CPU) | Speed | Accuracy |
|-------|-----------|-----------|-------|----------|
| `tiny` | ~1 GB | ~1 GB | Very fast | Rough |
| `base` | ~1 GB | ~1 GB | Fast | Good |
| `small` | ~2 GB | ~2 GB | Medium | Better |
| `medium` | ~5 GB | ~5 GB | Slow | Very good |
| `large` | ~10 GB | ~10 GB | Very slow | Best |

A GTX 1660 Ti (6 GB VRAM) handles `medium` comfortably; `large` needs a
higher-end card.

---

## Search Not Working

**Symptom:** The search page shows "Search index offline" or returns no
results for documents you know exist.

**Check Meilisearch status.** Visit the health endpoint or debug dashboard.
If Meilisearch shows "unavailable":

```bash
docker compose logs meilisearch
docker compose up -d meilisearch    # restart if needed
```

**Documents converted but not appearing?** Check the Admin page Search Index
card. Only successfully converted files are indexed. After a bulk job, allow
a few moments for indexing to complete. If documents still do not appear,
trigger a search index rebuild.

> **Tip:** If you renamed a file and reconverted it, the old index entry
> persists alongside the new one. A full index rebuild cleans this up.

---

## OCR Quality Is Poor

**Symptom:** Converted PDFs have garbled text or many low-confidence flags.

**Check the source quality.** OCR accuracy depends on the input:

| Source Quality | Expected Accuracy |
|----------------|-------------------|
| Clean digital PDF (text layer) | No OCR needed |
| 300 DPI scan, clean text | 95%+ |
| 150 DPI scan or fax | 80--90% |
| Photo of a document | 60--80% |
| Handwritten text | Very poor |

**Adjust OCR settings** in Settings: raise the confidence threshold to flag
more questionable results, or set OCR mode to `force` if a PDF has an
unreliable text layer.

**Enable LLM correction.** If you have an [LLM provider](/help#llm-providers)
configured, turn on the OCR correction toggle for AI-powered cleanup of
common OCR mistakes.

**Review flagged pages** on the [OCR Review page](/review.html), which shows
the original image side by side with the extracted text.

---

## Bulk Job Is Stuck

**Symptom:** A bulk job shows "running" but progress has not moved.

1. Go to the [Status page](/status.html) and check the job card. If a
   worker's filename is not changing, a single file may be hanging.
2. Click **Stop** on the job (or **STOP ALL**). Wait for workers to finish
   their current file -- stopping is cooperative, not instant.
3. Click **Reset Stop Flag** on the Admin page.
4. Start a new bulk job. Already-converted files will be skipped.

> **Warning:** Do not force-kill the container to stop a stuck job. This can
> corrupt the SQLite write-ahead log. Always use the Stop controls.

**Check disk space.** If the output volume is full, conversions fail
silently. Check the [Admin disk usage section](/help#admin-tools).

---

## Authentication Issues

**Symptom:** Pages load but show no data, or API calls return 401/403.

**In development:** Make sure `DEV_BYPASS_AUTH: "true"` is in your
`docker-compose.yml`. With bypass enabled, all requests are treated as Admin.

**In production:** You need either a valid JWT from UnionCore or an API key
(`X-API-Key: mf_...`). If tokens are rejected, verify `UNIONCORE_JWT_SECRET`
matches between MarkFlow and UnionCore.

**Role restrictions** may also be the cause:

| Page | Minimum Role |
|------|-------------|
| Search | `search_user` |
| Convert, History | `operator` |
| Bulk Jobs, Trash, Resources, Settings | `manager` |
| Admin | `admin` |

---

## MCP Connection Fails

**Symptom:** Claude.ai cannot connect to MarkFlow's MCP server.

Verify the server is running with `docker compose logs mcp`. The MCP server
listens on port 8001. Test with `curl http://localhost:8001/sse` -- an SSE
connection should open and hang (that is normal).

If `MCP_AUTH_TOKEN` is set, Claude must send the same token. If you are
behind a firewall, ensure port 8001 is reachable from Claude.ai's backend.

---

## Stale Docker Volumes

**Symptom:** After rebuilding, old data persists or new data goes to the
wrong location.

Docker volumes survive `docker compose down`. If you changed volume names
or paths in `docker-compose.yml`, old volumes still exist:

```bash
docker volume ls | grep markflow
```

To start completely fresh (deletes all data):

```bash
docker compose down -v && docker compose up -d
```

> **Warning:** The `-v` flag removes all named volumes, permanently deleting
> the database, converted files, and search index. Only use it if you truly
> want a clean start.

---

## Quick Reference: First Things to Check

When something goes wrong, check these in order:

1. **Health endpoint** -- `http://localhost:8000/api/health`
2. **Container logs** -- `docker compose logs -f app`
3. **Debug dashboard** -- `http://localhost:8000/debug`
4. **Admin stats** -- Repository Overview and Recent Errors table
5. **Disk space** -- Admin page Disk Usage section

---

## Related Articles

- [Administration](/help#admin-tools) -- database tools and disk usage
- [Status & Active Jobs](/help#status-page) -- monitoring and stopping jobs
- [Resources & Monitoring](/help#resources-monitoring) -- system metrics
- [Settings Reference](/help#settings-guide) -- adjusting thresholds
