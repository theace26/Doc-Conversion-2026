# Getting Started with MarkFlow

Welcome to MarkFlow, the document conversion tool that turns your everyday office files into clean, readable Markdown — and back again. Whether you work with Word documents, PDFs, spreadsheets, or presentations, MarkFlow handles the heavy lifting so you can focus on your content.

This guide will walk you through your very first conversion and help you feel at home in the application.


## What Is MarkFlow?

MarkFlow is a web application your team uses to convert documents between their original format (Word, PDF, PowerPoint, Excel) and Markdown. You open it in your browser — there is nothing to install on your computer.

Think of it as a translator for your files. You give it a Word document, and it gives you back a nicely formatted text version. You give it that text version, and it can rebuild the Word document. The goal is to make your content portable, searchable, and easy to manage.


## What Is Markdown?

Markdown is a simple way of writing formatted text using plain characters. Instead of clicking a Bold button in Word, you wrap a word in double asterisks: `**bold**`. Instead of selecting a font size for a heading, you put a hash sign in front of it: `# My Heading`.

Here is a quick comparison:

| What you want      | How it looks in Word         | How it looks in Markdown        |
|---------------------|-----------------------------|---------------------------------|
| Bold text           | **Bold** (toolbar button)   | `**Bold**`                      |
| Italic text         | *Italic* (toolbar button)   | `*Italic*`                      |
| Heading             | Heading 1 style dropdown    | `# Heading 1`                   |
| Bulleted list       | Bullet button on toolbar    | `- List item`                   |
| Numbered list       | Numbering button on toolbar | `1. List item`                  |
| Link                | Insert Hyperlink dialog     | `[Click here](https://...)` |

You do not need to learn Markdown to use MarkFlow. The application reads and writes it for you. But knowing the basics helps you understand what you are looking at when you open a converted file.

> **Tip:** Markdown files are just plain text, so they open in any text editor — Notepad, VS Code, or even a web browser. You will never be locked into a single application.


## Your First Conversion

Let's walk through converting a Word document step by step.

### Step 1: Open MarkFlow

Open your web browser and go to the address your team uses for MarkFlow (usually something like `http://localhost:8000`). You will land on the **Search** page.

### Step 2: Go to the Convert Page

Click **Convert** in the navigation bar at the top of the page. This takes you to the upload screen.

### Step 3: Choose Your Direction

Near the top of the Convert page, you will see a direction toggle. It controls which way the conversion goes:

| Direction              | What it does                                  |
|------------------------|-----------------------------------------------|
| **To Markdown**        | Takes your original file and produces Markdown |
| **From Markdown**      | Takes a Markdown file and produces the original format |

For your first try, leave it set to **To Markdown**.

### Step 4: Upload Your File

You have two ways to add a file:

1. **Drag and drop** — Pick up the file from your desktop or file explorer and drop it onto the upload area on the page.
2. **Click to browse** — Click the upload area and choose a file from the file picker dialog.

You will see the filename appear with a small badge showing the file type (DOCX, PDF, etc.).

> **Warning:** There is a file size limit. Very large files (over 100 MB) may be rejected. If your file is too big, consider splitting it into smaller parts first.

### Step 5: Start the Conversion

Click the **Convert** button. MarkFlow will show you a progress screen with a live progress bar. For a typical Word document, this takes just a few seconds.

### Step 6: Get Your Results

Once the conversion finishes, you will be taken to the results view. From here you can:

- **Download the Markdown file** — Click the download link next to the converted file.
- **Download everything as a ZIP** — If the conversion produced multiple files (images, sidecars), grab them all at once.
- **View the conversion in History** — Every conversion is saved so you can come back to it later.

Congratulations — you just converted your first document!


## The Navigation Bar

The navigation bar runs along the top of every page. Depending on your account permissions, you may see some or all of these links:

| Nav Link       | What it does                                                        |
|----------------|---------------------------------------------------------------------|
| **Search**     | Find previously converted documents by keyword                      |
| **Convert**    | Upload and convert a single file                                    |
| **Bulk**       | Convert entire folders of files at once                             |
| **History**    | Browse all past conversions with filters and sorting                |
| **Status**     | See running jobs, pause or cancel them                              |
| **Trash**      | View and restore deleted files before they are permanently removed  |
| **Settings**   | Adjust preferences like OCR sensitivity and worker count            |
| **Admin**      | System dashboard for administrators (resource usage, API keys)      |

> **Tip:** The Status link shows a small number badge when jobs are actively running. This lets you keep an eye on progress from any page.

> **Tip *(v0.35.0)*:** The top of the Status page is the **Active
> Operations Hub** — a single live list of every long-running thing
> MarkFlow is currently doing (bulk jobs, pipeline scans, trash empty,
> search-index rebuild, database backup, etc.). It's the one place
> to look when you want to know "what's MarkFlow up to right now?".

### Pages You Might Not See

Not every link appears for every user. MarkFlow uses roles to control who can do what:

| Role             | What you can access                                    |
|------------------|--------------------------------------------------------|
| **Search User**  | Search and Status only                                 |
| **Operator**     | Everything above, plus Convert, Bulk, History, Trash   |
| **Manager**      | Everything above, plus Settings                        |
| **Admin**        | Full access, including Admin panel and API keys        |

If you need access to a page you cannot see, ask your team administrator.


## How It Works

Behind the scenes, MarkFlow follows a straightforward pipeline for every file:

1. **Validate** — Check that the file type is supported and the file is not corrupt.
2. **Ingest** — Read the document's content: headings, paragraphs, tables, images, and metadata.
3. **Build a model** — Organize everything into a structured internal representation.
4. **Extract styles** — Record fonts, sizes, colors, and spacing so they can be reapplied later.
5. **Generate output** — Write the Markdown file (or the original format, if going the other direction).
6. **Save metadata** — Store a manifest and style sidecar alongside the output.
7. **Record in history** — Log the conversion so you can find it again.

You do not need to understand these steps to use the tool. They happen automatically every time you convert a file.


## What Happens to My Original File?

MarkFlow keeps a copy of your original file alongside the conversion output. It is stored in a folder called `_originals` inside the batch output directory. Your original is never modified or deleted during conversion.

> **Tip:** If you ever need to reconvert the same file with different settings, you can always find the original in History and download it again.


## Common Questions

**Can I convert more than one file at a time?**
Yes. For a handful of files, drag them all onto the upload area on the Convert page. For large batches (hundreds or thousands of files), use the [Bulk Conversion](/help.html#bulk-conversion) feature instead.

**What if my file has images?**
Images are extracted and saved as separate PNG files alongside the Markdown output. The Markdown file includes references that point to those images.

**What if the conversion looks wrong?**
Some documents have complex formatting that does not translate perfectly. Check the [Fidelity Tiers](/help.html#fidelity-tiers) article to learn how MarkFlow handles different levels of formatting detail.

**Do I need to be online?**
MarkFlow runs on your local network. As long as you can reach the server, you are good. No internet connection is required.


## Next Steps

Now that you know the basics, explore these topics:

- [Document Conversion](/help.html#document-conversion) — Supported formats and detailed upload instructions
- [Fidelity Tiers](/help.html#fidelity-tiers) — How MarkFlow preserves formatting at different levels
- [Search](/help.html#search) — Finding your converted documents by keyword
- [Bulk Conversion](/help.html#bulk-conversion) — Converting entire folders at once


## Related

- [Document Conversion](/help.html#document-conversion)
- [Fidelity Tiers](/help.html#fidelity-tiers)
- [OCR Pipeline](/help.html#ocr-pipeline)
- [Bulk Conversion](/help.html#bulk-conversion)
- [Search](/help.html#search)
- [File Lifecycle](/help.html#file-lifecycle)
