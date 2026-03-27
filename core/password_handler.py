"""
Password-protected document handling.

Detects protection type (restriction vs encryption), strips trivial
restrictions automatically, and attempts password recovery via a cascade:
  1. Empty string
  2. User-supplied password (from upload form or API)
  3. Organization password list (org_passwords.txt)
  4. Found passwords (reused from other files in the same batch)
  5. Dictionary attack (common.txt wordlist)
  6. Brute-force (configurable charset/length/timeout)
  7. External tool (john the ripper, if installed)

All format handlers are preprocessed through this module before ingest.
"""

import itertools
import json as _json
import os
import secrets
import shutil
import string
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_WORDLIST_DIR = Path(__file__).parent / "password_wordlists"


class ProtectionType(Enum):
    NONE = "none"
    RESTRICTION_ONLY = "restriction_only"
    ENCRYPTED = "encrypted"
    ENCRYPTED_DECRYPTED = "encrypted_decrypted"
    ENCRYPTED_FAILED = "encrypted_failed"


class CrackMethod(Enum):
    NONE = "none"
    USER_SUPPLIED = "user_supplied"
    KNOWN_PASSWORD = "known_password"
    FOUND_REUSE = "found_reuse"
    DICTIONARY = "dictionary"
    BRUTE_FORCE = "brute_force"
    EXTERNAL_TOOL = "external_tool"
    HASHCAT_GPU = "hashcat_gpu"
    HASHCAT_CPU = "hashcat_cpu"
    HASHCAT_HOST = "hashcat_host"


@dataclass
class PasswordResult:
    """Result of a password-handling attempt."""
    protection_type: ProtectionType
    success: bool
    method: CrackMethod = CrackMethod.NONE
    password_found: Optional[str] = None
    output_path: Optional[Path] = None
    error: Optional[str] = None
    attempts: int = 0


# ── Format categories ────────────────────────────────────────────────────────

_PDF_EXTS = {".pdf"}
_OOXML_EXTS = {".docx", ".xlsx", ".pptx"}
_LEGACY_OFFICE_EXTS = {".doc", ".xls", ".ppt"}
_ALL_SUPPORTED = _PDF_EXTS | _OOXML_EXTS | _LEGACY_OFFICE_EXTS


class PasswordHandler:
    """
    Central password handling for all document formats.

    Called by the converter BEFORE format handler ingest(). If a file is
    protected, attempts to unlock it and returns a clean file path.
    """

    def __init__(self, settings: dict | None = None):
        settings = settings or {}
        self._settings = settings
        self.org_passwords: list[str] = self._load_org_passwords()
        self.dictionary_enabled: bool = settings.get("password_dictionary_enabled", "true") == "true"
        self.brute_force_enabled: bool = settings.get("password_brute_force_enabled", "false") == "true"
        self.brute_force_max_length: int = int(settings.get("password_brute_force_max_length", "6"))
        self.brute_force_charset: str = settings.get("password_brute_force_charset", "alphanumeric")
        self.timeout_seconds: int = int(settings.get("password_timeout_seconds", "300"))
        self.reuse_found: bool = settings.get("password_reuse_found", "true") == "true"
        self.hashcat_enabled: bool = settings.get("password_hashcat_enabled", "true") == "true"
        # Passwords found during this batch — shared across files
        self._found_passwords: list[str] = []
        # External tool availability (cached)
        self._john_available: bool | None = None
        # GPU / hashcat path (lazy-loaded)
        self._gpu_info = None
        self._hashcat_path: str | None = None
        self._hashcat_queue_dir = Path("/mnt/hashcat-queue")

    def _load_org_passwords(self) -> list[str]:
        """Load organization-specific passwords from org_passwords.txt."""
        org_file = _WORDLIST_DIR / "org_passwords.txt"
        if not org_file.exists():
            return []
        try:
            lines = org_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            return [line.strip() for line in lines if line.strip()]
        except Exception:
            return []

    def _load_dictionary(self) -> list[str]:
        """Load the bundled common password dictionary."""
        dict_file = _WORDLIST_DIR / "common.txt"
        if not dict_file.exists():
            return []
        try:
            lines = dict_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            return [line.strip() for line in lines if line.strip()]
        except Exception:
            return []

    def _check_john_available(self) -> bool:
        """Check if John the Ripper is installed."""
        if self._john_available is not None:
            return self._john_available
        try:
            result = subprocess.run(
                ["john", "--help"], capture_output=True, timeout=5
            )
            self._john_available = result.returncode in (0, 1)  # john returns 1 for --help
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._john_available = False
        return self._john_available

    def handle_sync(
        self,
        file_path: Path,
        user_password: str | None = None,
    ) -> PasswordResult:
        """
        Main entry point (synchronous — runs in thread via converter).

        Detects protection, attempts unlock, returns result with output_path
        pointing to the unlocked file (or original if no protection).
        """
        ext = file_path.suffix.lower()
        if ext not in _ALL_SUPPORTED:
            return PasswordResult(
                protection_type=ProtectionType.NONE,
                success=True,
                output_path=file_path,
            )

        try:
            # Step 1: Detect protection type
            ptype = self._detect(file_path, ext)

            if ptype == ProtectionType.NONE:
                return PasswordResult(
                    protection_type=ProtectionType.NONE,
                    success=True,
                    output_path=file_path,
                )

            # Step 2: Strip restrictions (no password needed)
            if ptype == ProtectionType.RESTRICTION_ONLY:
                stripped = self._strip_restrictions(file_path, ext)
                log.info("password.restrictions_stripped", file=file_path.name)
                return PasswordResult(
                    protection_type=ProtectionType.RESTRICTION_ONLY,
                    success=True,
                    output_path=stripped,
                )

            # Step 3: Encrypted — build password candidate list and try cascade
            log.info("password.encrypted_detected", file=file_path.name)
            candidates = self._build_candidate_list(user_password)
            result = self._try_decrypt(file_path, ext, candidates)

            if result.success:
                # Cache the password for reuse on other files
                if result.password_found and self.reuse_found:
                    if result.password_found not in self._found_passwords:
                        self._found_passwords.append(result.password_found)
                log.info(
                    "password.decrypted",
                    file=file_path.name,
                    method=result.method.value,
                    attempts=result.attempts,
                )
                return result

            log.warning(
                "password.decrypt_failed",
                file=file_path.name,
                attempts=result.attempts,
            )
            return result

        except Exception as exc:
            log.error("password.handler_error", file=file_path.name, error=str(exc))
            return PasswordResult(
                protection_type=ProtectionType.ENCRYPTED_FAILED,
                success=False,
                error=str(exc),
            )

    # ── Detection ────────────────────────────────────────────────────────────

    def _detect(self, path: Path, ext: str) -> ProtectionType:
        """Detect the protection type of a file."""
        if ext in _PDF_EXTS:
            return self._detect_pdf(path)
        elif ext in _OOXML_EXTS:
            return self._detect_ooxml(path)
        elif ext in _LEGACY_OFFICE_EXTS:
            return self._detect_legacy_office(path)
        return ProtectionType.NONE

    def _detect_pdf(self, path: Path) -> ProtectionType:
        """Detect PDF protection type using pikepdf."""
        import pikepdf

        try:
            pdf = pikepdf.open(path)
            # Opened without password — check if there were restrictions
            if pdf.is_encrypted:
                # Had an owner password (restrictions) but no user password
                pdf.close()
                return ProtectionType.RESTRICTION_ONLY
            pdf.close()
            return ProtectionType.NONE
        except pikepdf.PasswordError:
            return ProtectionType.ENCRYPTED
        except Exception:
            return ProtectionType.NONE

    def _detect_ooxml(self, path: Path) -> ProtectionType:
        """Detect OOXML (docx/xlsx/pptx) protection type."""
        import msoffcrypto

        # Check file-level encryption first
        try:
            with open(path, "rb") as f:
                file = msoffcrypto.OfficeFile(f)
                if file.is_encrypted():
                    return ProtectionType.ENCRYPTED
        except Exception:
            # msoffcrypto may fail on non-OLE files (valid OOXML without encryption)
            pass

        # Check for XML-level restrictions (edit/sheet/workbook protection)
        try:
            if not zipfile.is_zipfile(path):
                return ProtectionType.NONE
            return self._check_ooxml_restrictions(path)
        except Exception:
            return ProtectionType.NONE

    def _check_ooxml_restrictions(self, path: Path) -> ProtectionType:
        """Check for enforced edit/sheet/workbook protection tags in OOXML ZIP."""
        from lxml import etree

        # Tags to look for with their namespace and enforcement attributes
        protection_checks = [
            # (namespace, local_name, enforcement_attr_local)
            ("http://schemas.openxmlformats.org/wordprocessingml/2006/main", "documentProtection", "enforcement"),
            ("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "sheetProtection", "sheet"),
            ("http://schemas.openxmlformats.org/spreadsheetml/2006/main", "workbookProtection", "lockStructure"),
            ("http://schemas.openxmlformats.org/presentationml/2006/main", "modifyVerifier", None),
        ]

        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith(".xml"):
                        continue
                    try:
                        content = zf.read(name)
                        if b"Protection" not in content and b"modifyVerifier" not in content:
                            continue
                        tree = etree.fromstring(content)
                        for ns, local, enforce_attr in protection_checks:
                            for el in tree.findall(f".//{{{ns}}}{local}"):
                                if enforce_attr is None:
                                    # modifyVerifier presence alone means protection
                                    return ProtectionType.RESTRICTION_ONLY
                                # Check if protection is actually enforced
                                val = el.get(enforce_attr) or el.get(f"{{{ns}}}{enforce_attr}")
                                if val and val.lower() in ("1", "true"):
                                    return ProtectionType.RESTRICTION_ONLY
                    except Exception:
                        continue
        except Exception:
            pass
        return ProtectionType.NONE

    def _detect_legacy_office(self, path: Path) -> ProtectionType:
        """Detect legacy Office (.doc/.xls/.ppt) encryption."""
        import msoffcrypto

        try:
            with open(path, "rb") as f:
                file = msoffcrypto.OfficeFile(f)
                if file.is_encrypted():
                    return ProtectionType.ENCRYPTED
        except Exception:
            pass
        return ProtectionType.NONE

    # ── Restriction stripping ────────────────────────────────────────────────

    def _strip_restrictions(self, path: Path, ext: str) -> Path:
        """Strip edit/print restrictions. Returns path to unrestricted file."""
        if ext in _PDF_EXTS:
            return self._strip_pdf_restrictions(path)
        elif ext in _OOXML_EXTS:
            return self._strip_ooxml_restrictions(path)
        return path

    def _strip_pdf_restrictions(self, path: Path) -> Path:
        """Strip PDF owner-password restrictions via pikepdf."""
        import pikepdf

        out_path = self._temp_path(path)
        pdf = pikepdf.open(path)
        pdf.save(out_path)
        pdf.close()
        return out_path

    def _strip_ooxml_restrictions(self, path: Path) -> Path:
        """Strip edit/sheet/workbook protection from OOXML by removing XML tags."""
        from lxml import etree

        out_path = self._temp_path(path)

        # Namespaces for protection tags to remove
        remove_tags = [
            ("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}", "documentProtection"),
            ("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}", "sheetProtection"),
            ("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}", "workbookProtection"),
            ("{http://schemas.openxmlformats.org/presentationml/2006/main}", "modifyVerifier"),
        ]

        with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(out_path, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".xml") and (
                    b"Protection" in data or b"modifyVerifier" in data
                ):
                    try:
                        tree = etree.fromstring(data)
                        modified = False
                        for ns, local in remove_tags:
                            for el in tree.findall(f".//{ns}{local}"):
                                el.getparent().remove(el)
                                modified = True
                        if modified:
                            data = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
                    except Exception:
                        pass
                zout.writestr(item, data)

        return out_path

    # ── Decryption cascade ───────────────────────────────────────────────────

    def _build_candidate_list(self, user_password: str | None = None) -> list[tuple[str, CrackMethod]]:
        """Build ordered list of (password, method) candidates."""
        candidates: list[tuple[str, CrackMethod]] = []

        # 1. Empty string
        candidates.append(("", CrackMethod.KNOWN_PASSWORD))

        # 2. User-supplied password
        if user_password:
            candidates.append((user_password, CrackMethod.USER_SUPPLIED))

        # 3. Organization password list
        for pw in self.org_passwords:
            candidates.append((pw, CrackMethod.KNOWN_PASSWORD))

        # 4. Found passwords (from other files in this batch)
        if self.reuse_found:
            for pw in self._found_passwords:
                candidates.append((pw, CrackMethod.FOUND_REUSE))

        return candidates

    def _try_decrypt(self, path: Path, ext: str, candidates: list[tuple[str, CrackMethod]]) -> PasswordResult:
        """Try all password candidates, then dictionary, then brute-force."""
        total_attempts = 0
        deadline = time.monotonic() + self.timeout_seconds

        # Phase 1: Direct candidates (org list, user-supplied, found)
        for password, method in candidates:
            if time.monotonic() > deadline:
                break
            total_attempts += 1
            decrypted = self._try_password(path, ext, password)
            if decrypted:
                return PasswordResult(
                    protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                    success=True,
                    method=method,
                    password_found=password,
                    output_path=decrypted,
                    attempts=total_attempts,
                )

        # Phase 2: Dictionary attack
        if self.dictionary_enabled and time.monotonic() < deadline:
            dictionary = self._load_dictionary()
            for pw in dictionary:
                if time.monotonic() > deadline:
                    break
                total_attempts += 1
                decrypted = self._try_password(path, ext, pw)
                if decrypted:
                    return PasswordResult(
                        protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                        success=True,
                        method=CrackMethod.DICTIONARY,
                        password_found=pw,
                        output_path=decrypted,
                        attempts=total_attempts,
                    )
                # Also try common mutations
                for mutation in self._mutations(pw):
                    if time.monotonic() > deadline:
                        break
                    total_attempts += 1
                    decrypted = self._try_password(path, ext, mutation)
                    if decrypted:
                        return PasswordResult(
                            protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                            success=True,
                            method=CrackMethod.DICTIONARY,
                            password_found=mutation,
                            output_path=decrypted,
                            attempts=total_attempts,
                        )

        # Phase 3: Brute-force
        if self.brute_force_enabled and time.monotonic() < deadline:
            charset = self._get_charset()
            for length in range(1, self.brute_force_max_length + 1):
                if time.monotonic() > deadline:
                    break
                for combo in itertools.product(charset, repeat=length):
                    if time.monotonic() > deadline:
                        break
                    pw = "".join(combo)
                    total_attempts += 1
                    decrypted = self._try_password(path, ext, pw)
                    if decrypted:
                        return PasswordResult(
                            protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                            success=True,
                            method=CrackMethod.BRUTE_FORCE,
                            password_found=pw,
                            output_path=decrypted,
                            attempts=total_attempts,
                        )

        # Phase 4: External tool (john)
        if self._check_john_available() and ext in _PDF_EXTS and time.monotonic() < deadline:
            result = self._try_john(path, deadline)
            if result:
                total_attempts += 1
                return PasswordResult(
                    protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                    success=True,
                    method=CrackMethod.EXTERNAL_TOOL,
                    password_found=result,
                    output_path=self._decrypt_pdf(path, result),
                    attempts=total_attempts,
                )

        # Phase 5: Hashcat (GPU-accelerated or CPU fallback)
        if self.hashcat_enabled and time.monotonic() < deadline:
            hashcat_pw = self._try_hashcat(path, ext)
            if hashcat_pw:
                total_attempts += 1
                hp = self._get_hashcat_path()
                if hp == "host":
                    method = CrackMethod.HASHCAT_HOST
                elif self._gpu_info and self._gpu_info.execution_path == "container":
                    method = CrackMethod.HASHCAT_GPU
                else:
                    method = CrackMethod.HASHCAT_CPU
                decrypted = self._try_password(path, ext, hashcat_pw)
                if decrypted:
                    return PasswordResult(
                        protection_type=ProtectionType.ENCRYPTED_DECRYPTED,
                        success=True,
                        method=method,
                        password_found=hashcat_pw,
                        output_path=decrypted,
                        attempts=total_attempts,
                    )

        return PasswordResult(
            protection_type=ProtectionType.ENCRYPTED_FAILED,
            success=False,
            error=f"Unable to decrypt after {total_attempts} attempts",
            attempts=total_attempts,
        )

    def _try_password(self, path: Path, ext: str, password: str) -> Path | None:
        """Try a single password. Returns decrypted path or None."""
        try:
            if ext in _PDF_EXTS:
                return self._decrypt_pdf(path, password)
            elif ext in _OOXML_EXTS or ext in _LEGACY_OFFICE_EXTS:
                return self._decrypt_office(path, password)
        except Exception:
            return None
        return None

    def _decrypt_pdf(self, path: Path, password: str) -> Path | None:
        """Decrypt a PDF with the given password."""
        import pikepdf

        out_path = self._temp_path(path)
        try:
            pdf = pikepdf.open(path, password=password)
            pdf.save(out_path)
            pdf.close()
            return out_path
        except pikepdf.PasswordError:
            # Clean up failed attempt
            if out_path.exists():
                out_path.unlink()
            return None

    def _decrypt_office(self, path: Path, password: str) -> Path | None:
        """Decrypt an Office file (OOXML or legacy) with the given password."""
        import msoffcrypto

        out_path = self._temp_path(path)
        try:
            with open(path, "rb") as f:
                file = msoffcrypto.OfficeFile(f)
                file.load_key(password=password)
                with open(out_path, "wb") as out:
                    file.decrypt(out)
            return out_path
        except Exception:
            if out_path.exists():
                out_path.unlink()
            return None

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _temp_path(self, original: Path) -> Path:
        """Create a temp file path preserving the original extension."""
        fd, tmp = tempfile.mkstemp(suffix=original.suffix, prefix="mf_pw_")
        os.close(fd)
        return Path(tmp)

    def _mutations(self, password: str) -> list[str]:
        """Generate common password mutations."""
        mutations = []
        if password:
            mutations.append(password.capitalize())
            mutations.append(password.upper())
            mutations.append(password + "1")
            mutations.append(password + "!")
            mutations.append(password + "123")
            mutations.append(password + "2024")
            mutations.append(password + "2025")
            mutations.append(password + "2026")
        return mutations

    def _get_charset(self) -> str:
        """Get character set for brute-force based on config."""
        if self.brute_force_charset == "numeric":
            return string.digits
        elif self.brute_force_charset == "alpha":
            return string.ascii_lowercase
        elif self.brute_force_charset == "alphanumeric":
            return string.ascii_lowercase + string.digits
        elif self.brute_force_charset == "all_printable":
            return string.printable.strip()
        return string.ascii_lowercase + string.digits

    def _try_john(self, path: Path, deadline: float) -> str | None:
        """Try John the Ripper for PDF password cracking."""
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            return None

        try:
            # Extract hash using pdf2john (bundled with john)
            hash_result = subprocess.run(
                ["pdf2john", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            if hash_result.returncode != 0 or not hash_result.stdout.strip():
                return None

            # Write hash to temp file
            hash_file = self._temp_path(Path("hash.txt"))
            hash_file.write_text(hash_result.stdout.strip())

            # Run john with timeout
            john_result = subprocess.run(
                ["john", "--wordlist=" + str(_WORDLIST_DIR / "common.txt"), str(hash_file)],
                capture_output=True, text=True, timeout=min(remaining, 120),
            )

            # Check result
            show_result = subprocess.run(
                ["john", "--show", str(hash_file)],
                capture_output=True, text=True, timeout=10,
            )

            # Clean up hash file
            hash_file.unlink(missing_ok=True)

            # Parse: format is "filename:password"
            for line in show_result.stdout.splitlines():
                if ":" in line and not line.startswith("0 password"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        return parts[1]

        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass

        return None

    # ── Hashcat GPU-accelerated cracking ─────────────────────────────────

    def _get_hashcat_path(self) -> str:
        """Resolve hashcat execution path (lazy, cached)."""
        if self._hashcat_path is not None:
            return self._hashcat_path
        if not self.hashcat_enabled:
            self._hashcat_path = "none"
            return "none"
        try:
            from core.gpu_detector import get_gpu_info
            self._gpu_info = get_gpu_info()
            self._hashcat_path = self._gpu_info.execution_path
        except Exception:
            self._hashcat_path = "none"
        return self._hashcat_path

    def _try_hashcat(self, path: Path, ext: str) -> str | None:
        """Try hashcat cracking. Returns password or None."""
        hp = self._get_hashcat_path()
        if hp == "none":
            return None

        hash_file = self._extract_hash_for_hashcat(path, ext)
        if not hash_file:
            return None

        hash_mode = self._get_hashcat_mode(ext)
        if not hash_mode:
            hash_file.unlink(missing_ok=True)
            return None

        try:
            if hp in ("container", "container_cpu"):
                return self._hashcat_container(hash_file, hash_mode)
            elif hp == "host":
                return self._hashcat_host(hash_file, hash_mode, path, ext)
        except Exception as exc:
            log.warning("hashcat_attack_error", error=str(exc))
        finally:
            hash_file.unlink(missing_ok=True)
        return None

    def _extract_hash_for_hashcat(self, path: Path, ext: str) -> Path | None:
        """Extract hash file for hashcat using john's *2john tools."""
        try:
            if ext in _PDF_EXTS:
                tool = "pdf2john"
            elif ext in (".docx", ".xlsx", ".pptx"):
                tool = "office2john"
            elif ext in (".doc", ".xls", ".ppt"):
                tool = "office2john"
            else:
                return None

            # Try the tool (bundled with john)
            result = subprocess.run(
                [tool, str(path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                # Try perl script variant
                for variant in [f"/usr/share/john/{tool}.pl", f"/usr/share/john/{tool}"]:
                    if Path(variant).exists():
                        result = subprocess.run(
                            ["perl", variant, str(path)],
                            capture_output=True, text=True, timeout=30,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            break
                else:
                    return None

            if not result.stdout.strip():
                return None

            hash_path = self._temp_path(Path("hash.txt"))
            hash_path.write_text(result.stdout.strip())
            return hash_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _get_hashcat_mode(self, ext: str) -> int | None:
        """Map file extension to hashcat -m mode."""
        # Common modes — actual mode depends on encryption version
        modes = {
            ".pdf": 10500,     # PDF 1.4-1.6 (RC4/AES)
            ".docx": 9600,     # MS Office 2013+ (AES-256)
            ".xlsx": 9600,
            ".pptx": 9600,
            ".doc": 9700,      # MS Office 97-03 (RC4)
            ".xls": 9700,
            ".ppt": 9700,
        }
        return modes.get(ext)

    def _build_hashcat_mask(self) -> str:
        """Build hashcat mask from charset settings."""
        charset_map = {
            "numeric": "?d",
            "alpha": "?l",
            "alphanumeric": "?a",
            "all_printable": "?a",
        }
        char = charset_map.get(self.brute_force_charset, "?a")
        length = min(self.brute_force_max_length, 8)
        return char * length

    def _hashcat_container(self, hash_file: Path, hash_mode: int) -> str | None:
        """Run hashcat directly inside the container."""
        potfile = self._temp_path(Path("pot.txt"))
        outfile = self._temp_path(Path("out.txt"))
        workload = int(self._settings.get("password_hashcat_workload", "3"))
        mask = self._build_hashcat_mask()

        cmd = [
            "hashcat", "-m", str(hash_mode), "-a", "3",
            "--potfile-path", str(potfile), "-o", str(outfile),
            "--force", "--runtime", str(self.timeout_seconds),
            "--quiet", "-w", str(workload),
            str(hash_file), mask,
        ]

        log.info("hashcat.container_starting", mode=hash_mode)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_seconds + 30,
            )
            password = self._read_hashcat_result(outfile, potfile)
            if password:
                log.info("hashcat.container_cracked")
            return password
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        finally:
            potfile.unlink(missing_ok=True)
            outfile.unlink(missing_ok=True)

    def _hashcat_host(self, hash_file: Path, hash_mode: int, source_file: Path, ext: str) -> str | None:
        """Delegate to host worker via shared queue volume."""
        import shutil as shutil_mod

        queue_dir = self._hashcat_queue_dir
        job_id = f"pw_{secrets.token_hex(4)}"

        for d in ["hashes", "jobs", "results"]:
            (queue_dir / d).mkdir(parents=True, exist_ok=True)

        # Copy hash to shared volume
        queue_hash = queue_dir / "hashes" / f"{job_id}.hash"
        shutil_mod.copy2(hash_file, queue_hash)

        # Write job file
        workload = int(self._settings.get("password_hashcat_workload", "3"))
        job = {
            "job_id": job_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hash_file": f"hashes/{job_id}.hash",
            "hash_mode": hash_mode,
            "attack_mode": 3,
            "mask": self._build_hashcat_mask(),
            "workload_profile": workload,
            "timeout_seconds": self.timeout_seconds,
            "source_file": source_file.name,
            "format": ext,
        }
        job_file = queue_dir / "jobs" / f"{job_id}.json"
        job_file.write_text(_json.dumps(job, indent=2))
        log.info("hashcat.host_job_submitted", job_id=job_id, file=source_file.name)

        # Poll for result
        result_file = queue_dir / "results" / f"{job_id}.json"
        max_wait = self.timeout_seconds + 120
        elapsed = 0.0

        while elapsed < max_wait:
            time.sleep(1.0)
            elapsed += 1.0
            if result_file.exists():
                try:
                    result = _json.loads(result_file.read_text())
                    result_file.unlink(missing_ok=True)
                    if result.get("status") == "cracked" and result.get("password"):
                        log.info("hashcat.host_cracked", job_id=job_id,
                                 backend=result.get("backend"),
                                 duration=result.get("duration_seconds"))
                        return result["password"]
                    log.info("hashcat.host_completed", job_id=job_id,
                             status=result.get("status"))
                    return None
                except (_json.JSONDecodeError, OSError):
                    continue

        # Timeout — cleanup stale files
        log.warning("hashcat.host_timeout", job_id=job_id)
        job_file.unlink(missing_ok=True)
        queue_hash.unlink(missing_ok=True)
        return None

    @staticmethod
    def _read_hashcat_result(outfile: Path, potfile: Path) -> str | None:
        """Read cracked password from hashcat output or potfile."""
        for f in [outfile, potfile]:
            try:
                if f.exists() and f.stat().st_size > 0:
                    for line in f.read_text().strip().splitlines():
                        if ":" in line:
                            return line.split(":")[-1]
            except OSError:
                pass
        return None

    def cleanup_temp_file(self, result: PasswordResult) -> None:
        """Delete the temp decrypted file after conversion is complete."""
        if result.output_path and result.output_path != result.output_path:
            # Only delete temp files (those in system temp dir)
            try:
                tmp_dir = Path(tempfile.gettempdir())
                if result.output_path.parent == tmp_dir or str(result.output_path).startswith(str(tmp_dir)):
                    result.output_path.unlink(missing_ok=True)
            except Exception:
                pass
