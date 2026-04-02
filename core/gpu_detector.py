"""
GPU detection for hashcat password cracking — dual-path architecture.

Probes two paths:
  1. Container-visible GPU (NVIDIA only on Docker/WSL2 via Container Toolkit)
  2. Host worker capabilities (AMD/Intel/NVIDIA/Apple — reported via shared volume)

Resolution priority: NVIDIA container > host worker > hashcat CPU > none
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_HOST_WORKER_REPORT = Path("/mnt/hashcat-queue/worker_capabilities.json")
_HOST_WORKER_LOCK = Path("/mnt/hashcat-queue/worker.lock")
_WORKER_STALE_SECONDS = 300  # 5 minutes — worker heartbeats every 2 min


@dataclass
class GPUInfo:
    """Detected GPU hardware and software capabilities."""
    # Container-visible GPU (NVIDIA only on Docker/WSL2)
    container_gpu_available: bool = False
    container_gpu_vendor: str = "none"
    container_gpu_name: str = ""
    container_gpu_vram_mb: int = 0
    container_gpu_driver: str = ""
    container_cuda_version: Optional[str] = None
    container_hashcat_available: bool = False
    container_hashcat_backend: Optional[str] = None

    # Host worker GPU (any vendor — reported by host worker)
    host_worker_available: bool = False
    host_worker_gpu_vendor: str = "none"
    host_worker_gpu_name: str = ""
    host_worker_gpu_vram_mb: int = 0
    host_worker_gpu_backend: Optional[str] = None
    host_worker_hashcat_version: Optional[str] = None

    # Resolved execution path
    execution_path: str = "none"  # "container", "host", "container_cpu", "none"
    effective_gpu_name: str = ""
    effective_backend: str = ""


_gpu_info: Optional[GPUInfo] = None


def _read_host_worker_report() -> dict | None:
    """
    Read worker_capabilities.json and return its contents, or None if the
    worker is not running or its report is stale.

    Liveness checks (both must pass):
      1. worker.lock exists — worker wrote it at startup, removes it on clean exit
      2. capabilities timestamp is within _WORKER_STALE_SECONDS — catches ungraceful
         exits (power-off, crash) where the lock file was never cleaned up
    """
    if not _HOST_WORKER_LOCK.exists():
        return None
    if not _HOST_WORKER_REPORT.exists():
        return None
    try:
        report = json.loads(_HOST_WORKER_REPORT.read_text(encoding="utf-8-sig"))
        ts_raw = report.get("timestamp")
        if ts_raw:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > _WORKER_STALE_SECONDS:
                log.warning("gpu.host_worker_stale",
                            age_seconds=int(age),
                            threshold=_WORKER_STALE_SECONDS)
                return None
        return report
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def detect_gpu() -> GPUInfo:
    """Probe for GPU hardware from both container and host paths."""
    global _gpu_info
    info = GPUInfo()

    # ── Container-visible GPU (NVIDIA only) ──────────────────────────────
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 3:
                    info.container_gpu_available = True
                    info.container_gpu_vendor = "nvidia"
                    info.container_gpu_name = parts[0].strip()
                    info.container_gpu_vram_mb = int(float(parts[1].strip()))
                    info.container_gpu_driver = parts[2].strip()
                    log.info("gpu.container_nvidia_detected",
                             name=info.container_gpu_name,
                             vram_mb=info.container_gpu_vram_mb)
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass

    # Check CUDA version
    if info.container_gpu_vendor == "nvidia" and shutil.which("nvcc"):
        try:
            result = subprocess.run(
                ["nvcc", "--version"], capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if "release" in line.lower():
                    info.container_cuda_version = line.split("release")[-1].split(",")[0].strip()
                    break
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Check hashcat inside container
    info.container_hashcat_available = shutil.which("hashcat") is not None
    if info.container_hashcat_available:
        info.container_hashcat_backend = _probe_hashcat_backend()

    # ── Host worker capabilities ─────────────────────────────────────────
    report = _read_host_worker_report()
    if report is not None:
        info.host_worker_available = report.get("available", False)
        info.host_worker_gpu_vendor = report.get("gpu_vendor", "none")
        info.host_worker_gpu_name = report.get("gpu_name", "")
        info.host_worker_gpu_vram_mb = report.get("gpu_vram_mb", 0)
        info.host_worker_gpu_backend = report.get("hashcat_backend")
        info.host_worker_hashcat_version = report.get("hashcat_version")
        if info.host_worker_available:
            log.info("gpu.host_worker_detected",
                     vendor=info.host_worker_gpu_vendor,
                     name=info.host_worker_gpu_name,
                     backend=info.host_worker_gpu_backend)

    # ── Resolve execution path ───────────────────────────────────────────
    _gpu_backends = ("CUDA", "OpenCL", "ROCm", "Metal")
    if info.container_gpu_available and info.container_hashcat_backend in ("CUDA", "OpenCL"):
        info.execution_path = "container"
        info.effective_gpu_name = info.container_gpu_name
        info.effective_backend = info.container_hashcat_backend or "CUDA"
    elif info.host_worker_available and info.host_worker_gpu_backend in _gpu_backends:
        info.execution_path = "host"
        info.effective_gpu_name = info.host_worker_gpu_name
        info.effective_backend = info.host_worker_gpu_backend
    elif info.container_hashcat_available:
        info.execution_path = "container_cpu"
        info.effective_gpu_name = "CPU (no GPU detected)"
        info.effective_backend = "CPU"
    else:
        info.execution_path = "none"

    log.info("gpu.resolution",
             execution_path=info.execution_path,
             effective_gpu=info.effective_gpu_name,
             backend=info.effective_backend)

    _gpu_info = info
    return info


def get_gpu_info() -> GPUInfo:
    """Return cached GPU info. Call detect_gpu() first during startup."""
    global _gpu_info
    if _gpu_info is None:
        return detect_gpu()
    return _gpu_info


def get_gpu_info_live() -> GPUInfo:
    """Re-read host worker capabilities for live health check (no cache)."""
    info = get_gpu_info()
    # Re-read host worker report for live status
    report = _read_host_worker_report()
    if report is not None:
        info.host_worker_available = report.get("available", False)
        info.host_worker_gpu_vendor = report.get("gpu_vendor", "none")
        info.host_worker_gpu_name = report.get("gpu_name", "")
        info.host_worker_gpu_vram_mb = report.get("gpu_vram_mb", 0)
        info.host_worker_gpu_backend = report.get("hashcat_backend")
        info.host_worker_hashcat_version = report.get("hashcat_version")
    else:
        info.host_worker_available = False
    return info


def _probe_hashcat_backend() -> Optional[str]:
    """Run hashcat -I to determine available backend."""
    try:
        result = subprocess.run(
            ["hashcat", "-I"], capture_output=True, text=True, timeout=15,
        )
        stdout = result.stdout.lower()
        if "cuda" in stdout:
            return "CUDA"
        elif "opencl" in stdout and ("gpu" in stdout or "accelerator" in stdout):
            return "OpenCL"
        elif "opencl" in stdout or "cpu" in stdout:
            return "CPU-only"
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
