# OCR Pipeline

Some documents — especially scanned PDFs — contain pages that are images rather than selectable text. MarkFlow uses **OCR** (Optical Character Recognition) to read the text from those images so it can be included in the Markdown output. This article explains how OCR works in MarkFlow, what confidence scores mean, and how to review and correct results.


## What Is OCR?

OCR stands for Optical Character Recognition. It is the process of looking at an image of text and figuring out what the words say. Think of it as MarkFlow "reading" a photograph of a page the same way you would read it with your eyes.

OCR is necessary when a PDF was created by scanning a paper document. These scanned PDFs look like normal documents on screen, but the computer sees them as pictures — there is no actual text data inside the file. MarkFlow detects this situation and runs OCR automatically.

> **Tip:** If you can open a PDF and select or copy text with your mouse, it probably has real text and will not need OCR. If you cannot select text, the PDF is likely a scanned image.


## How Detection Works

MarkFlow uses multiple signals to decide whether a PDF page needs OCR:

| Signal                     | What it checks                                                |
|----------------------------|---------------------------------------------------------------|
| **Text layer presence**    | Does the page have any extractable text at all?               |
| **Text density**           | Is there enough text relative to the page size?               |
| **Character count**        | Are there too few characters for a page that should have text? |
| **Image coverage**         | Does a large image cover most of the page?                    |

If these signals indicate a page is mostly or entirely image-based, MarkFlow marks it for OCR processing. Pages with adequate selectable text skip OCR entirely.

> **Tip:** Detection happens per page, not per document. A 20-page PDF where only pages 5 and 6 are scanned will have OCR applied to just those two pages. The other 18 pages use their existing text.


## How OCR Processing Works

When a page is identified as needing OCR, MarkFlow follows these steps:

### Step 1: Preprocessing

Before reading the text, MarkFlow cleans up the page image to improve accuracy:

- **Deskewing** — Straightens pages that were scanned at a slight angle.
- **Contrast adjustment** — Makes text stand out more clearly against the background.
- **Noise reduction** — Removes speckles and artifacts from the scan.

### Step 2: Text Recognition

MarkFlow sends the cleaned-up image to its OCR engine (Tesseract), which identifies each word on the page along with its position and a confidence score.

### Step 3: Confidence Scoring

Every word gets a confidence score from 0 to 100, representing how certain the OCR engine is about its reading:

| Score range | Meaning                                              |
|-------------|------------------------------------------------------|
| 80 - 100    | High confidence — the word is almost certainly correct |
| 60 - 79     | Medium confidence — probably correct but worth checking |
| Below 60    | Low confidence — likely contains errors               |

MarkFlow calculates three summary scores for each page:

- **Mean confidence** — The average score across all words on the page.
- **Minimum confidence** — The lowest-scoring word on the page.
- **Pages below threshold** — How many pages have a mean score below your configured threshold.


## Confidence Scores in History

After conversion, every file that went through OCR shows confidence information in the History page. Look for colored badges next to the filename:

| Badge color | What it means                                     |
|-------------|---------------------------------------------------|
| **Green**   | High confidence — results look reliable            |
| **Yellow**  | Medium confidence — some words may need review     |
| **Red**     | Low confidence — significant portions may be wrong |

Click on any conversion in History to see detailed per-page confidence breakdowns.

> **Tip:** A red badge does not mean the conversion failed. It means some text may be inaccurate. You can still use the output — just be aware that some words might need manual correction.


## The Review Interface

When OCR produces low-confidence results, MarkFlow flags specific words and phrases for your review. The review interface lets you see exactly what the OCR engine read and correct any mistakes.

### Accessing Review

There are two ways to reach the review page:

1. **From the progress screen** — If MarkFlow detects low-confidence text during conversion, a banner appears with a link to review the flagged items.
2. **From History** — Open a conversion that has OCR flags and click the "Review OCR" link.

### Using the Review Page

The review page shows a side-by-side view:

| Left side                        | Right side                         |
|----------------------------------|------------------------------------|
| The original page image          | The recognized text (editable)     |

Flagged words are highlighted in the image and in the text. For each flag, you can:

- **Accept** — The OCR reading is correct; dismiss the flag.
- **Edit** — Type the correct text to replace the OCR result.
- **Accept All** — If you have reviewed enough and trust the remaining flags, accept everything at once.

> **Warning:** Accepting all flags without reviewing them means any OCR errors will be included in your Markdown output. This is fine for informal documents but risky for contracts, legal text, or anything where accuracy is critical.

### What Happens After Review

Once you resolve all flags for a file:

- The Markdown output is updated with your corrections.
- The flag status changes to "resolved" in the database.
- The file appears without the review banner in History.


## Unattended Mode

If you convert many scanned PDFs regularly and do not want to review every flag manually, you can enable **Unattended Mode** in Settings.

| Setting             | What it does                                                  |
|---------------------|---------------------------------------------------------------|
| **Unattended Mode** | Automatically accepts all OCR text without waiting for review |

When unattended mode is on:

- OCR still runs and confidence scores are still recorded.
- Low-confidence text is accepted automatically instead of being flagged.
- You can still see confidence badges in History to identify files that may have issues.
- No review banners appear during conversion.

> **Tip:** Unattended mode is great for large archival projects where you want to get everything converted quickly and only review files with very low confidence scores later.


## Bulk Skip-and-Review

When running a [Bulk Conversion](/help#bulk-conversion) job, MarkFlow offers a middle ground between stopping for every flag and accepting everything blindly.

### How It Works

During a bulk job, if a PDF's estimated OCR confidence falls below the threshold, MarkFlow **skips** that file into a review queue instead of failing it. The rest of the bulk job continues without interruption.

After the bulk job finishes, you can open the **Bulk Review** page to handle the skipped files:

| Action                | What it does                                                  |
|-----------------------|---------------------------------------------------------------|
| **Convert Anyway**    | Run the conversion despite low confidence                     |
| **Skip Permanently**  | Mark the file as permanently skipped — it will not be retried |
| **Open Review**       | Go to the per-page OCR review for that specific file          |

### The Review Queue

The bulk progress screen shows a count of files in the review queue. After the job completes, a link to the Bulk Review page appears.

On the Bulk Review page, each skipped file shows:

- The filename and path
- The estimated confidence score
- The reason it was skipped
- Action buttons (Convert Anyway, Skip Permanently, Open Review)

> **Tip:** You do not need to resolve the review queue immediately. Skipped files stay in the queue until you decide what to do with them. They will not be retried on future bulk jobs unless you explicitly convert them.


## OCR Settings

These settings on the Settings page control OCR behavior:

| Setting                        | What it controls                                   | Default | Range    |
|--------------------------------|----------------------------------------------------|---------|----------|
| **OCR Confidence Threshold**   | Minimum average confidence to accept without review | 60      | 0 - 100  |
| **Unattended Mode**            | Auto-accept all OCR text without flagging          | Off     | On / Off |
| **OCR Preprocessing**          | Apply deskew, contrast, and noise reduction        | On      | On / Off |

### Adjusting the Confidence Threshold

- **Raise it** (e.g., to 80) if accuracy is critical and you are willing to review more flags.
- **Lower it** (e.g., to 40) if you want fewer interruptions and can tolerate some errors.
- **Set it to 0** if you want to accept all OCR text regardless of confidence (similar to unattended mode, but flags are still created — just not shown as needing review).

> **Warning:** Setting the threshold very high (above 90) will flag almost every page, even clean scans. OCR engines rarely report 100% confidence even on perfect text. A threshold of 60-70 is a good starting point for most documents.


## Tips for Better OCR Results

The quality of OCR depends heavily on the quality of the original scan. Here are some things that improve results:

| Factor              | Good for OCR                          | Bad for OCR                          |
|---------------------|---------------------------------------|--------------------------------------|
| Scan resolution     | 300 DPI or higher                     | Below 150 DPI                        |
| Page alignment      | Straight, not rotated                 | Skewed or rotated significantly      |
| Text contrast       | Dark text on white background         | Light text, colored backgrounds      |
| Font style          | Standard printed fonts                | Handwriting, decorative fonts        |
| Page condition      | Clean, no stains or creases           | Wrinkled, stained, faded             |
| Language            | English (default)                     | Mixed languages on same page         |

> **Tip:** If you have control over the scanning process, scan at 300 DPI in black-and-white mode for the best OCR accuracy. Color scans are larger files and do not improve text recognition.


## Common Questions

**Does OCR slow down conversion?**
Yes. OCR adds processing time — typically a few seconds per page. A 100-page scanned PDF may take a few minutes. Text-based PDFs that skip OCR convert much faster.

**Can MarkFlow handle handwriting?**
Yes. As of v0.20.3, MarkFlow automatically detects handwritten pages during OCR. When Tesseract produces very low confidence results that match handwriting patterns (low confidence + high flagged word ratio + unrecognisable words), MarkFlow sends the page image to an LLM vision provider (Claude, GPT-4V, Gemini, or Ollama) for transcription.

In **unattended mode**, the LLM transcription automatically replaces Tesseract's garbled output. In **review mode**, both Tesseract's attempt and the LLM's transcription are shown — you can accept either one or edit further.

The handwriting detection threshold is configurable via the `handwriting_confidence_threshold` preference (default: 40%). An active LLM vision provider must be configured for the fallback to work. If no provider is available, handwritten pages are flagged for manual review as before.

**What languages does OCR support?**
MarkFlow uses Tesseract, which supports many languages. The default configuration is English. Ask your administrator if you need other languages enabled.

**Can I re-run OCR on a file?**
Yes. Convert the same file again and MarkFlow will run OCR fresh. Previous review decisions do not carry over to new conversions.


## Related

- [Getting Started](/help#getting-started)
- [Document Conversion](/help#document-conversion)
- [Bulk Conversion](/help#bulk-conversion)
- [Fidelity Tiers](/help#fidelity-tiers)
- [Search](/help#search)
