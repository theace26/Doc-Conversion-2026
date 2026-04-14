"""
LLM image analysis queue worker.

APScheduler job (5-min interval). Each drain cycle:
  1. Check analysis_enabled preference
  2. Yield to active bulk jobs
  3. Verify active LLM provider supports vision
  4. Claim up to analysis_batch_size pending rows
  5. Call VisionAdapter.describe_batch() — one API call for all images
  6. Write results; re-index completed files in Meilisearch
"""

from pathlib import Path

import structlog

from core.db.catalog import get_active_provider
from core.db.preferences import get_preference
from core.db.analysis import claim_pending_batch, write_batch_results
from core.bulk_worker import get_all_active_jobs

log = structlog.get_logger(__name__)


async def run_analysis_drain() -> None:
    """Drain one batch from analysis_queue. Called by APScheduler every 5 minutes."""
    try:
        enabled = await get_preference("analysis_enabled") or "true"
        if enabled == "false":
            log.debug("analysis_worker.disabled")
            return

        active = await get_all_active_jobs()
        if any(j["status"] in ("scanning", "running") for j in active):
            log.debug("analysis_worker.skipped_bulk_job_active")
            return

        provider_config = await get_active_provider()
        if not provider_config:
            log.debug("analysis_worker.no_active_provider")
            return

        from core.vision_adapter import VisionAdapter
        adapter = VisionAdapter(provider_config)
        if not adapter.supports_vision():
            log.debug("analysis_worker.provider_no_vision", provider=provider_config.get("provider"))
            return

        paused = await get_preference("analysis_submission_paused") or "false"
        if paused == "true":
            log.info("analysis_worker.paused_by_user")
            return

        batch_size_str = await get_preference("analysis_batch_size") or "10"
        batch_size = max(1, min(int(batch_size_str), 20))
        rows = await claim_pending_batch(batch_size)
        if not rows:
            return

        log.info(
            "analysis_worker.batch_start",
            count=len(rows),
            provider=provider_config.get("provider"),
            model=provider_config.get("model"),
        )

        # Skip files no longer on disk
        valid_rows, skip_results = [], []
        for row in rows:
            if Path(row["source_path"]).exists():
                valid_rows.append(row)
            else:
                skip_results.append({"id": row["id"], "error": "source file not found on disk"})
        if skip_results:
            await write_batch_results(skip_results)
        if not valid_rows:
            return

        image_paths = [Path(r["source_path"]) for r in valid_rows]
        descriptions = await adapter.describe_batch(image_paths)

        results = []
        for i, row in enumerate(valid_rows):
            desc = descriptions[i] if i < len(descriptions) else None
            if desc and not desc.error:
                results.append({
                    "id": row["id"],
                    "description": desc.description,
                    "extracted_text": desc.extracted_text,
                    "provider_id": provider_config.get("provider"),
                    "model": provider_config.get("model"),
                    "tokens_used": desc.tokens_used,
                })
            else:
                results.append({
                    "id": row["id"],
                    "error": (desc.error if desc else "no result returned"),
                })

        await write_batch_results(results)

        completed = sum(1 for r in results if not r.get("error"))
        failed = sum(1 for r in results if r.get("error"))
        log.info("analysis_worker.batch_complete", completed=completed, failed=failed)

        if completed > 0:
            await _reindex_completed(valid_rows, results)

    except Exception as exc:
        # v0.22.14: SQLite lock contention is transient — downgrade to a
        # warning and let the next scheduled drain retry naturally.
        err = str(exc)
        if "database is locked" in err.lower():
            log.warning("analysis_worker.drain_db_locked_skip", error=err)
        else:
            log.error("analysis_worker.drain_failed", error=err)


async def _reindex_completed(rows: list[dict], results: list[dict]) -> None:
    """Re-index Meilisearch for files whose analysis just completed."""
    try:
        from core.search_indexer import get_search_indexer
        from core.db.connection import db_fetch_one

        indexer = get_search_indexer()
        if not indexer:
            return

        completed_paths = {
            rows[i]["source_path"]
            for i, r in enumerate(results)
            if not r.get("error")
        }

        for source_path in completed_paths:
            try:
                row = await db_fetch_one(
                    "SELECT output_path FROM source_files WHERE source_path = ?",
                    (source_path,),
                )
                if row and row.get("output_path"):
                    md_path = Path(row["output_path"])
                    if md_path.exists():
                        await indexer.index_document(md_path)
            except Exception as exc:
                log.warning("analysis_worker.reindex_failed", path=source_path, error=str(exc))

    except Exception as exc:
        log.warning("analysis_worker.reindex_error", error=str(exc))
