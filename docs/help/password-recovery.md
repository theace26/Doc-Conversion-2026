# Password Recovery

MarkFlow can handle password-protected documents automatically during conversion.
This article explains how protection is detected, what MarkFlow can unlock on its
own, and how you can help it along when automatic recovery falls short.

---

## Two Layers of Protection

Documents can be protected in two very different ways. MarkFlow treats them
separately because one is trivial to remove and the other requires real work.

| Layer | What It Does | MarkFlow Behavior |
|-------|-------------|-------------------|
| **Restrictions** (edit, print, copy) | Prevents editing or printing but the content is still readable | Stripped automatically -- no password needed |
| **Encryption** (open password) | Content is fully encrypted; cannot be read without a password | Recovery attempted via the cracking cascade below |

> **Tip:** If your document just has an "editing restriction" or "print
> restriction," MarkFlow removes it silently. You will see a note in the
> conversion history saying "restrictions stripped" but nothing else changes.

### Supported Formats

Password handling covers these file types:

- **PDF** (.pdf) -- both restriction and encryption
- **Modern Office** (.docx, .xlsx, .pptx) -- file-level encryption and XML-level edit/sheet protection
- **Legacy Office** (.doc, .xls, .ppt) -- OLE encryption

All other formats pass through unchanged.

---

## The Cracking Cascade

When MarkFlow finds an encrypted file, it works through a series of strategies
in order. As soon as one succeeds, it stops and moves on.

| Step | Strategy | What Happens |
|------|----------|-------------|
| 1 | **Empty password** | Tries an empty string -- surprisingly common on auto-generated documents |
| 2 | **User-supplied password** | Tries the password you typed on the Convert page or sent via the API |
| 3 | **Organization password list** | Tries every line in `org_passwords.txt` (see below) |
| 4 | **Found passwords** | Tries passwords that already worked on other files in the same batch |
| 5 | **Dictionary attack** | Tries a bundled wordlist of common passwords, plus common mutations (capitalization, trailing digits, year suffixes) |
| 6 | **Brute-force** | Tries every character combination up to a configured length and character set |
| 7 | **John the Ripper** | If installed, runs John against the file hash with the common wordlist |
| 8 | **Hashcat (GPU)** | If enabled, delegates to hashcat for GPU-accelerated mask attack |

> **Warning:** Steps 6 through 8 can be slow, especially for strong encryption.
> The timeout setting (default 300 seconds) limits how long MarkFlow spends on
> any single file before giving up and marking it as failed.

If every step fails, the file is recorded in conversion history with status
"failed" and the reason "Unable to decrypt." The rest of the batch continues
normally.

---

## Supplying a Password on the Convert Page

When you upload files through the Convert page, there is a **Password** field
below the file picker. If you know the password for one or more files in your
upload, type it there before clicking Convert.

MarkFlow tries your password at step 2 of the cascade -- before the dictionary
or brute-force stages. If the password works, conversion proceeds immediately
with no delay.

You can only supply one password per upload. If your batch contains files with
different passwords, convert them in separate batches or rely on the "found
password reuse" feature (step 4) which tries passwords that worked on earlier
files in the same job.

> **Tip:** When converting via the API (`POST /api/convert`), pass the password
> in the `password` field of the multipart form data.

---

## The Organization Password List

Many organizations use a small set of standard passwords across departments.
Instead of typing them every time, you can add them to a file that MarkFlow
checks automatically.

The file lives at:

```
core/password_wordlists/org_passwords.txt
```

Inside the container that path is `/app/core/password_wordlists/org_passwords.txt`.

**Format:** One password per line, no quoting, no comments. Blank lines are
ignored.

```
companyname2024
Finance2025
HR_Password!
quarterly-report
```

MarkFlow loads this file when the password handler initializes. To update it:

1. Edit the file (or mount a custom version via Docker volume).
2. Restart the container, or wait for the next bulk job to start -- the handler
   re-reads the file each time.

> **Warning:** Keep this file secure. Anyone with access to the container
> filesystem can read it. Do not commit it to version control if it contains
> real passwords.

---

## Found Password Reuse

When the "Reuse found passwords across batch" setting is on (it is by default),
MarkFlow keeps a list of every password that successfully decrypted a file
during the current bulk job. Those passwords are tried at step 4 of the
cascade for every subsequent file.

This is especially useful when someone has protected an entire folder of
documents with the same password. The first file goes through the full
cascade, and the rest decrypt almost instantly.

The found-password list is per-job. It does not persist between jobs and is
never written to disk.

---

## Dictionary and Brute-Force Settings

These settings live on the **Settings** page under **Password Recovery**. See
[Settings Guide](/help#settings-guide) for the full reference.

| Setting | Default | Description |
|---------|---------|-------------|
| Dictionary attack | On | Try the bundled `common.txt` wordlist plus mutations |
| Brute-force | Off | Try every character combination |
| Max brute-force length | 6 | Longest password to attempt (1--8) |
| Character set | Alphanumeric | `numeric`, `alpha`, `alphanumeric`, or `all_printable` |
| Recovery timeout | 300 seconds | Max time per file before giving up |

> **Warning:** Brute-force with `all_printable` at length 8 generates billions
> of combinations. Unless you have GPU acceleration enabled, keep the length
> low (4--5) or use a narrower character set.

### Dictionary Mutations

For each word in the dictionary, MarkFlow also tries these automatic mutations:

- Capitalized (e.g., `password` becomes `Password`)
- All uppercase (`PASSWORD`)
- Trailing `1`, `!`, `123`
- Trailing year (`2024`, `2025`, `2026`)

This catches the most common variations without needing a larger wordlist.

---

## GPU Acceleration

MarkFlow can use **hashcat** for GPU-accelerated password cracking. This is
dramatically faster than CPU-based brute-force -- a modern GPU can test millions
of password candidates per second.

There are two paths for GPU acceleration:

| Path | GPU Vendors | How It Works |
|------|-------------|-------------|
| **Container (NVIDIA)** | NVIDIA only | GPU is passed into the Docker container via NVIDIA Container Toolkit |
| **Host worker** | NVIDIA, AMD, Intel | A small script runs on your host machine with direct GPU access |

See [GPU Setup](/help#gpu-setup) for installation instructions.

### Hashcat Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Use hashcat | On | Enable GPU-accelerated cracking when available |
| Workload profile | 3 (High) | 1 = Low (desktop responsive), 2 = Default, 3 = High (dedicated), 4 = Maximum (100% GPU) |

> **Tip:** If you are running MarkFlow on a machine you also use for other
> work, set the workload profile to 1 or 2 so hashcat does not make the
> system unresponsive.

### How MarkFlow Chooses the Execution Path

MarkFlow checks GPU availability at startup and picks the best available path:

1. **NVIDIA container GPU** -- if nvidia-smi is available inside the container and hashcat detects a CUDA or OpenCL backend
2. **Host worker** -- if a host worker has written its capabilities to the shared queue directory
3. **Hashcat CPU** -- if hashcat is installed in the container but no GPU is detected
4. **None** -- if hashcat is not installed at all

You can see the current detection result on the **Settings** page in the
GPU Acceleration card, or by calling `GET /api/health` and checking the
`components.gpu` section.

---

## What Happens After Recovery

When a password is successfully recovered:

- The decrypted file is written to a temporary location.
- The format handler ingests the decrypted copy as if it were a normal file.
- The temporary copy is deleted after conversion completes.
- The conversion history records which cracking method succeeded and how many
  attempts it took.
- If "reuse found" is on, the password is cached for the rest of the batch.

The original encrypted file is never modified.

---

## Compliance Note

Password recovery is intended for documents owned by your organization --
files where you have the legal right to access the content but the password
has been lost or the original author is unavailable.

Ensure that your use of these features complies with your organization's
data governance and information security policies.

---

## Related

- [GPU Setup](/help#gpu-setup) -- installing hashcat and configuring GPU passthrough
- [Settings Guide](/help#settings-guide) -- full reference for all password recovery settings
- [Getting Started](/help#getting-started) -- uploading and converting your first file
