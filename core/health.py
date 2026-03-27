"""
System health checks — verifies all required external dependencies at startup.

HealthChecker.check_all() returns a dict with per-dependency status.
Called by the /api/health endpoint and during app lifespan startup.

run_health_check() — reusable entry point returning a structured JSON response
for both the startup lifespan and the /debug/api/health endpoint.

Checks:
  - Tesseract OCR (version, path)
  - LibreOffice headless (available for .doc→.docx and chart export)
  - Poppler / pdftoppm (for pdf2image)
  - WeasyPrint (importable; sets fallback flag if not)
  - Disk space (warn if < 1GB free)
  - SQLite DB (file accessible, size)
"""

import asyncio
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Disk space warning threshold: 1 GB
DISK_WARN_BYTES = 1 * 1024 * 1024 * 1024

# Track app start time for uptime calculation
_APP_START_TIME = time.monotonic()


class HealthChecker:
    """Checks availability of all system dependencies required by MarkFlow."""

    async def check_all(self) -> dict:
        """Run all checks concurrently and return combined status dict."""
        results = await asyncio.gather(
            self._check_tesseract(),
            self._check_libreoffice(),
            self._check_poppler(),
            self._check_weasyprint(),
            self._check_disk_space(),
            self._check_database(),
            self._check_meilisearch(),
            self._check_drives(),
            return_exceptions=True,
        )
        keys = ["tesseract", "libreoffice", "poppler", "weasyprint", "disk", "database", "meilisearch", "drives"]
        out = {}
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                out[key] = {"ok": False, "error": str(result)}
            else:
                out[key] = result
        return out

    # ── Individual checks ─────────────────────────────────────────────────────

    async def _check_tesseract(self) -> dict:
        return await asyncio.to_thread(self._sync_check_tesseract)

    def _sync_check_tesseract(self) -> dict:
        path = shutil.which("tesseract")
        if not path:
            return {"ok": False, "error": "tesseract not found in PATH"}
        try:
            import subprocess
            result = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True, text=True, timeout=10
            )
            version_line = (result.stdout or result.stderr or "").splitlines()
            version = version_line[0].strip() if version_line else "unknown"
            return {"ok": True, "path": path, "version": version}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    async def _check_libreoffice(self) -> dict:
        return await asyncio.to_thread(self._sync_check_libreoffice)

    def _sync_check_libreoffice(self) -> dict:
        # Try multiple common binary names
        for binary in ("libreoffice", "soffice"):
            path = shutil.which(binary)
            if path:
                return {"ok": True, "path": path, "binary": binary}
        return {"ok": False, "error": "libreoffice / soffice not found in PATH"}

    async def _check_poppler(self) -> dict:
        return await asyncio.to_thread(self._sync_check_poppler)

    def _sync_check_poppler(self) -> dict:
        path = shutil.which("pdftoppm")
        if not path:
            return {"ok": False, "error": "pdftoppm (poppler) not found in PATH"}
        try:
            import subprocess
            result = subprocess.run(
                ["pdftoppm", "-v"],
                capture_output=True, text=True, timeout=10
            )
            version_line = (result.stderr or result.stdout or "").splitlines()
            version = version_line[0].strip() if version_line else "unknown"
            return {"ok": True, "path": path, "version": version}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    async def _check_weasyprint(self) -> dict:
        return await asyncio.to_thread(self._sync_check_weasyprint)

    def _sync_check_weasyprint(self) -> dict:
        try:
            import weasyprint
            version = getattr(weasyprint, "__version__", "unknown")
            return {"ok": True, "version": version}
        except ImportError as e:
            log.warning("health.weasyprint_unavailable", error=str(e))
            return {
                "ok": False,
                "error": str(e),
                "fallback": "fpdf2",
                "note": "PDF export will use fpdf2 fallback",
            }

    async def _check_disk_space(self) -> dict:
        return await asyncio.to_thread(self._sync_check_disk_space)

    def _sync_check_disk_space(self) -> dict:
        try:
            stat = shutil.disk_usage(".")
            free_gb = stat.free / (1024 ** 3)
            total_gb = stat.total / (1024 ** 3)
            used_gb = (stat.total - stat.free) / (1024 ** 3)
            ok = stat.free >= DISK_WARN_BYTES
            return {
                "ok": ok,
                "free_gb": round(free_gb, 2),
                "used_gb": round(used_gb, 2),
                "total_gb": round(total_gb, 2),
                "warning": None if ok else f"Low disk space: {free_gb:.1f} GB free",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _check_database(self) -> dict:
        return await asyncio.to_thread(self._sync_check_database)

    def _sync_check_database(self) -> dict:
        from core.database import DB_PATH
        try:
            parent = DB_PATH.parent
            parent.mkdir(parents=True, exist_ok=True)
            # Check writeable
            test_file = parent / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
            return {
                "ok": True,
                "path": str(DB_PATH),
                "size_bytes": size_bytes,
                "size_kb": round(size_bytes / 1024, 1),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


    async def _check_drives(self) -> dict:
        return await asyncio.to_thread(self._sync_check_drives)

    def _sync_check_drives(self) -> dict:
        raw = os.getenv("MOUNTED_DRIVES", "")
        letters = [l.strip().lower() for l in raw.split(",") if l.strip()] if raw else []
        mounted = []
        unmounted = []
        for letter in letters:
            host_path = Path(f"/host/{letter}")
            accessible = False
            try:
                if host_path.is_dir():
                    os.listdir(host_path)
                    accessible = True
            except (PermissionError, OSError):
                pass
            if accessible:
                mounted.append({"letter": letter.upper(), "path": f"/host/{letter}", "accessible": True})
            else:
                unmounted.append(letter.upper())
        all_ok = len(mounted) > 0 or len(letters) == 0
        return {
            "ok": all_ok,
            "status": "ok" if all_ok else "no_drives",
            "mounted": mounted,
            "unmounted": unmounted,
        }

    async def _check_meilisearch(self) -> dict:
        try:
            from core.search_client import get_meili_client, MEILI_HOST
            client = get_meili_client()
            available = await client.health_check()
            if not available:
                return {"ok": False, "status": "not_available", "host": MEILI_HOST}
            docs_stats = await client.get_index_stats("documents")
            adobe_stats = await client.get_index_stats("adobe-files")
            return {
                "ok": True,
                "status": "ok",
                "host": MEILI_HOST,
                "documents_index_count": docs_stats.get("numberOfDocuments", 0),
                "adobe_index_count": adobe_stats.get("numberOfDocuments", 0),
            }
        except Exception as e:
            return {"ok": False, "status": "not_available", "error": str(e)}


async def run_health_check() -> dict:
    """
    Reusable health check entry point.

    Returns a JSON-serializable dict with status, uptime, timestamp,
    and per-component health. Used by both the startup lifespan and
    the /debug/api/health endpoint.
    """
    checker = HealthChecker()
    components = await checker.check_all()

    # GPU info (re-reads host worker capabilities for live status)
    try:
        from core.gpu_detector import get_gpu_info_live
        gpu = get_gpu_info_live()
        components["gpu"] = {
            "execution_path": gpu.execution_path,
            "container_gpu": {
                "available": gpu.container_gpu_available,
                "vendor": gpu.container_gpu_vendor,
                "name": gpu.container_gpu_name,
                "vram_mb": gpu.container_gpu_vram_mb,
                "hashcat_backend": gpu.container_hashcat_backend,
            },
            "host_worker": {
                "available": gpu.host_worker_available,
                "vendor": gpu.host_worker_gpu_vendor,
                "name": gpu.host_worker_gpu_name,
                "vram_mb": gpu.host_worker_gpu_vram_mb,
                "backend": gpu.host_worker_gpu_backend,
            },
            "effective_gpu": gpu.effective_gpu_name,
            "effective_backend": gpu.effective_backend,
        }
    except Exception:
        components["gpu"] = {"execution_path": "none", "error": "detection_failed"}

    all_ok = all(
        c.get("ok", False) for k, c in components.items()
        if k != "gpu" and isinstance(c, dict)
    )
    uptime_seconds = int(time.monotonic() - _APP_START_TIME)

    return {
        "status": "ok" if all_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "components": components,
    }
