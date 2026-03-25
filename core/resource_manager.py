"""
core/resource_manager.py

Applies CPU and process priority settings to the running MarkFlow process.
Settings are stored in the existing user_preferences table via _PREFERENCE_SCHEMA.
Applied at startup and whenever an admin changes them via PUT /api/admin/resources.

Notes:
- CPU affinity pins which cores the entire process (and its threads) can use.
- Process priority uses OS nice levels: low=10, normal=0, high=-10.
  Negative nice requires root. In Docker, MarkFlow typically runs as root.
  If setpriority fails, log a warning and continue — don't crash.
- In Docker, the container may have CPU limits set externally (e.g. --cpus flag).
  Those limits take precedence over affinity. We report both in the metrics endpoint.
"""

import os

import psutil
import structlog

log = structlog.get_logger(__name__)
_proc = psutil.Process(os.getpid())

PRIORITY_NICE = {"low": 10, "normal": 0, "high": -10}


def get_cpu_info() -> dict:
    """Return static CPU topology. Called once at startup and cached."""
    return {
        "logical_count": psutil.cpu_count(logical=True),
        "physical_count": psutil.cpu_count(logical=False),
        "current_affinity": _get_affinity(),
        "docker_cpu_limit": _get_docker_cpu_limit(),
    }


def _get_affinity() -> list[int]:
    try:
        return sorted(_proc.cpu_affinity())
    except (AttributeError, psutil.AccessDenied, OSError):
        # cpu_affinity not available on all platforms (macOS Docker)
        return list(range(psutil.cpu_count(logical=True)))


def _get_docker_cpu_limit() -> float | None:
    """Read CFS quota from /sys/fs/cgroup — returns effective CPUs or None."""
    # cgroup v1
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read().strip())
        if quota > 0:
            return round(quota / period, 2)
    except Exception:
        pass
    # cgroup v2
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            data = f.read().strip().split()
        if data[0] != "max":
            return round(int(data[0]) / int(data[1]), 2)
    except Exception:
        pass
    return None


def apply_affinity(core_indices: list[int]) -> bool:
    """
    Pin the process to the specified cores.
    core_indices: list of 0-based CPU indices. Empty list = use all cores.
    Returns True on success, False if not supported (macOS, some containers).
    """
    if not core_indices:
        core_indices = list(range(psutil.cpu_count(logical=True)))

    try:
        _proc.cpu_affinity(core_indices)
        log.info("cpu_affinity_applied", cores=core_indices)
        return True
    except (AttributeError, psutil.AccessDenied, OSError) as e:
        log.warning("cpu_affinity_failed", reason=str(e))
        return False


def apply_priority(level: str) -> bool:
    """
    Set process nice level. level: 'low' | 'normal' | 'high'.
    Returns True on success. Logs warning and returns False if permission denied.
    """
    nice = PRIORITY_NICE.get(level)
    if nice is None:
        log.warning("process_priority_invalid", level=level)
        return False
    try:
        _proc.nice(nice)
        log.info("process_priority_applied", level=level, nice=nice)
        return True
    except (psutil.AccessDenied, PermissionError, OSError) as e:
        log.warning("process_priority_failed", level=level, reason=str(e))
        return False


def get_live_metrics() -> dict:
    """
    Returns a snapshot of current resource usage.
    Safe to call every 2 seconds — all reads are non-blocking.
    """
    per_cpu = psutil.cpu_percent(interval=None, percpu=True)
    mem = psutil.virtual_memory()

    return {
        "cpu_per_core": per_cpu,
        "cpu_total_pct": round(sum(per_cpu) / max(len(per_cpu), 1), 1),
        "cpu_affinity": _get_affinity(),
        "mem_total_mb": round(mem.total / 1024 / 1024),
        "mem_used_mb": round(mem.used / 1024 / 1024),
        "mem_available_mb": round(mem.available / 1024 / 1024),
        "mem_pct": mem.percent,
        "thread_count": _proc.num_threads(),
        "docker_cpu_limit": _get_docker_cpu_limit(),
    }


# Cached CPU info — doesn't change while running
_cpu_info_cache: dict | None = None


def get_cpu_info_cached() -> dict:
    global _cpu_info_cache
    if _cpu_info_cache is None:
        _cpu_info_cache = get_cpu_info()
    return _cpu_info_cache
