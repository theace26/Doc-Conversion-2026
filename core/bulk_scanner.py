"""
Bulk file scanner — walks a source directory tree, discovers convertible and
Adobe files, and records them into the bulk_files table with mtime tracking.

Supports incremental processing: unchanged files (same mtime) are skipped.
"""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from core.stop_controller import should_stop
from core.database import get_preference, record_path_issue, update_bulk_file, update_bulk_job_status, upsert_bulk_file
from core.path_utils import PathSafetyResult, run_path_safety_pass

log = structlog.get_logger(__name__)

# All supported extensions — unified scanning (no separate Adobe/convertible split)
SUPPORTED_EXTENSIONS = {
    # Office documents
    ".docx", ".doc",
    ".pdf",
    ".pptx", ".ppt",
    ".xlsx", ".xls",
    ".csv", ".tsv",
    ".rtf",
    # OpenDocument
    ".odt", ".ods", ".odp",
    # Markdown & text
    ".md", ".txt", ".log", ".text",
    # Web & data
    ".html", ".htm", ".xml", ".epub",
    # Email
    ".eml", ".msg",
    # Adobe creative suite
    ".psd", ".ai", ".indd", ".aep", ".prproj", ".xd",
    # Media (audio/video — indexed for metadata/scene detection)
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
    ".webm", ".m4a", ".m4v", ".wmv", ".aac", ".wma",
}

# Backwards-compat aliases (referenced by bulk_worker and other modules)
CONVERTIBLE_EXTENSIONS = SUPPORTED_EXTENSIONS
ADOBE_EXTENSIONS = {".ai", ".psd", ".indd", ".aep", ".prproj", ".xd"}
ALL_SUPPORTED = SUPPORTED_EXTENSIONS


@dataclass
class ScanResult:
    job_id: str
    total_discovered: int = 0
    convertible_count: int = 0
    adobe_count: int = 0
    unrecognized_count: int = 0
    skipped_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    path_too_long_count: int = 0
    collision_count: int = 0
    case_collision_count: int = 0
    path_safety_result: "PathSafetyResult | None" = None
    scan_duration_ms: int = 0


@dataclass
class BulkFileRecord:
    file_id: str
    job_id: str
    source_path: Path
    file_ext: str
    file_size_bytes: int
    source_mtime: float
    status: str = "pending"


class BulkScanner:
    """Walks a source directory and upserts discovered files into bulk_files."""

    def __init__(self, job_id: str, source_path: Path, output_path: Path | None = None, db_path: str = ""):
        self.job_id = job_id
        self.source_path = Path(source_path)
        self.output_path = Path(output_path) if output_path else None
        self._yield_interval = 1000  # yield control every N files

    async def scan(
        self,
        on_progress: Callable[[dict], Awaitable[None]] | None = None,
    ) -> ScanResult:
        """
        Walk source_path recursively. For each supported file:
          1. Check extension
          2. Get mtime and size
          3. Upsert into bulk_files table
          4. Yield control every _yield_interval files
        """
        t_start = time.perf_counter()
        result = ScanResult(job_id=self.job_id)
        file_count = 0
        self._convertible_paths: list[Path] = []

        log.info("bulk_scan_start", job_id=self.job_id, source_path=str(self.source_path))

        # Pre-count files for progress estimation (capped at 10s)
        total_estimate = 0
        try:
            total_estimate = await asyncio.wait_for(
                asyncio.to_thread(self._count_files, self.source_path),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, Exception):
            total_estimate = 0

        # Emit first progress event
        if on_progress:
            await on_progress({
                "event": "scan_progress",
                "job_id": self.job_id,
                "scanned": 0,
                "total": total_estimate,
                "current_file": "",
                "pct": None if total_estimate == 0 else 0,
            })

        progress_interval = 50  # emit every N files

        for dirpath, dirnames, filenames in os.walk(self.source_path):
            # Check global stop before each directory
            if should_stop():
                log.warning("scan_stopped_early", job_id=self.job_id, scanned_so_far=file_count)
                if on_progress:
                    await on_progress({
                        "event": "scan_stopped",
                        "job_id": self.job_id,
                        "scanned": file_count,
                        "reason": "global_stop_requested",
                    })
                break

            # Skip hidden directories and _markflow output dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "_markflow"
            ]

            for filename in filenames:
                file_path = Path(dirpath) / filename
                ext = file_path.suffix.lower()

                # Stat the file
                try:
                    stat = file_path.stat()
                    file_size = stat.st_size
                    mtime = stat.st_mtime
                except OSError as exc:
                    log.warning("bulk_scan_stat_error", path=str(file_path), error=str(exc))
                    continue

                result.total_discovered += 1

                if ext in SUPPORTED_EXTENSIONS:
                    result.convertible_count += 1
                    self._convertible_paths.append(file_path)

                    file_id = await upsert_bulk_file(
                        job_id=self.job_id,
                        source_path=str(file_path),
                        file_ext=ext,
                        file_size_bytes=file_size,
                        source_mtime=mtime,
                    )
                else:
                    # Unrecognized file — catalog with MIME detection
                    result.unrecognized_count += 1
                    await self._record_unrecognized(file_path, ext, file_size, mtime)

                file_count += 1

                # Emit progress every N files
                if on_progress and (file_count % progress_interval == 0):
                    try:
                        rel_path = file_path.relative_to(self.source_path)
                    except ValueError:
                        rel_path = file_path
                    pct = min(99, int(file_count / total_estimate * 100)) if total_estimate > 0 else None
                    await on_progress({
                        "event": "scan_progress",
                        "job_id": self.job_id,
                        "scanned": file_count,
                        "total": total_estimate,
                        "current_file": str(rel_path),
                        "pct": pct,
                    })

                if file_count % self._yield_interval == 0:
                    await asyncio.sleep(0)

        # Emit final progress event
        if on_progress:
            await on_progress({
                "event": "scan_progress",
                "job_id": self.job_id,
                "scanned": file_count,
                "total": total_estimate if total_estimate > 0 else file_count,
                "current_file": "",
                "pct": 99,
            })

        # Count skipped (already converted, unchanged)
        from core.database import get_bulk_file_count
        result.skipped_count = await get_bulk_file_count(self.job_id, status="skipped")
        pending = await get_bulk_file_count(self.job_id, status="pending")
        # new_count + changed_count = pending (we can't distinguish without more state,
        # but pending after upsert means either new or mtime-changed)
        result.new_count = pending  # approximate: all pending are "needs processing"

        # ── Path safety pass ──────────────────────────────────────────────
        if self.output_path and self._convertible_paths:
            result.path_safety_result = await self._run_path_safety_pass(result)

        result.scan_duration_ms = int((time.perf_counter() - t_start) * 1000)

        # Emit scan_complete event
        if on_progress:
            await on_progress({
                "event": "scan_complete",
                "job_id": self.job_id,
                "total_found": file_count,
            })

        log.info(
            "bulk_scan_complete",
            job_id=self.job_id,
            total_discovered=result.total_discovered,
            supported=result.convertible_count,
            unrecognized=result.unrecognized_count,
            skipped=result.skipped_count,
            pending=pending,
            too_long=result.path_too_long_count,
            collisions=result.collision_count,
            case_collisions=result.case_collision_count,
            duration_ms=result.scan_duration_ms,
        )

        return result

    @staticmethod
    def _count_files(source_path: Path) -> int:
        """Count files in the source directory (synchronous, for use in a thread)."""
        count = 0
        for _, dirnames, filenames in os.walk(source_path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_markflow"]
            count += len(filenames)
        return count

    async def _record_unrecognized(
        self, path: Path, ext: str, file_size: int, mtime: float
    ) -> None:
        """Record an unrecognized file with MIME detection."""
        try:
            from core.mime_classifier import classify
            mime_type, category = classify(path)
        except Exception:
            mime_type, category = "application/octet-stream", "unknown"

        file_id = await upsert_bulk_file(
            job_id=self.job_id,
            source_path=str(path),
            file_ext=ext or ".unknown",
            file_size_bytes=file_size,
            source_mtime=mtime,
        )
        # Update the status and MIME fields
        await update_bulk_file(
            file_id,
            status="unrecognized",
            mime_type=mime_type,
            file_category=category,
        )

    async def _run_path_safety_pass(self, scan_result: ScanResult) -> PathSafetyResult:
        """Run path length and collision checks on all convertible files."""
        max_len_str = await get_preference("max_output_path_length") or "240"
        max_len = int(max_len_str)
        strategy_str = await get_preference("collision_strategy") or "rename"
        strategy = strategy_str if strategy_str in ("rename", "skip", "error") else "rename"

        safety = await run_path_safety_pass(
            all_files=self._convertible_paths,
            source_root=self.source_path,
            output_root=self.output_path,
            max_path_length=max_len,
            collision_strategy=strategy,
        )

        scan_result.path_too_long_count = safety.too_long_count
        scan_result.collision_count = safety.collision_count
        scan_result.case_collision_count = safety.case_collision_count

        # Record path issues in DB
        if safety.too_long_count or safety.collision_count or safety.case_collision_count:
            await self._record_path_issues(safety, strategy)

        log.info(
            "path_safety_pass_complete",
            job_id=self.job_id,
            total_checked=safety.total_checked,
            too_long=safety.too_long_count,
            collisions=safety.collision_count,
            case_collisions=safety.case_collision_count,
        )

        for output_path, files in safety.collision_groups.items():
            log.warning(
                "output_collision_detected",
                job_id=self.job_id,
                output_path=output_path,
                source_files=[str(f) for f in files],
                strategy=strategy,
            )

        return safety

    async def _record_path_issues(self, safety: PathSafetyResult, strategy: str) -> None:
        """Persist path issues to bulk_path_issues table and update bulk_files."""
        from core.path_utils import map_output_path

        # Too-long paths
        for f in safety.path_too_long:
            out = map_output_path(f, self.source_path, self.output_path)
            await record_path_issue(
                job_id=self.job_id,
                issue_type="path_too_long",
                source_path=str(f),
                output_path=str(out),
                resolution="skipped",
            )

        # Standard collisions
        for output_path_str, sources in safety.collision_groups.items():
            sorted_sources = sorted(sources, key=lambda p: str(p))
            for src in sorted_sources:
                resolved = safety.resolved_paths.get(str(src))
                resolved_path = resolved[0] if resolved else None
                resolution = resolved[1] if resolved else strategy
                peers = [str(s) for s in sorted_sources if s != src]
                await record_path_issue(
                    job_id=self.job_id,
                    issue_type="collision",
                    source_path=str(src),
                    output_path=output_path_str,
                    collision_group=output_path_str,
                    collision_peer=peers[0] if peers else None,
                    resolution=resolution,
                    resolved_path=resolved_path,
                )

        # Case collisions
        for lower_path, sources in safety.case_collision_groups.items():
            sorted_sources = sorted(sources, key=lambda p: str(p))
            for src in sorted_sources:
                resolved = safety.resolved_paths.get(str(src))
                resolved_path = resolved[0] if resolved else None
                resolution = resolved[1] if resolved else strategy
                peers = [str(s) for s in sorted_sources if s != src]
                await record_path_issue(
                    job_id=self.job_id,
                    issue_type="case_collision",
                    source_path=str(src),
                    output_path=lower_path,
                    collision_group=lower_path,
                    collision_peer=peers[0] if peers else None,
                    resolution=resolution,
                    resolved_path=resolved_path,
                )

        # Update job counters
        await update_bulk_job_status(
            self.job_id, "scanning",
            path_too_long_count=safety.too_long_count,
            collision_count=safety.collision_count,
            case_collision_count=safety.case_collision_count,
        )
