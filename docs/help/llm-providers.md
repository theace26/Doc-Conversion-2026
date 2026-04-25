# LLM Providers

MarkFlow can use an AI language model to improve conversion quality. This is
entirely optional -- conversions work without it -- but when enabled, AI can
correct garbled OCR text, generate document summaries, infer headings in PDFs
that lack font data, and describe video keyframes.

This article covers adding a provider, verifying the connection, activating
it, and understanding what each enhancement does.

---

## Supported Providers

| Provider | Display Name | Requires API Key | Models |
|----------|-------------|-----------------|--------|
| **Anthropic** | Claude (Anthropic) | Yes | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001 |
| **OpenAI** | OpenAI | Yes | gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo |
| **Gemini** | Gemini (Google) | Yes | gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash |
| **Ollama** | Ollama (Local) | No | Any model you have pulled locally |
| **Custom** | Custom (OpenAI-compatible) | Optional | You specify the model name manually |

> **Tip:** If you want to keep everything on-premises with no external API
> calls, use **Ollama**. It runs models locally on your own hardware. No API
> key is needed -- just install Ollama and pull a model.

---

## Adding a Provider

1. Go to the **Settings** page.
2. In the **AI Enhancement** section, click **Manage Providers**.
3. On the Providers page, click **Add Provider**.
4. Select a provider type from the dropdown.
5. Fill in the fields:
   - **Name** -- a friendly label (e.g., "Production Claude" or "Local Ollama")
   - **Model** -- pick from the dropdown or type a custom model name
   - **API Key** -- your secret key (cloud providers only)
   - **Base URL** -- pre-filled for known providers; override if using a proxy
6. Click **Save**.

Your API key is encrypted before being stored in the database. It is never
logged or exposed in API responses after creation.

> **Warning:** You must set the `SECRET_KEY` environment variable before
> adding any provider. If `SECRET_KEY` is not set, the app will refuse to
> encrypt API keys and provider creation will fail. Generate one with:
> `python -c "import secrets; print(secrets.token_hex(32))"`

### Where to Get API Keys

| Provider | Where to Create a Key |
|----------|----------------------|
| Anthropic | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) |
| OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Gemini | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| Ollama | No key needed -- [ollama.com/download](https://ollama.com/download) |

---

## Verifying a Connection

After adding a provider, click the **Verify** button next to it on the
Providers page. MarkFlow sends a tiny test request to the provider's API
and reports the result.

- A green checkmark means the provider responded successfully.
- The response time is shown (e.g., "claude-sonnet-4-6 responded in 320ms").
- A red indicator means something went wrong -- hover or click for the error
  message.

Common verification failures:

| Error | Cause | Fix |
|-------|-------|-----|
| "Invalid API key" | Key is wrong, expired, or revoked | Regenerate the key at the provider's console |
| "Cannot connect to Ollama" | Ollama server is not running | Start Ollama: `ollama serve` |
| "Model not found" | The model name does not match an available model | Check the model name; for Ollama, run `ollama pull <model>` |
| "Rate limited" | Provider returned 429 | Wait a moment and try again -- your key is valid |

> **Tip:** Verification does not test vision capabilities specifically. It
> sends a simple text prompt. If you need vision (Level 3 frame descriptions),
> make sure you chose a model that supports image input.

---

## Activating a Provider

You can have multiple providers saved, but only **one is active** at a time.
The active provider is the one MarkFlow uses for all AI enhancement tasks.

To activate a provider:

- On the **Providers** page, click **Activate** next to the desired provider.
- Or on the **Settings** page, use the **Active Provider** dropdown in the
  AI Enhancement section.

Changing the active provider takes effect immediately. Any conversions
currently in progress will continue using the old provider; new conversions
will use the new one.

Setting the dropdown to "None (AI disabled)" deactivates AI enhancement
entirely. All three enhancement toggles are ignored when no provider is
active.

---

## What Enhancement Does

AI enhancement is controlled by three independent toggles on the Settings
page. Each can be turned on or off separately.

### OCR Text Correction

**Setting:** "Use LLM to correct low-confidence OCR text"
**Default:** Off

When enabled, MarkFlow sends OCR output that scored below the confidence
threshold to the LLM for cleanup. The LLM fixes spelling errors, garbled
words, and formatting artifacts while preserving the document's structure
and formatting markers.

This is especially useful for:

- Scanned documents with poor image quality
- Documents with unusual fonts or handwritten annotations
- Historical or degraded source material

The LLM sees only the OCR text, not the original image. It returns corrected
text that replaces the raw OCR output in the final Markdown.

> **Tip:** OCR correction adds processing time and API costs per page. For
> large bulk jobs with thousands of pages, consider enabling it only for
> documents you know have OCR quality issues.

### Document Summaries

**Setting:** "Generate document summaries"
**Default:** Off

When enabled, MarkFlow sends the first ~8,000 characters of each converted
document to the LLM and asks for a 2-3 sentence summary. The summary is
stored in the conversion history and included in the Meilisearch index.

Summaries are useful for:

- Quick document triage without opening each file
- Search result previews
- AI assistant context (Claude can read summaries via MCP)

### Heading Inference

**Setting:** "Use LLM to infer headings in PDFs"
**Default:** Off

Some PDFs lack embedded font size data, making it impossible to detect
headings by normal means. When this toggle is on, MarkFlow sends blocks
of text to the LLM and asks it to identify which blocks should be headings
and at what level (H1 through H4).

This produces much better Markdown structure for:

- PDFs created by older or minimal PDF generators
- PDFs where all text is the same font size
- Scanned documents converted to "searchable PDF" without structure tags

> **Warning:** Heading inference processes up to 100 text blocks per
> document. Very long documents may have some sections without inferred
> headings if they fall beyond this limit.

---

## Vision Capabilities

The active LLM provider is also used for **vision** tasks -- specifically,
describing keyframes extracted from video files during visual enrichment
(see Settings > Vision & Frame Description).

Vision support by provider:

| Provider | Vision Support |
|----------|---------------|
| Anthropic | Yes -- all Claude models with vision |
| OpenAI | Yes -- GPT-4o and GPT-4-turbo |
| Gemini | Yes -- all Gemini models |
| Ollama | Yes -- models like LLaVA that support images |
| Custom | No -- API shape for image input is unknown |

Vision uses the **same provider and model** configured in the AI Enhancement
section. There is no separate vision provider setting. If you want Level 3
visual enrichment (AI frame descriptions), make sure your active provider
supports image input.

The Settings page shows the active vision provider in the **Vision & Frame
Description** section with a link to manage providers if none is configured.

---

## Multiple Providers

You can save multiple providers and switch between them as needed. Common
setups:

- **Cloud + Local fallback:** Keep a Claude or GPT-4o provider for high-quality
  results, and an Ollama provider as a backup when the cloud API is down or
  rate-limited.
- **Cost tiers:** Use GPT-4o-mini for routine summaries (cheaper) and switch
  to Claude or GPT-4o when you need higher-quality OCR correction.
- **Testing:** Add a new provider, verify it, and activate it for a test batch
  without deleting your production provider.

Only the active provider is used. Inactive providers sit idle and incur no
API costs.

> **Token tracking:** Every LLM vision call records the token count in the
> `analysis_queue` table. You can query aggregate usage (total tokens, average
> per file, breakdown by model) via `get_analysis_token_summary()` in
> `core/db/analysis.py`. This helps monitor costs when processing large image
> collections.

---

## Ollama Setup

Ollama runs models locally. To use it with MarkFlow:

1. Install Ollama from [ollama.com/download](https://ollama.com/download).
2. Pull a model: `ollama pull llama3` (or any model you prefer).
3. Make sure Ollama is running: `ollama serve`.
4. In MarkFlow, add a provider with type "Ollama" and base URL
   `http://host.docker.internal:11434` (this lets the Docker container
   reach Ollama on your host machine).
5. MarkFlow will auto-detect available models when you verify the connection.

For vision tasks, pull a vision-capable model like `llava`:
`ollama pull llava`.

> **Tip:** Ollama performance depends on your hardware. Models run on CPU
> unless you have a GPU with enough VRAM. Smaller models (7B parameters)
> are faster; larger models (70B) produce better results but require more
> memory and time.

---

## Custom Provider

The "Custom" provider type supports any API that is compatible with the
OpenAI chat completions format (`POST /v1/chat/completions`). This includes:

- LM Studio
- vLLM
- text-generation-inference (TGI)
- Any OpenAI-compatible proxy

Enter the base URL (e.g., `http://localhost:1234`) and optionally an API key.
The model name must match what the server expects.

> **Warning:** Custom providers do not support vision (image input). If you
> need Level 3 frame descriptions, use one of the named providers instead.

---

## Resilience and reliability (v0.31.2)

MarkFlow's vision-API code path defends against provider
flakiness, transient outages, and bad input files using a
five-layer pipeline. Every layer applies to **all four
providers** (Anthropic, OpenAI, Gemini, Ollama) regardless
of which one is active.

### The five layers

| Layer | What it does | When it fires |
|---|---|---|
| 1. Pre-flight | PIL header verify + dimension sanity check + MIME allow-list, all locally before encoding to base64 | Always, on every image |
| 2. Exponential backoff | Up to 4 retries with delays of 1, 2, 4, 8 s (jittered ±15%); honors `Retry-After` header when present | On 429, 500, 502, 503, 504, 529 |
| 3. Per-image bisection | Halves the failing batch and retries each half until the bad image is in a solo sub-batch | On 400 (payload error) |
| 4. Circuit breaker | Process-wide state machine; opens after 5 consecutive upstream failures, cooldown 60s → 2min → 4min → 8min → cap 15min | When upstream is genuinely broken |
| 5. Operator banner | Red banner on Batch Management when breaker is open, with cooldown countdown + Reset button | When the breaker is open or half-open |

### Example: one bad image in a batch of 10

Before v0.29.9 (Anthropic) / v0.31.2 (others):

```
Batch of 10 images → POST → HTTP 400 "image at index 4 is corrupt"
Result: all 10 rows marked failed
```

After:

```
Batch of 10 images → POST → HTTP 400
  └── Bisect: left half (5 images) → POST → 200 OK ✓
  └── Bisect: right half (5 images) → POST → HTTP 400
        └── Bisect: 2 images → POST → 200 OK ✓
        └── Bisect: 3 images → POST → HTTP 400
              └── Bisect: 1 image → POST → 200 OK ✓
              └── Bisect: 2 images → POST → HTTP 400
                    └── Bisect: 1 image → POST → HTTP 400
                          ✗ Isolated! Mark this one failed.
                    └── Bisect: 1 image → POST → 200 OK ✓
Result: 9 of 10 rows succeed, 1 row marked with the actual 400
        body so you can see what was wrong with that file.
```

The worst case is `~2 N` extra calls for one bad file in a
batch of N. The cost is real, but you save the cost of failing
the other N − 1 files plus the operator's time.

### Example: provider outage

```
Batch 1 → POST → 503 → backoff 1s → POST → 503 → backoff 2s → POST → 503 → backoff 4s → POST → 503 → backoff 8s → POST → 503 → mark all failed (after 4 attempts)
   (4 retries x 5 = 1 cumulative breaker failure)
Batch 2 → POST → 503 → ... (same pattern, 1 more breaker failure)
Batch 3 → ...
Batch 4 → ...
Batch 5 → After 5 consecutive upstream failures, breaker OPENS.
Batch 6 → CIRCUIT OPEN → instant fail without any API call.
   (saves money — no doomed calls go out)
   ... 60 second cooldown ...
Batch 7 → CIRCUIT HALF-OPEN → one trial call permitted.
   If success: breaker closes, normal traffic resumes.
   If failure: breaker re-opens with 120s cooldown.
```

### Where to see it

- **Batch Management page** (`/batch-management.html`) — when
  the breaker opens, a red/amber banner appears above the top
  bar with the error class, consecutive-failure count,
  countdown to next trial, and a **Reset breaker** button
  (Manager+ role required).
- **API endpoint** — `GET /api/analysis/circuit-breaker`
  returns the breaker's current state as JSON. Useful for
  monitoring scripts.
- **Logs** — search the operational log for
  `vision_circuit_breaker.opened` / `closed` / `half_open` to
  see breaker transitions.

### What the breaker does NOT count

Only **upstream** failures count toward the breaker threshold:

- ✓ HTTP 429, 500, 502, 503, 504, 529
- ✓ network errors, timeouts, connection refused

Specifically NOT counted:

- ✗ HTTP 400 (payload error — feeds bisection instead)
- ✗ Pre-flight failures (corrupt local file)
- ✗ Auth errors (401/403 — these still mark all rows failed
  but don't trip the breaker, because you don't want a single
  invalid-key incident to block all traffic during the
  rotation window)

This means a single bad file in a giant batch can never trip
the breaker — bisection will isolate it cleanly.

### Cross-provider note

The breaker is **process-wide**. If you're mid-experiment
switching from one provider to another, the first call to the
new provider may short-circuit if the breaker is still cooling
down from the old provider. Click **Reset breaker** on the
banner to bypass the cooldown immediately, or wait it out (60s
the first time, doubling on each re-trigger up to 15 minutes).

---

## Security Notes

- API keys are encrypted at rest using Fernet symmetric encryption.
- The `SECRET_KEY` environment variable is required for encryption.
- Keys are never returned in API responses after creation.
- Keys are never written to log files.
- If you need to rotate a key, delete the provider and re-add it with the
  new key.

---

## Related

- [Settings Guide](/help.html#settings-guide) -- all AI and vision settings with defaults
- [GPU Setup](/help.html#gpu-setup) -- GPU acceleration for password cracking (separate from LLM)
- [Adobe Files](/help.html#adobe-files) -- how AI search enhancement applies to indexed files
