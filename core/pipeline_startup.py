"""
Pipeline startup health gate.

Waits for all critical services to be ready before triggering the initial
scan+convert+index cycle. Designed for headless deployment — the app starts
serving immediately, but the pipeline waits until dependencies are stable.

The configurable delay (default 5 min) acts as a minimum wait to let the
system stabilize after deployment. After the delay, health checks are polled
until all critical services pass.
"""

import asyncio
from datetime import datetime, timezone

import structlog

from core.database import get_preference
from core.health import HealthChecker

log = structlog.get_logger(__name__)

# Critical services that must be healthy before the pipeline starts.
# Non-critical services (GPU, WeasyPrint) are allowed to be absent.
CRITICAL_SERVICES = {"database", "disk"}
# Services we want but can proceed without (with a warning)
PREFERRED_SERVICES = {"meilisearch", "tesseract", "libreoffice"}


async def wait_for_health_and_start_pipeline() -> None:
    """Health-gated pipeline startup.

    1. Wait the configured startup delay (min wait for system stabilization)
    2. Poll health checks until critical services are ready
    3. Trigger the initial scan+convert cycle
    """
    try:
        delay_str = await get_preference("pipeline_startup_delay_minutes") or "5"
        delay_minutes = max(1, int(delay_str))
    except (ValueError, TypeError):
        delay_minutes = 5

    log.info(
        "pipeline.startup_gate_begin",
        delay_minutes=delay_minutes,
        critical_services=list(CRITICAL_SERVICES),
    )

    # Phase 1: Minimum stabilization delay
    await asyncio.sleep(delay_minutes * 60)

    # Phase 2: Poll health until critical services pass
    checker = HealthChecker()
    max_retries = 12  # 12 x 15s = 3 more minutes max
    retry_interval = 15

    for attempt in range(1, max_retries + 1):
        health = await checker.check_all()

        critical_ok = all(
            health.get(svc, {}).get("ok", False) for svc in CRITICAL_SERVICES
        )
        preferred_status = {
            svc: health.get(svc, {}).get("ok", False) for svc in PREFERRED_SERVICES
        }
        preferred_missing = [s for s, ok in preferred_status.items() if not ok]

        if critical_ok:
            if preferred_missing:
                log.warning(
                    "pipeline.startup_preferred_services_unavailable",
                    missing=preferred_missing,
                    message="Pipeline starting without these services. Some features may be limited.",
                )
            log.info(
                "pipeline.startup_health_gate_passed",
                attempt=attempt,
                total_wait_minutes=round(delay_minutes + (attempt - 1) * retry_interval / 60, 1),
            )
            break
        else:
            failed = [s for s in CRITICAL_SERVICES if not health.get(s, {}).get("ok", False)]
            log.warning(
                "pipeline.startup_health_gate_waiting",
                attempt=attempt,
                max_retries=max_retries,
                failed_services=failed,
                retry_in_seconds=retry_interval,
            )
            if attempt < max_retries:
                await asyncio.sleep(retry_interval)
    else:
        # Exhausted retries — start anyway with a prominent error
        log.error(
            "pipeline.startup_health_gate_timeout",
            message=(
                "Critical services did not become healthy within the timeout. "
                "Pipeline is starting anyway — some operations may fail. "
                "Check service configuration and logs."
            ),
            total_wait_minutes=round(delay_minutes + max_retries * retry_interval / 60, 1),
        )

    # Phase 3: Trigger initial scan+convert cycle
    log.info("pipeline.initial_cycle_starting")
    try:
        from core.scheduler import run_lifecycle_scan
        await run_lifecycle_scan(force=True)
        log.info("pipeline.initial_cycle_complete")
    except Exception as exc:
        log.error("pipeline.initial_cycle_failed", error=str(exc))

    # Phase 4: Fire initial disk snapshot
    try:
        from core.metrics_collector import collect_disk_snapshot
        await collect_disk_snapshot()
    except Exception:
        pass
