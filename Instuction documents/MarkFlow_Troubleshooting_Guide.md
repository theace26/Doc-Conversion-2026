# MarkFlow — Troubleshooting & Debug Guide

A reference for diagnosing and fixing issues in MarkFlow. Organized by symptom — find what's broken, follow the steps.

---

## Quick Reference: Debug Mode

Start MarkFlow in debug mode to get verbose logging and intermediate files:

```bash
DEBUG=true uvicorn main:app --reload
```

This enables:
- `DEBUG`-level log output
- Intermediate file preservation in `output/<batch_id>/_debug/`
- Debug dashboard at `http://localhost:8000/debug`
- Extra response headers (`X-MarkFlow-Request-Id`, `X-MarkFlow-Duration-Ms`, etc.)

**Always start here.** Most issues become obvious once you can see the pipeline internals.

---

## 1. Conversion Failures

### Symptom: File uploads but conversion produces empty or corrupt output

**Check in order:**

1. **Look at the manifest:** `output/<batch_id>/manifest.json` — check the file's `status` field. If it says `error`, the `error_message` field will have details.

2. **Check the raw extraction (debug mode):** Open `output/<batch_id>/_debug/<filename>.raw_extract.txt`. If this is empty, the problem is in the format handler (extraction stage), not the markdown generator. If this has content but the `.md` is wrong, the problem is in markdown conversion.

3. **Check the style sidecar:** Open `<filename>.styles.debug.json` (the verbose version). If fields are `null` or missing, the style extractor couldn't read the source formatting — this will cause round-trip fidelity issues but shouldn't cause conversion failure.

4. **Check logs for the specific file:**
   ```bash
   grep "<filename>" logs/markflow.log | grep "ERROR\|WARNING"
   ```
   Or use the debug dashboard log viewer, filtered by batch ID.

**Common causes:**

| Symptom | Likely Cause | Fix |
|---|---|---|
| `.docx` extraction fails | Password-protected or corrupted `.docx` | Try opening in Word first — if Word can't open it, MarkFlow can't either |
| `.doc` (legacy) fails | LibreOffice not installed or not in PATH | Run `libreoffice --version` — if not found, install it |
| PDF extraction returns gibberish | PDF uses non-standard encoding or custom fonts | Check `raw_extract.txt` — if gibberish, try forcing OCR mode for that file |
| `.pptx` missing slide content | Content is in grouped shapes or SmartArt | `python-pptx` can't extract from grouped shapes — known limitation, flag for manual review |
| `.xlsx` missing data | Data is in named ranges or pivot tables, not cells | `openpyxl` reads cell values — pivot tables and named ranges need special handling |

### Symptom: Round-trip produces different formatting

This is the hardest category. The file converts to `.md` and back, but the result looks different.

1. **Check the round-trip diff (debug mode):** Open `<filename>.round_trip_diff.txt` — this shows structural differences (heading count, table dimensions, image count, paragraph count).

2. **Compare style sidecars:** Open both the original `<filename>.styles.json` and see if the fields look populated. Common gaps:
   - Missing font families → export uses defaults
   - Missing table column widths → export uses auto-width
   - Missing image dimensions → images may resize

3. **Check the markdown intermediate:** Open the `.md` file. Is the content structurally correct? If the markdown looks right but the export looks wrong, the problem is in the export handler. If the markdown is already missing structure, the problem is in the ingest handler.

**The pipeline inspector on the debug dashboard is the fastest way to trace this.** Click through each stage and compare input vs. output.

---

## 2. OCR Pipeline Issues

### Symptom: OCR produces bad text

1. **Check preprocessing (debug mode):** Compare `<filename>.ocr_preprocess.png` against the original image. If the preprocessed image looks worse (over-thresholded, lost detail), the preprocessing parameters need tuning.

2. **Check raw OCR output:** Open `<filename>.ocr_raw.txt` — this is what Tesseract returned before any confidence filtering. If this is bad, the problem is either the image quality or Tesseract configuration.

3. **Check Tesseract PSM mode:** Different page segmentation modes work better for different layouts:
   - `--psm 6` (default): Assumes a single uniform block of text
   - `--psm 3`: Fully automatic segmentation — better for mixed layouts
   - `--psm 4`: Column-based text
   - `--psm 11`: Sparse text (labels on a diagram, for example)
   
   If the document has unusual layout, try a different PSM.

4. **Check the HOCR output (debug mode):** Open `<filename>.ocr_hocr.html` in a browser. This shows bounding boxes around every detected word — if Tesseract is merging or splitting words incorrectly, you'll see it visually.

**Common OCR causes:**

| Symptom | Likely Cause | Fix |
|---|---|---|
| Most words are wrong | Image resolution too low (< 200 DPI) | Upscale image before OCR, or flag as unconvertible |
| Words are merged together | Tesseract PSM mode wrong for layout | Try `--psm 3` or `--psm 4` |
| Special characters mangled | Tesseract language pack missing | Install `tesseract-ocr-[lang]` for the document's language |
| Tables come through as garbled text | Tesseract doesn't understand table structure | Extract table regions separately, OCR each cell — this is a known hard problem |
| Confidence scores are all high but text is wrong | Confidence scoring isn't reliable for all fonts | Visual review is the fallback — this is why the interactive review exists |

### Symptom: OCR review UI shows no flagged items but output has errors

The confidence threshold (default 80%) may be too low for the document's font or scan quality. Tesseract can be confidently wrong.

**Workaround:** Lower the threshold temporarily. Add a query parameter or config option:
```
POST /api/convert?ocr_confidence_threshold=90
```

### Symptom: OCR is extremely slow

- Check image resolution — OCR on a 600 DPI full-page scan is significantly slower than 300 DPI
- Check page count — for large PDFs, verify pages are being processed sequentially with progress updates, not loaded all at once
- Check Tesseract engine mode — `--oem 3` (default) uses the LSTM engine which is more accurate but slower. `--oem 0` uses legacy engine, faster but less accurate

---

## 3. UI Issues

### Symptom: Upload not working (nothing happens when clicking Convert)

1. **Open browser dev tools (F12) → Console tab.** Look for JavaScript errors. Common ones:
   - `Failed to fetch` — backend isn't running or CORS issue
   - `TypeError` — JavaScript bug in the upload handler

2. **Check the Network tab.** Is the request being sent? If yes, what's the response?
   - `422 Unprocessable Entity` — FastAPI validation error. The request body doesn't match the Pydantic model. Check the response body for details.
   - `500 Internal Server Error` — backend crash. Check `logs/markflow.log`.
   - No request at all — the frontend JavaScript isn't firing. Check for missing event listeners.

3. **Test the endpoint directly via Swagger:** Go to `http://localhost:8000/docs`, find the `/api/convert` endpoint, and try uploading there. If it works in Swagger but not in the UI, the problem is 100% frontend.

### Symptom: OCR review page not loading or broken layout

1. **Check if there are actually flagged items:** Hit `GET /api/batch/{batch_id}/review` directly (via Swagger or curl). If it returns an empty list, there's nothing to review — the UI should show "no items to review" but might be handling the empty state wrong.

2. **Check if images are loading:** The review UI shows cropped images of flagged regions. If images show as broken, the image extraction or serving path is wrong. Check that the debug images exist in the output directory and that the static file serving is configured to serve from there.

3. **Check the Accept All flow:** "Accept All Remaining" should POST to `/api/batch/{batch_id}/review/accept-all` and then redirect to results. If it hangs, check if the endpoint is actually processing or if it's stuck in a loop.

### Symptom: Batch progress not updating

The progress UI polls the status endpoint. If it's stuck:

1. **Check if the batch is actually processing:** `GET /api/batch/{batch_id}/status` — is the status changing? If stuck on "processing" for a long time, a file may be hanging the pipeline.

2. **Check logs for the stuck file:** Filter logs by batch ID and look for the last file that started processing. If it's a large PDF or a problematic file, it may be blocking.

3. **Check if it's a polling issue:** The UI uses `setInterval` or similar to poll status. If the endpoint returns correctly in Swagger but the UI doesn't update, the problem is in the frontend polling JavaScript.

---

## 4. API Issues

### Symptom: Endpoint returns 500 Internal Server Error

1. **Check logs immediately.** The traceback will be in `logs/markflow.log` and in the terminal output. FastAPI logs the full Python traceback on 500 errors.

2. **Check the request ID:** If debug mode is on, the response header `X-MarkFlow-Request-Id` lets you grep for the exact request in logs:
   ```bash
   grep "request_id=<the-id>" logs/markflow.log
   ```

3. **Common 500 causes:**

| Error in traceback | Cause | Fix |
|---|---|---|
| `FileNotFoundError` | Output directory doesn't exist or file was cleaned up | Ensure `output/` exists and batch directories aren't being deleted prematurely |
| `tesseract is not installed or not in PATH` | Tesseract binary not found | Install `tesseract-ocr` and verify with `tesseract --version` |
| `KeyError` in style extractor | Document has unexpected structure | Add defensive checks — not all `.docx` files have all style properties |
| `PermissionError` | File locked by another process or OS permissions | Close the file in other apps, check directory permissions |

### Symptom: Batch job hangs (never completes)

1. **Check which file is stuck:** `GET /api/batch/{batch_id}/status` — look for files still in "processing" state.

2. **Check if it's a subprocess hang:** LibreOffice (for `.doc` conversion) and Tesseract can hang on certain inputs. If logs show a subprocess started but never completed, it may need a timeout.

3. **Kill stuck processes:**
   ```bash
   # Find hanging processes
   ps aux | grep -E "tesseract|soffice"
   # Kill if necessary
   kill <pid>
   ```

4. **Add timeouts:** Each subprocess call (Tesseract, LibreOffice) should have a timeout. If the build didn't add them, wrap in:
   ```python
   subprocess.run([...], timeout=120)  # 2 minute timeout
   ```

### Symptom: Endpoint returns 422 Validation Error

This means the request doesn't match FastAPI's expected schema. The response body will tell you exactly what's wrong:

```json
{
  "detail": [
    {
      "loc": ["body", "direction"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Fix:** Check the Swagger docs at `/docs` for the correct request format. The Pydantic models define exactly what fields are required and what types they need to be.

---

## 5. System-Level Issues

### Tesseract not working

```bash
# Verify installation
tesseract --version

# Verify it can process an image
tesseract test_image.png output_text

# Check available languages
tesseract --list-langs
```

If Tesseract works from the command line but not from Python, `pytesseract` can't find the binary. Set explicitly:
```python
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # Linux
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Windows
```

### LibreOffice not working (for .doc conversion)

```bash
# Verify installation
libreoffice --version

# Test headless conversion
libreoffice --headless --convert-to docx test.doc --outdir /tmp
```

LibreOffice locks a user profile when running — if you get profile lock errors, another instance is running. Kill it or use a custom profile:
```bash
libreoffice --headless -env:UserInstallation=file:///tmp/libreoffice_profile --convert-to docx test.doc
```

### Disk space

Intermediate debug files can accumulate fast, especially with OCR on large PDFs.

```bash
# Check output directory size
du -sh output/

# Clear old debug files (keep manifests and converted files)
find output/ -path '*/_debug/*' -mtime +7 -delete
```

---

## 6. Debug Workflow Cheat Sheet

**Something broke. What do I do?**

```
1. Is debug mode on?
   NO  → Restart with DEBUG=true, reproduce the issue
   YES → Continue

2. Is it an API error?
   YES → Check terminal output for traceback
       → Check response body for error details
       → Test endpoint in Swagger (/docs) to isolate frontend vs. backend
   NO  → Continue

3. Is it a conversion quality issue?
   YES → Open debug dashboard (/debug)
       → Find the file in recent conversions
       → Click through pipeline inspector stage by stage
       → Compare intermediate outputs to find where quality degraded
   NO  → Continue

4. Is it an OCR issue?
   YES → Check ocr_preprocess.png — is preprocessing helping or hurting?
       → Check ocr_confidence.json — are confidence scores matching reality?
       → Check ocr_hocr.html — are bounding boxes correct?
       → Try different PSM mode
   NO  → Continue

5. Is it a UI issue?
   YES → Open browser dev tools (F12)
       → Console for JS errors
       → Network tab for failed/missing requests
       → Test the same endpoint in Swagger to isolate frontend vs. backend
   NO  → Continue

6. Is it hanging/slow?
   YES → Check logs for last activity
       → Check for hung subprocesses (tesseract, soffice)
       → Check disk space
       → Add or reduce timeout values
```
