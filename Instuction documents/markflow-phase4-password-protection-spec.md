# MarkFlow Phase 4 Addition: Password-Protected Document Handling

> **Purpose:** When employees leave an organization, their password-protected documents remain inaccessible. MarkFlow needs to handle these gracefully during both single-file conversion and bulk repository indexing — stripping trivial restrictions automatically, accepting known passwords, and attempting recovery of unknown passwords via dictionary/brute-force attacks.

---

## 1. Two Kinds of "Password Protection"

Every office format has **two distinct protection layers**. MarkFlow must handle both:

| Layer | What It Does | Difficulty |
|-------|-------------|------------|
| **Restriction/Permissions** | Prevents editing, printing, copying — but the file opens fine. PDF "owner password", Word/Excel edit protection, sheet protection. | **Trivial.** These are flags/XML tags, not real encryption. Strip them silently. |
| **Encryption** | File cannot be opened at all without the password. AES-128/256 or legacy RC4 encryption. | **Real crypto.** Requires the password or brute-force attempts. |

### Design Principle

MarkFlow should **never fail silently** on a protected file. The behavior cascade is:

1. **Detect** the protection type
2. **Auto-strip** if it's just a restriction (no password needed)
3. **Try known passwords** from the organization's password list
4. **Attempt dictionary/brute-force** if configured
5. **Log and skip** if all attempts fail — record in manifest, never crash the batch

---

## 2. Format-Specific Handling

### 2.1 PDF

**Library:** `pikepdf` (already likely in the stack via pdfplumber dependency chain; if not, add it)

**Restriction passwords (owner password):**
```python
import pikepdf

# pikepdf can open owner-password-restricted PDFs without any password
# The restrictions are just metadata flags — pikepdf ignores them
pdf = pikepdf.open("restricted.pdf")
pdf.save("unrestricted.pdf")
```
This is instant and requires no password. MarkFlow should do this transparently.

**Encryption passwords (user password):**
```python
try:
    pdf = pikepdf.open("encrypted.pdf")  # Try no password first
except pikepdf.PasswordError:
    # File is truly encrypted — need a password
    for password in password_candidates:
        try:
            pdf = pikepdf.open("encrypted.pdf", password=password)
            pdf.save("decrypted.pdf")
            break
        except pikepdf.PasswordError:
            continue
```

**Brute-force notes:**
- PDF encryption (especially AES-256 in modern PDFs) is slow to brute-force in pure Python
- For serious cracking, shell out to `john` (John the Ripper) or `hashcat` if installed
- MarkFlow should support an **optional** system dependency on `john` for PDF cracking
- Without `john`, fall back to Python-based dictionary attack (slower but no extra deps)

### 2.2 DOCX / XLSX / PPTX (Office Open XML — OOXML)

**Library:** `msoffcrypto-tool` (Python, handles both old and new Office encryption)

**Edit/sheet protection (restriction):**
These are just XML tags inside the ZIP archive. No encryption involved.

```python
import zipfile
from lxml import etree

# DOCX edit protection: remove <w:documentProtection> from word/settings.xml
# XLSX sheet protection: remove <sheetProtection> from each xl/worksheets/sheet*.xml
# XLSX workbook protection: remove <workbookProtection> from xl/workbook.xml
# PPTX: remove <p:modifyVerifier> from ppt/presentation.xml
```

Strip these XML elements, rewrite the ZIP, done. No password needed.

**Encryption (file-level, can't even open):**
```python
import msoffcrypto

with open("encrypted.docx", "rb") as f:
    file = msoffcrypto.OfficeFile(f)
    if file.is_encrypted():
        for password in password_candidates:
            try:
                file.load_key(password=password)
                with open("decrypted.docx", "wb") as out:
                    file.decrypt(out)
                break
            except Exception:
                continue
```

`msoffcrypto-tool` handles:
- Office 2007+ (OOXML with AES-128/AES-256)
- Office 97-2003 (.doc, .xls, .ppt with RC4)
- XOR obfuscation (very old Excel files)

### 2.3 Legacy Office (.doc, .xls, .ppt)

Same `msoffcrypto-tool` library handles these. The encryption is weaker (RC4 or XOR), so brute-force is faster.

For `.xls` sheet protection specifically, `openpyxl` doesn't handle `.xls` — use `xlrd` to read and note that old XLS sheet protection is trivially crackable (it's a 16-bit hash).

---

## 3. Architecture: `core/password_handler.py`

A single module that all format handlers call before attempting conversion.

```
core/
├── password_handler.py      # NEW — central password handling
├── password_wordlists/      # NEW — directory for dictionary files
│   ├── common.txt           # Ships with MarkFlow (top 10K passwords)
│   └── org_passwords.txt    # User-provided org-specific passwords
```

### 3.1 Class Design

```python
# core/password_handler.py

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()


class ProtectionType(Enum):
    NONE = "none"
    RESTRICTION_ONLY = "restriction_only"      # Edit/print restrictions, no real encryption
    ENCRYPTED = "encrypted"                     # Real encryption, password required
    ENCRYPTED_DECRYPTED = "encrypted_decrypted" # Was encrypted, successfully decrypted


class CrackMethod(Enum):
    NONE = "none"
    KNOWN_PASSWORD = "known_password"       # From org password list
    DICTIONARY = "dictionary"               # Dictionary attack
    BRUTE_FORCE = "brute_force"             # Character-space brute force
    EXTERNAL_TOOL = "external_tool"         # john/hashcat


@dataclass
class PasswordResult:
    """Result of a password-handling attempt."""
    protection_type: ProtectionType
    success: bool
    method: CrackMethod = CrackMethod.NONE
    password_found: Optional[str] = None   # The password that worked (for logging/reuse)
    output_path: Optional[Path] = None     # Path to the unlocked file
    error: Optional[str] = None
    attempts: int = 0


class PasswordHandler:
    """
    Central password handling for all document formats.
    
    Called by format handlers BEFORE conversion. If a file is protected,
    this class attempts to unlock it and returns a clean file path for
    the handler to convert.
    """

    def __init__(self, settings: dict):
        self.org_passwords: list[str] = self._load_org_passwords(settings)
        self.dictionary_path: Optional[Path] = self._resolve_dictionary(settings)
        self.brute_force_enabled: bool = settings.get("brute_force_enabled", False)
        self.brute_force_max_length: int = settings.get("brute_force_max_length", 6)
        self.brute_force_charset: str = settings.get("brute_force_charset", "alphanumeric")
        self.timeout_seconds: int = settings.get("password_timeout_seconds", 300)

    async def handle(self, file_path: Path, format_type: str) -> PasswordResult:
        """
        Main entry point. Detect protection, attempt unlock.
        
        Returns PasswordResult with output_path pointing to the unlocked
        file (or the original file if no protection was found).
        """
        ...

    # --- Format-specific detection ---
    async def _detect_pdf(self, path: Path) -> ProtectionType: ...
    async def _detect_ooxml(self, path: Path) -> ProtectionType: ...
    async def _detect_legacy_office(self, path: Path) -> ProtectionType: ...

    # --- Restriction stripping (no password needed) ---
    async def _strip_pdf_restrictions(self, path: Path) -> Path: ...
    async def _strip_ooxml_restrictions(self, path: Path) -> Path: ...

    # --- Encryption cracking cascade ---
    async def _try_passwords(self, path: Path, fmt: str, passwords: list[str]) -> Optional[str]: ...
    async def _dictionary_attack(self, path: Path, fmt: str) -> Optional[str]: ...
    async def _brute_force_attack(self, path: Path, fmt: str) -> Optional[str]: ...
    async def _external_tool_attack(self, path: Path, fmt: str) -> Optional[str]: ...
```

### 3.2 Integration With Format Handlers

Each existing handler gets a small addition at the top of its `to_markdown()` and `from_markdown()` methods:

```python
# In any format handler (e.g., handlers/pdf_handler.py)

async def to_markdown(self, file_path: Path, options: dict) -> DocumentModel:
    # Step 0: Handle password protection
    pw_result = await self.password_handler.handle(file_path, "pdf")
    
    if not pw_result.success:
        # Log it, record in manifest, return a stub DocumentModel with error
        logger.warning("password_protected_skip", 
                       file=str(file_path), 
                       error=pw_result.error)
        return self._error_document(file_path, pw_result.error)
    
    # Use the (possibly decrypted) file for conversion
    working_path = pw_result.output_path or file_path
    
    # ... rest of existing conversion logic using working_path ...
```

### 3.3 Password Cascade Order

For every encrypted file, MarkFlow tries passwords in this order:

1. **Empty string** — surprisingly common
2. **Organization password list** (`org_passwords.txt`) — user-maintained, org-specific passwords former employees commonly used
3. **"Found" passwords** — passwords that worked on other files in the same batch (employees often reuse passwords across documents)
4. **Dictionary attack** — `common.txt` wordlist + common mutations (append 1, !, capitalize, etc.)
5. **Brute-force** — configurable charset and max length, with timeout
6. **External tool** (`john` or `hashcat`) — if installed on the system, hand off the hash for GPU-accelerated cracking

Step 6 is optional and only used if the tool is detected on the system.

---

## 4. UI Addition: Convert Page

Add a **"Password-Protected Files"** section to the existing convert page.

### 4.1 Single File Conversion

When a user uploads a password-protected file:

1. MarkFlow detects the protection type
2. If restriction-only → strip silently, show a notice: *"Edit restrictions removed automatically"*
3. If encrypted → show a password input field: *"This file is encrypted. Enter the password or let MarkFlow attempt recovery."*
4. User can either:
   - Enter a known password
   - Click **"Attempt Recovery"** to run the dictionary/brute-force cascade
5. Show progress during recovery attempts (estimated time, attempts count)
6. On success → proceed to conversion, show which method worked
7. On failure → clear message: *"Unable to unlock. You can try a different password or add passwords to the organization list."*

### 4.2 Batch/Bulk Conversion

During bulk conversion (Phase 7), protected files are handled automatically:

1. Restrictions are stripped silently (logged)
2. Encrypted files run through the full cascade
3. Failed files are recorded in the batch manifest with status `password_locked`
4. After the batch completes, the UI shows a summary:
   - *"47 files had restrictions removed automatically"*
   - *"12 encrypted files unlocked via organization passwords"*
   - *"3 encrypted files unlocked via dictionary attack"*
   - *"5 encrypted files could not be unlocked"* (with file list)

### 4.3 Settings Page Addition

Add a **"Password Recovery"** section to the settings page:

| Setting | Default | Description |
|---------|---------|-------------|
| Organization passwords | *(empty file)* | Textarea or file upload for org-specific passwords, one per line |
| Dictionary attack enabled | `true` | Whether to try dictionary attack on unknown passwords |
| Brute-force enabled | `false` | Whether to try brute-force (can be slow) |
| Brute-force max length | `6` | Maximum password length for brute-force |
| Brute-force charset | `alphanumeric` | Character set: `numeric`, `alpha`, `alphanumeric`, `all_printable` |
| Recovery timeout | `300` seconds | Max time to spend on any single file |
| Reuse found passwords | `true` | Try passwords that worked on other files in the same batch |

These go into the existing `_PREFERENCE_SCHEMA` (following the Phase 8 pattern of not creating new settings tables).

---

## 5. Dependencies

### Required (add to requirements.txt / pyproject.toml)

```
pikepdf>=9.0.0          # PDF password handling (may already be a pdfplumber transitive dep)
msoffcrypto-tool>=5.4.0 # Office encryption/decryption (.docx, .xlsx, .pptx, .doc, .xls, .ppt)
lxml>=5.0.0             # XML manipulation for stripping protection tags (likely already present)
```

### Optional (system-level, for enhanced cracking)

```
# Not Python packages — system binaries
john                    # John the Ripper — for serious PDF/Office hash cracking
hashcat                 # GPU-accelerated password cracking (if CUDA/OpenCL available)
```

MarkFlow should detect these at startup and log their availability:
```
INFO  password_tools_available  john=true  hashcat=false
```

### Bundled Wordlist

Ship a `common.txt` with the top ~10,000 passwords (sourced from public datasets like SecLists' `10k-most-common.txt`). This file is used for dictionary attacks and is small enough to bundle in the Docker image.

---

## 6. Database Schema Addition

Add columns to the existing `documents` table (or the batch manifest table if that's separate in Phase 7):

```sql
-- Add to documents table
ALTER TABLE documents ADD COLUMN protection_type TEXT DEFAULT 'none';
    -- Values: none, restriction_only, encrypted, encrypted_decrypted, encrypted_failed
ALTER TABLE documents ADD COLUMN password_method TEXT DEFAULT NULL;
    -- Values: NULL, known_password, dictionary, brute_force, external_tool
ALTER TABLE documents ADD COLUMN password_attempts INTEGER DEFAULT 0;
```

This lets the UI show protection statistics and lets bulk conversion track which files still need manual intervention.

---

## 7. Security Considerations

### 7.1 Password Storage
- **Organization passwords** are stored in a plain text file on the server (same security posture as the rest of MarkFlow — it's a local/on-prem tool, not a SaaS product)
- **Found passwords** (from batch reuse) are held in memory only — never written to disk or database
- The `password_found` field in `PasswordResult` is for runtime reuse only. It is **not logged** and **not stored in SQLite**

### 7.2 Legal/Ethical
- This is for recovering **your organization's own documents** when the author is unavailable
- MarkFlow's UI should include a brief notice: *"Password recovery is intended for documents owned by your organization. Ensure compliance with your organization's data policies."*
- This is standard IT practice — every enterprise has procedures for recovering access to former employees' files

### 7.3 Tempfile Cleanup
- Decrypted files are written to a temp directory during conversion
- After conversion completes (success or failure), the decrypted temp file is deleted
- Use Python's `tempfile` module with `NamedTemporaryFile(delete=False)` + explicit cleanup in a `finally` block

---

## 8. Test Requirements

### Unit Tests (`tests/test_password_handler.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_detect_unprotected_pdf` | No false positives on normal PDFs |
| `test_detect_unprotected_docx` | No false positives on normal DOCX |
| `test_strip_pdf_restrictions` | Owner-password PDF opens and saves cleanly |
| `test_strip_docx_edit_protection` | `<w:documentProtection>` tag is removed |
| `test_strip_xlsx_sheet_protection` | `<sheetProtection>` tags are removed from all sheets |
| `test_strip_pptx_modify_protection` | `<p:modifyVerifier>` tag is removed |
| `test_decrypt_pdf_known_password` | Encrypted PDF decrypted with correct password |
| `test_decrypt_docx_known_password` | Encrypted DOCX decrypted with correct password |
| `test_decrypt_xlsx_known_password` | Encrypted XLSX decrypted with correct password |
| `test_decrypt_pptx_known_password` | Encrypted PPTX decrypted with correct password |
| `test_decrypt_legacy_xls` | Encrypted .xls (RC4) decrypted |
| `test_password_cascade_order` | Empty → org list → found → dictionary (in order) |
| `test_batch_password_reuse` | Password from file A is tried on file B |
| `test_timeout_respected` | Brute-force stops after configured timeout |
| `test_failure_logged_not_crashed` | Failed decryption returns error result, doesn't raise |
| `test_tempfile_cleanup` | Decrypted temp files are deleted after conversion |

### Test Fixtures

Create encrypted test files for each format:
```
tests/fixtures/password/
├── restricted.pdf          # Owner-password only (no user password)
├── encrypted.pdf           # User-password: "test123"
├── protected_edit.docx     # Edit protection enabled
├── encrypted.docx          # Encryption password: "test123"
├── protected_sheet.xlsx    # Sheet protection on Sheet1
├── protected_workbook.xlsx # Workbook structure protection
├── encrypted.xlsx          # Encryption password: "test123"
├── protected.pptx          # Modify protection
├── encrypted.pptx          # Encryption password: "test123"
└── encrypted.xls           # Legacy RC4 encryption: "test123"
```

---

## 9. Files to Create or Modify

### New Files
| File | Purpose |
|------|---------|
| `core/password_handler.py` | Central password detection, stripping, and cracking |
| `core/password_wordlists/common.txt` | Bundled top-10K password dictionary |
| `core/password_wordlists/.gitkeep` | Placeholder for `org_passwords.txt` (user-created, gitignored) |
| `tests/test_password_handler.py` | Full test suite |
| `tests/fixtures/password/` | Encrypted/protected test files (all formats) |

### Modified Files
| File | Change |
|------|--------|
| `handlers/pdf_handler.py` | Add `password_handler.handle()` call before conversion |
| `handlers/docx_handler.py` | Add `password_handler.handle()` call before conversion |
| `handlers/xlsx_handler.py` | Add `password_handler.handle()` call before conversion |
| `handlers/pptx_handler.py` | Add `password_handler.handle()` call before conversion |
| `core/database.py` | Add `protection_type`, `password_method`, `password_attempts` columns |
| `core/converter.py` | Initialize `PasswordHandler` and pass to handlers |
| `static/convert.html` | Add password input UI for encrypted files |
| `static/settings.html` | Add password recovery settings section |
| `api/routes/convert.py` | Handle password submission from UI |
| `requirements.txt` | Add `pikepdf`, `msoffcrypto-tool` |
| `Dockerfile` | Optionally add `john` package for enhanced cracking |
| `CLAUDE.md` | Update with password handling feature |

---

## 10. Done Criteria Checklist

- [ ] `core/password_handler.py` exists with full cascade logic
- [ ] Restriction-only PDFs are silently stripped via `pikepdf`
- [ ] Restriction-only OOXML files have protection XML tags removed
- [ ] Encrypted files are decrypted when password is provided manually
- [ ] Organization password list is loaded and tried automatically
- [ ] Found-password reuse works across files in a batch
- [ ] Dictionary attack works with bundled `common.txt`
- [ ] Brute-force attack works with configurable charset/length/timeout
- [ ] External tool detection (`john`) works and is used when available
- [ ] All four format handlers integrate with `PasswordHandler`
- [ ] Convert UI shows password input for encrypted files
- [ ] Settings UI has password recovery configuration section
- [ ] Database schema tracks protection type and method
- [ ] Temp files are cleaned up after decryption
- [ ] All 16+ tests pass
- [ ] Batch conversion handles protected files without crashing
- [ ] Failed files are logged with `password_locked` status
- [ ] CLAUDE.md updated with password handling feature
