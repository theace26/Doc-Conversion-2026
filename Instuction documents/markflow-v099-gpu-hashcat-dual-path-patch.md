# MarkFlow v0.9.9 Patch: GPU Auto-Detection & Hashcat Integration (Dual-Path)

> **Patch target:** `core/password_handler.py` (existing, built in v0.9.8)
> **Purpose:** Auto-detect ANY GPU (NVIDIA, AMD, Intel) on the host system and use hashcat for GPU-accelerated password cracking. Dual-path execution: NVIDIA runs inside the Docker container; AMD/Intel runs on the host via a file-based job queue.
> **Grounded in:** CLAUDE.md as of v0.9.8. All file paths, table names, patterns, and conventions match the running codebase.

---

## 1. Why Two Paths?

Docker on Windows/WSL2 can only pass **NVIDIA GPUs** into containers (via NVIDIA Container Toolkit). AMD and Intel GPUs have no WSL2 passthrough. This means:

| GPU Vendor | Inside Container? | Hashcat Backend | Path |
|-----------|-------------------|-----------------|------|
| **NVIDIA** | ✅ Yes (CUDA via Container Toolkit) | CUDA or OpenCL | **Container-native** — hashcat runs inside Docker |
| **AMD** | ❌ No (ROCm needs bare-metal Linux) | ROCm or OpenCL | **Host-side worker** — hashcat runs on host, communicates via shared volume |
| **Intel** | ❌ No (oneAPI doesn't pass through WSL2) | OpenCL | **Host-side worker** — same as AMD |
| **None** | N/A | CPU fallback | **Container-native** — hashcat CPU mode or john |

The dual-path architecture:
1. **Container path (NVIDIA):** hashcat installed in Docker image, GPU passed through via `deploy.resources.reservations.devices`. Everything happens inside the container.
2. **Host path (AMD/Intel):** MarkFlow writes a job file to a shared volume. A lightweight host-side worker script picks it up, runs hashcat with the host GPU, writes the result back. MarkFlow polls for the result.

Both paths are transparent to the rest of MarkFlow — `_hashcat_attack()` abstracts away which path is used.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (doc-conversion-2026-markflow-1)          │
│                                                             │
│  PasswordHandler._hashcat_attack()                          │
│       │                                                     │
│       ├── NVIDIA detected? ──────► Run hashcat directly     │
│       │   (nvidia-smi works)       (CUDA backend, in-proc)  │
│       │                                                     │
│       └── AMD/Intel/Unknown? ───► Write job to              │
│           (no nvidia-smi)          /mnt/hashcat-queue/       │
│                                    Poll for result           │
│                                    (/mnt/hashcat-queue/      │
│                                     results/)                │
└──────────────┬──────────────────────────────────────────────┘
               │ shared volume: hashcat-queue
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Host System (Windows 11 / WSL2 / Linux)                    │
│                                                             │
│  markflow-hashcat-worker.py  (runs outside Docker)          │
│       │                                                     │
│       ├── Watches /path/to/hashcat-queue/jobs/              │
│       ├── Runs hashcat with host GPU (AMD ROCm, Intel OCL)  │
│       └── Writes result to /path/to/hashcat-queue/results/  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Shared Volume: `hashcat-queue`

A new Docker volume mounted at `/mnt/hashcat-queue` inside the container and mapped to a host directory.

### 3.1 Directory Structure

```
hashcat-queue/
├── jobs/                    # MarkFlow writes job files here
│   └── <job_id>.json        # Job definition (hash, mode, settings)
├── hashes/                  # Extracted hash files referenced by jobs
│   └── <job_id>.hash        # The actual hash for hashcat to crack
├── results/                 # Worker writes results here
│   └── <job_id>.json        # Result (password found or exhausted)
└── worker.lock              # PID lockfile to prevent duplicate workers
```

### 3.2 Job File Format

```json
{
    "job_id": "pw_a3f8c912",
    "created_at": "2026-03-26T14:30:00Z",
    "hash_file": "hashes/pw_a3f8c912.hash",
    "hash_mode": 9600,
    "attack_mode": 3,
    "mask": "?a?a?a?a?a?a",
    "workload_profile": 3,
    "timeout_seconds": 300,
    "source_file": "Q3_Budget_2024.xlsx",
    "format": "xlsx"
}
```

### 3.3 Result File Format

```json
{
    "job_id": "pw_a3f8c912",
    "completed_at": "2026-03-26T14:31:47Z",
    "status": "cracked",
    "password": "Budget2024!",
    "method": "hashcat_gpu",
    "backend": "ROCm",
    "gpu_name": "AMD Radeon RX 7900 XTX",
    "attempts": 48293710,
    "duration_seconds": 107
}
```

Status values: `"cracked"`, `"exhausted"`, `"timeout"`, `"error"`

---

## 4. GPU Detection Module: `core/gpu_detector.py`

New file. Runs once at app startup. Detects what's visible **inside the container** (NVIDIA only on Docker/WSL2) and also checks if a host worker is available.

```python
# core/gpu_detector.py

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)

# Path where the host worker drops its capability report
_HOST_WORKER_REPORT = Path("/mnt/hashcat-queue/worker_capabilities.json")


@dataclass
class GPUInfo:
    """Detected GPU hardware and software capabilities."""
    # --- Container-visible GPU (NVIDIA only on Docker/WSL2) ---
    container_gpu_available: bool = False
    container_gpu_vendor: str = "none"          # "nvidia" or "none"
    container_gpu_name: str = ""                # e.g. "NVIDIA GeForce RTX 3080"
    container_gpu_vram_mb: int = 0
    container_gpu_driver: str = ""
    container_cuda_version: Optional[str] = None
    container_hashcat_available: bool = False
    container_hashcat_backend: Optional[str] = None  # "CUDA", "OpenCL", "CPU-only", None

    # --- Host worker GPU (AMD/Intel/NVIDIA — reported by host worker) ---
    host_worker_available: bool = False
    host_worker_gpu_vendor: str = "none"        # "nvidia", "amd", "intel", "none"
    host_worker_gpu_name: str = ""
    host_worker_gpu_vram_mb: int = 0
    host_worker_gpu_backend: Optional[str] = None  # "ROCm", "OpenCL", "CUDA", None
    host_worker_hashcat_version: Optional[str] = None

    # --- Resolved execution path ---
    execution_path: str = "none"                # "container", "host", "container_cpu", "none"
    effective_gpu_name: str = ""                 # Whichever GPU will actually be used
    effective_backend: str = ""                  # Backend of the GPU that will be used


# Module-level singleton
_gpu_info: Optional[GPUInfo] = None


def detect_gpu() -> GPUInfo:
    """
    Probe for GPU hardware from both paths:
    1. Container-visible GPU (nvidia-smi → NVIDIA via Container Toolkit)
    2. Host worker capabilities (reads worker_capabilities.json from shared volume)
    
    Then resolves which execution path to use.
    """
    global _gpu_info
    info = GPUInfo()

    # ═══════════════════════════════════════════════════════
    # PATH 1: Container-visible GPU (NVIDIA only)
    # ═══════════════════════════════════════════════════════

    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 3:
                    info.container_gpu_available = True
                    info.container_gpu_vendor = "nvidia"
                    info.container_gpu_name = parts[0].strip()
                    info.container_gpu_vram_mb = int(float(parts[1].strip()))
                    info.container_gpu_driver = parts[2].strip()
                    logger.info("container_gpu_detected",
                                vendor="nvidia",
                                name=info.container_gpu_name,
                                vram_mb=info.container_gpu_vram_mb)
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as e:
            logger.debug("nvidia_smi_probe_failed", error=str(e))

    # Check CUDA version if NVIDIA is present
    if info.container_gpu_vendor == "nvidia" and shutil.which("nvcc"):
        try:
            result = subprocess.run(
                ["nvcc", "--version"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "release" in line.lower():
                    info.container_cuda_version = (
                        line.split("release")[-1].split(",")[0].strip()
                    )
                    break
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Check hashcat inside container
    info.container_hashcat_available = shutil.which("hashcat") is not None
    if info.container_hashcat_available:
        info.container_hashcat_backend = _probe_hashcat_backend()

    # ═══════════════════════════════════════════════════════
    # PATH 2: Host worker capabilities (any GPU vendor)
    # ═══════════════════════════════════════════════════════

    if _HOST_WORKER_REPORT.exists():
        try:
            import json
            report = json.loads(_HOST_WORKER_REPORT.read_text())
            info.host_worker_available = report.get("available", False)
            info.host_worker_gpu_vendor = report.get("gpu_vendor", "none")
            info.host_worker_gpu_name = report.get("gpu_name", "")
            info.host_worker_gpu_vram_mb = report.get("gpu_vram_mb", 0)
            info.host_worker_gpu_backend = report.get("hashcat_backend", None)
            info.host_worker_hashcat_version = report.get("hashcat_version", None)
            logger.info("host_worker_detected",
                        vendor=info.host_worker_gpu_vendor,
                        name=info.host_worker_gpu_name,
                        backend=info.host_worker_gpu_backend)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("host_worker_report_unreadable", error=str(e))
    else:
        logger.info("no_host_worker_report",
                     path=str(_HOST_WORKER_REPORT),
                     hint="Run markflow-hashcat-worker.py on host to enable AMD/Intel GPU cracking")

    # ═══════════════════════════════════════════════════════
    # RESOLVE: Which execution path wins?
    # ═══════════════════════════════════════════════════════

    if info.container_gpu_available and info.container_hashcat_backend in ("CUDA", "OpenCL"):
        # NVIDIA GPU visible in container — run hashcat in container
        info.execution_path = "container"
        info.effective_gpu_name = info.container_gpu_name
        info.effective_backend = info.container_hashcat_backend or "CUDA"
    elif info.host_worker_available and info.host_worker_gpu_backend:
        # AMD/Intel GPU on host — delegate to host worker
        info.execution_path = "host"
        info.effective_gpu_name = info.host_worker_gpu_name
        info.effective_backend = info.host_worker_gpu_backend
    elif info.container_hashcat_available:
        # No GPU anywhere, but hashcat is in the container — CPU mode
        info.execution_path = "container_cpu"
        info.effective_gpu_name = "CPU (no GPU detected)"
        info.effective_backend = "CPU"
    else:
        info.execution_path = "none"

    logger.info("gpu_resolution",
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


def _probe_hashcat_backend() -> Optional[str]:
    """Run hashcat -I inside the container to determine backend."""
    try:
        result = subprocess.run(
            ["hashcat", "-I"],
            capture_output=True, text=True, timeout=15
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
```

---

## 5. Host-Side Worker: `tools/markflow-hashcat-worker.py`

This script runs **outside Docker** on the host machine (Windows, WSL2, or bare-metal Linux). It:

1. Detects the host GPU (NVIDIA, AMD, or Intel)
2. Writes its capabilities to `worker_capabilities.json` (the container reads this)
3. Watches the `jobs/` directory for crack requests
4. Runs hashcat with the host's GPU
5. Writes results to `results/`

This file ships with the MarkFlow repo but is NOT used inside Docker — the user runs it on their host.

```python
#!/usr/bin/env python3
"""
MarkFlow Hashcat Host Worker
=============================
Runs OUTSIDE Docker on the host machine to provide GPU-accelerated
password cracking for AMD/Intel GPUs (or NVIDIA if not using Docker GPU).

Usage:
    python tools/markflow-hashcat-worker.py --queue-dir /path/to/hashcat-queue

On Windows with Docker Desktop, the queue dir is wherever you mapped the
hashcat-queue volume. Example:
    python tools/markflow-hashcat-worker.py --queue-dir D:\\markflow-hashcat-queue

The worker will:
1. Detect your GPU and write capabilities to the queue dir
2. Watch for job files from MarkFlow
3. Run hashcat with your GPU for each job
4. Write results back for MarkFlow to read

Press Ctrl+C to stop.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def detect_host_gpu() -> dict:
    """Detect GPU on the host system (any vendor)."""
    info = {
        "available": False,
        "gpu_vendor": "none",
        "gpu_name": "",
        "gpu_vram_mb": 0,
        "hashcat_backend": None,
        "hashcat_version": None,
        "host_os": platform.system(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- NVIDIA ---
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 3:
                    info["available"] = True
                    info["gpu_vendor"] = "nvidia"
                    info["gpu_name"] = parts[0].strip()
                    info["gpu_vram_mb"] = int(float(parts[1].strip()))
        except Exception:
            pass

    # --- AMD (Windows: look for AMD drivers; Linux: rocm-smi) ---
    if not info["available"]:
        if platform.system() == "Linux" and shutil.which("rocm-smi"):
            try:
                result = subprocess.run(
                    ["rocm-smi", "--showproductname", "--csv"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.splitlines()[1:]:  # Skip header
                        if line.strip():
                            info["available"] = True
                            info["gpu_vendor"] = "amd"
                            info["gpu_name"] = line.strip().split(",")[0]
                            break
            except Exception:
                pass

        elif platform.system() == "Windows":
            # Use WMIC or PowerShell to detect AMD GPU
            try:
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Get-WmiObject Win32_VideoController | "
                     "Select-Object Name, AdapterRAM | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    gpus = json.loads(result.stdout)
                    if not isinstance(gpus, list):
                        gpus = [gpus]
                    for gpu in gpus:
                        name = gpu.get("Name", "").lower()
                        if "amd" in name or "radeon" in name:
                            info["available"] = True
                            info["gpu_vendor"] = "amd"
                            info["gpu_name"] = gpu["Name"]
                            ram = gpu.get("AdapterRAM", 0)
                            if ram:
                                info["gpu_vram_mb"] = int(ram) // (1024 * 1024)
                            break
                        elif "intel" in name and ("arc" in name or "iris" in name or "xe" in name):
                            info["available"] = True
                            info["gpu_vendor"] = "intel"
                            info["gpu_name"] = gpu["Name"]
                            ram = gpu.get("AdapterRAM", 0)
                            if ram:
                                info["gpu_vram_mb"] = int(ram) // (1024 * 1024)
                            break
            except Exception:
                pass

    # --- Intel (Linux: clinfo) ---
    if not info["available"] and platform.system() == "Linux":
        if shutil.which("clinfo"):
            try:
                result = subprocess.run(
                    ["clinfo", "--list"], capture_output=True, text=True, timeout=10
                )
                stdout_lower = result.stdout.lower()
                if "intel" in stdout_lower:
                    info["available"] = True
                    info["gpu_vendor"] = "intel"
                    info["gpu_name"] = "Intel GPU (via OpenCL)"
            except Exception:
                pass

    # --- Hashcat availability ---
    hashcat_path = shutil.which("hashcat")
    if hashcat_path:
        try:
            result = subprocess.run(
                ["hashcat", "--version"], capture_output=True, text=True, timeout=10
            )
            info["hashcat_version"] = result.stdout.strip()
        except Exception:
            pass

        # Determine backend
        try:
            result = subprocess.run(
                ["hashcat", "-I"], capture_output=True, text=True, timeout=15
            )
            stdout_lower = result.stdout.lower()
            if "cuda" in stdout_lower:
                info["hashcat_backend"] = "CUDA"
            elif "rocm" in stdout_lower:
                info["hashcat_backend"] = "ROCm"
            elif "opencl" in stdout_lower and "gpu" in stdout_lower:
                info["hashcat_backend"] = "OpenCL"
            elif "opencl" in stdout_lower:
                info["hashcat_backend"] = "OpenCL-CPU"
        except Exception:
            pass

    return info


def write_capabilities(queue_dir: Path, capabilities: dict):
    """Write capabilities report for the container to read."""
    report_path = queue_dir / "worker_capabilities.json"
    report_path.write_text(json.dumps(capabilities, indent=2))
    print(f"[worker] Wrote capabilities to {report_path}")


def process_job(queue_dir: Path, job_file: Path) -> dict:
    """Run hashcat for a single job and return the result."""
    job = json.loads(job_file.read_text())
    job_id = job["job_id"]
    hash_file = queue_dir / job["hash_file"]
    result = {
        "job_id": job_id,
        "completed_at": None,
        "status": "error",
        "password": None,
        "method": "hashcat_gpu",
        "backend": None,
        "gpu_name": None,
        "attempts": 0,
        "duration_seconds": 0,
        "error": None,
    }

    if not hash_file.exists():
        result["error"] = f"Hash file not found: {hash_file}"
        return result

    # Build hashcat command
    potfile = queue_dir / "temp" / f"{job_id}.potfile"
    outfile = queue_dir / "temp" / f"{job_id}.out"
    potfile.parent.mkdir(exist_ok=True)

    cmd = [
        "hashcat",
        "-m", str(job["hash_mode"]),
        "-a", str(job.get("attack_mode", 3)),
        "--potfile-path", str(potfile),
        "-o", str(outfile),
        "--force",
        "--status",
        "--status-timer", "10",
        "--runtime", str(job.get("timeout_seconds", 300)),
        "--quiet",
        "-w", str(job.get("workload_profile", 3)),
        str(hash_file),
        job["mask"],
    ]

    print(f"[worker] Starting hashcat for {job_id} ({job.get('source_file', '?')})")
    start = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=job.get("timeout_seconds", 300) + 60,
        )
        duration = time.time() - start
        result["duration_seconds"] = round(duration, 1)

        # Check for cracked password
        if outfile.exists() and outfile.stat().st_size > 0:
            content = outfile.read_text().strip()
            if ":" in content:
                result["status"] = "cracked"
                result["password"] = content.split(":")[-1]
                print(f"[worker] CRACKED {job_id} in {duration:.1f}s")
        elif potfile.exists() and potfile.stat().st_size > 0:
            for line in potfile.read_text().strip().splitlines():
                if ":" in line:
                    result["status"] = "cracked"
                    result["password"] = line.split(":")[-1]
                    break
        else:
            if proc.returncode == 1:
                result["status"] = "exhausted"
                print(f"[worker] Exhausted {job_id} in {duration:.1f}s")
            elif proc.returncode == 2:
                result["status"] = "timeout"
            else:
                result["status"] = "error"
                result["error"] = f"hashcat exit code: {proc.returncode}"

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["duration_seconds"] = job.get("timeout_seconds", 300)
    except FileNotFoundError:
        result["error"] = "hashcat not found on host"
    finally:
        # Cleanup temp files
        for f in [potfile, outfile]:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return result


def run_worker(queue_dir: Path, poll_interval: float = 1.0):
    """Main worker loop — watch for jobs, process them, write results."""
    jobs_dir = queue_dir / "jobs"
    results_dir = queue_dir / "results"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "hashes").mkdir(exist_ok=True)
    (queue_dir / "temp").mkdir(exist_ok=True)

    # Write capabilities
    caps = detect_host_gpu()
    write_capabilities(queue_dir, caps)

    print(f"[worker] GPU: {caps['gpu_name'] or 'None detected'} ({caps['gpu_vendor']})")
    print(f"[worker] Hashcat backend: {caps['hashcat_backend'] or 'N/A'}")
    print(f"[worker] Watching {jobs_dir} for crack requests...")
    print(f"[worker] Press Ctrl+C to stop.\n")

    # Write lockfile
    lock_path = queue_dir / "worker.lock"
    lock_path.write_text(str(os.getpid()))

    try:
        while True:
            # Look for unprocessed job files
            for job_file in sorted(jobs_dir.glob("*.json")):
                result_file = results_dir / job_file.name
                if result_file.exists():
                    continue  # Already processed

                # Process the job
                result = process_job(queue_dir, job_file)
                result["backend"] = caps.get("hashcat_backend")
                result["gpu_name"] = caps.get("gpu_name")

                # Write result
                result_file.write_text(json.dumps(result, indent=2))
                print(f"[worker] Result written: {result_file.name} "
                      f"(status={result['status']})\n")

                # Clean up job file and hash after processing
                try:
                    hash_path = queue_dir / f"hashes/{result['job_id']}.hash"
                    hash_path.unlink(missing_ok=True)
                    job_file.unlink(missing_ok=True)
                except OSError:
                    pass

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n[worker] Shutting down.")
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MarkFlow Hashcat Host Worker — GPU password cracking outside Docker"
    )
    parser.add_argument(
        "--queue-dir",
        type=Path,
        required=True,
        help="Path to the shared hashcat-queue directory "
             "(same as the Docker volume mount target)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between polling for new jobs (default: 1.0)",
    )
    args = parser.parse_args()

    if not shutil.which("hashcat"):
        print("[worker] ERROR: hashcat not found. Install hashcat on this machine first.")
        print("  Windows: https://hashcat.net/hashcat/ (extract zip, add to PATH)")
        print("  Linux:   sudo apt install hashcat")
        sys.exit(1)

    run_worker(args.queue_dir, args.poll_interval)
```

---

## 6. Password Handler Changes: `core/password_handler.py`

### 6.1 Updated `CrackMethod` Enum

```python
class CrackMethod(Enum):
    NONE = "none"
    KNOWN_PASSWORD = "known_password"
    DICTIONARY = "dictionary"
    BRUTE_FORCE = "brute_force"
    JOHN_CPU = "john_cpu"
    HASHCAT_GPU = "hashcat_gpu"             # GPU-accelerated (any vendor)
    HASHCAT_CPU = "hashcat_cpu"             # Hashcat in CPU-only mode
    HASHCAT_HOST = "hashcat_host"           # Via host worker (AMD/Intel GPU)
```

### 6.2 GPU-Aware Initialization

Add to `PasswordHandler.__init__()`:

```python
from core.gpu_detector import get_gpu_info

# In __init__:
self._gpu_info = get_gpu_info()
self._hashcat_path = (
    "container"  # NVIDIA: run in container
    if self._gpu_info.execution_path == "container"
    else "host"   # AMD/Intel: delegate to host worker
    if self._gpu_info.execution_path == "host"
    else "container_cpu"  # No GPU, but hashcat available for CPU mode
    if self._gpu_info.execution_path == "container_cpu"
    else "none"
)
self._hashcat_queue_dir = Path("/mnt/hashcat-queue")

logger.info("password_handler_gpu_init",
            execution_path=self._gpu_info.execution_path,
            effective_gpu=self._gpu_info.effective_gpu_name,
            backend=self._gpu_info.effective_backend)
```

### 6.3 Unified `_hashcat_attack()` — Routes to Correct Path

```python
async def _hashcat_attack(self, file_path: Path, fmt: str) -> Optional[str]:
    """
    GPU-accelerated password cracking via hashcat.
    
    Routes to the correct execution path:
    - container: Run hashcat directly (NVIDIA GPU visible)
    - host: Write job to shared queue, poll for result (AMD/Intel)
    - container_cpu: Run hashcat in CPU-only mode
    """
    if self._hashcat_path == "none":
        return None

    # Step 1: Extract hash (always done in container — john tools are here)
    hash_file = await self._extract_hash_for_hashcat(file_path, fmt)
    if not hash_file:
        return None

    hash_mode = self._get_hashcat_mode(fmt, file_path)
    if not hash_mode:
        logger.debug("hashcat_no_mode", format=fmt)
        return None

    # Step 2: Route to execution path
    if self._hashcat_path in ("container", "container_cpu"):
        result = await self._hashcat_container(hash_file, hash_mode)
    elif self._hashcat_path == "host":
        result = await self._hashcat_host(hash_file, hash_mode, file_path, fmt)
    else:
        result = None

    # Cleanup the extracted hash
    try:
        if hash_file and hash_file.exists():
            hash_file.unlink()
    except OSError:
        pass

    return result


async def _hashcat_container(self, hash_file: Path, hash_mode: int) -> Optional[str]:
    """Run hashcat directly inside the container (NVIDIA or CPU mode)."""
    import asyncio

    potfile = Path(tempfile.mktemp(suffix=".potfile"))
    outfile = Path(tempfile.mktemp(suffix=".out"))

    workload = int(self._settings.get("password_hashcat_workload", "3"))
    mask = self._build_hashcat_mask()

    cmd = [
        "hashcat",
        "-m", str(hash_mode),
        "-a", "3",
        "--potfile-path", str(potfile),
        "-o", str(outfile),
        "--force",
        "--runtime", str(self.timeout_seconds),
        "--quiet",
        "-w", str(workload),
        str(hash_file),
        mask,
    ]

    logger.info("hashcat_container_starting",
                mode=hash_mode,
                backend=self._gpu_info.effective_backend,
                gpu=self._gpu_info.effective_gpu_name)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(
            proc.communicate(),
            timeout=self.timeout_seconds + 30
        )

        # Check result files
        password = self._read_hashcat_result(outfile, potfile)
        if password:
            logger.info("hashcat_container_cracked",
                        backend=self._gpu_info.effective_backend)
        return password

    except asyncio.TimeoutError:
        logger.warning("hashcat_container_timeout")
        if proc and proc.returncode is None:
            proc.terminate()
        return None
    except FileNotFoundError:
        logger.warning("hashcat_not_found_in_container")
        return None
    finally:
        for f in [potfile, outfile]:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass


async def _hashcat_host(
    self, hash_file: Path, hash_mode: int, source_file: Path, fmt: str
) -> Optional[str]:
    """
    Delegate cracking to the host-side worker via the shared queue volume.
    
    1. Copy hash file to queue/hashes/
    2. Write job JSON to queue/jobs/
    3. Poll queue/results/ for the result
    4. Return password or None
    """
    import asyncio
    import json
    import shutil as shutil_mod

    queue_dir = self._hashcat_queue_dir
    job_id = f"pw_{secrets.token_hex(4)}"

    # Ensure directories exist
    (queue_dir / "hashes").mkdir(parents=True, exist_ok=True)
    (queue_dir / "jobs").mkdir(parents=True, exist_ok=True)
    (queue_dir / "results").mkdir(parents=True, exist_ok=True)

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
        "format": fmt,
    }
    job_file = queue_dir / "jobs" / f"{job_id}.json"
    job_file.write_text(json.dumps(job, indent=2))

    logger.info("hashcat_host_job_submitted",
                job_id=job_id,
                file=source_file.name,
                mode=hash_mode)

    # Poll for result
    result_file = queue_dir / "results" / f"{job_id}.json"
    poll_interval = 1.0  # seconds
    elapsed = 0.0
    # Allow extra time for host worker processing beyond our timeout
    max_wait = self.timeout_seconds + 120

    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        if result_file.exists():
            try:
                result = json.loads(result_file.read_text())

                if result.get("status") == "cracked" and result.get("password"):
                    logger.info("hashcat_host_cracked",
                                job_id=job_id,
                                backend=result.get("backend"),
                                gpu=result.get("gpu_name"),
                                duration=result.get("duration_seconds"))
                    password = result["password"]
                else:
                    logger.info("hashcat_host_completed",
                                job_id=job_id,
                                status=result.get("status"))
                    password = None

                # Cleanup result file
                try:
                    result_file.unlink(missing_ok=True)
                except OSError:
                    pass
                return password

            except (json.JSONDecodeError, OSError) as e:
                logger.debug("hashcat_host_result_read_error", error=str(e))
                continue

    # Timed out waiting for host worker
    logger.warning("hashcat_host_timeout",
                    job_id=job_id,
                    waited=elapsed)

    # Cleanup stale job
    for f in [job_file, queue_hash]:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    return None


@staticmethod
def _read_hashcat_result(outfile: Path, potfile: Path) -> Optional[str]:
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
```

### 6.4 Cascade Update

In the cracking cascade, the hashcat step should determine the correct `CrackMethod`:

```python
# After hashcat_result is obtained from _hashcat_attack():
if hashcat_result:
    if self._hashcat_path == "host":
        method = CrackMethod.HASHCAT_HOST
    elif self._gpu_info.execution_path == "container":
        method = CrackMethod.HASHCAT_GPU
    else:
        method = CrackMethod.HASHCAT_CPU
```

### 6.5 Helper Methods

The following methods carry over from the original patch unchanged:
- `_extract_hash_for_hashcat()` — extracts hash via `pdf2john.pl` / `office2john.py`
- `_get_hashcat_mode()` — maps format + encryption to hashcat `-m` mode
- `_build_hashcat_mask()` — builds charset mask from settings

(See the original v0.9.9 patch document for these — they are not modified.)

---

## 7. Docker Changes

### 7.1 Dockerfile Additions

Same as original patch — hashcat + OpenCL packages:

```dockerfile
# Password cracking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    john \
    hashcat \
    hashcat-data \
    opencl-headers \
    ocl-icd-libopencl1 \
    clinfo \
    perl-base \
    && rm -rf /var/lib/apt/lists/*

# NVIDIA OpenCL ICD (for container-native GPU path)
RUN mkdir -p /etc/OpenCL/vendors && \
    echo "libnvidia-opencl.so.1" > /etc/OpenCL/vendors/nvidia.icd
```

### 7.2 docker-compose.yml Changes

Add **both** the GPU reservation **and** the hashcat queue volume:

```yaml
services:
  markflow:
    build: .
    # ... existing config ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, compute, utility]
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
    volumes:
      # ... existing volumes ...
      - hashcat-queue:/mnt/hashcat-queue    # NEW — shared with host worker

volumes:
  # ... existing volumes ...
  hashcat-queue:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${HASHCAT_QUEUE_DIR:-./hashcat-queue}   # Host directory
```

The `HASHCAT_QUEUE_DIR` env var lets you put the queue wherever you want. Default is `./hashcat-queue` next to docker-compose.yml.

### 7.3 `.env` File Addition

```env
# GPU password cracking — host-side queue directory
# Set this to wherever you want the host worker to read/write
HASHCAT_QUEUE_DIR=D:\markflow-hashcat-queue
```

---

## 8. Settings & UI Additions

### 8.1 New Preference Keys

Add to `_PREFERENCE_SCHEMA` in `core/database.py`:

```python
"password_hashcat_enabled": {
    "type": "boolean",
    "default": "true",
    "label": "Use hashcat when available",
    "description": "Enable GPU-accelerated cracking via hashcat (container or host worker).",
    "category": "password_recovery",
    "system_level": True,
},
"password_hashcat_workload": {
    "type": "select",
    "default": "3",
    "options": ["1", "2", "3", "4"],
    "label": "Hashcat workload profile",
    "description": "1=Low (keep desktop responsive), 2=Default, 3=High (dedicated machine), 4=Maximum (100% GPU, may freeze UI).",
    "category": "password_recovery",
    "system_level": True,
},
```

### 8.2 Settings Page: GPU Status Card

```html
<div id="gpu-status-card" class="card">
    <h4>GPU Acceleration</h4>
    <div class="gpu-info">
        <span class="status-pill" id="gpu-pill">Detecting...</span>
        <dl>
            <dt>Execution Path</dt><dd id="gpu-path">—</dd>
            <dt>GPU</dt><dd id="gpu-name">—</dd>
            <dt>Backend</dt><dd id="gpu-backend">—</dd>
            <dt>Host Worker</dt><dd id="gpu-host-worker">—</dd>
        </dl>
        <p class="help-text" id="gpu-help"></p>
    </div>
</div>
```

JS logic for the card:
```javascript
// Fetch from GET /api/health → response.components.gpu
const gpu = healthData.components.gpu;
if (gpu.execution_path === "container") {
    gpuPill.textContent = "NVIDIA (Container)";
    gpuPill.classList.add("pill-green");
} else if (gpu.execution_path === "host") {
    gpuPill.textContent = `${gpu.host_worker_gpu_vendor.toUpperCase()} (Host Worker)`;
    gpuPill.classList.add("pill-blue");
} else if (gpu.execution_path === "container_cpu") {
    gpuPill.textContent = "CPU Only";
    gpuPill.classList.add("pill-yellow");
} else {
    gpuPill.textContent = "No GPU / No Hashcat";
    gpuPill.classList.add("pill-gray");
    gpuHelp.textContent = "Install hashcat in the container or run the host worker for GPU cracking.";
}
```

### 8.3 Health Endpoint

Add to the `GET /api/health` response:

```python
from core.gpu_detector import get_gpu_info

gpu = get_gpu_info()
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
```

---

## 9. User Setup Guide

### 9.1 NVIDIA GPU (Easiest — Fully Automatic)

```powershell
# Verify GPU passthrough works
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi

# If that works, just rebuild and start MarkFlow
docker compose down
docker compose build --no-cache markflow
docker compose up -d

# Verify in container
docker exec doc-conversion-2026-markflow-1 sh -c "nvidia-smi && hashcat -I"
```

No host worker needed. Everything runs inside the container.

### 9.2 AMD / Intel GPU (Host Worker Required)

**Step 1: Install hashcat on the host**

Windows:
1. Download from https://hashcat.net/hashcat/
2. Extract to `C:\hashcat\`
3. Add `C:\hashcat\` to system PATH
4. Verify: `hashcat --version`

For AMD GPUs, also install the latest AMD Adrenalin drivers (includes OpenCL runtime).
For Intel GPUs, install Intel oneAPI Base Toolkit (includes OpenCL runtime).

**Step 2: Create the queue directory**

```powershell
mkdir D:\markflow-hashcat-queue
```

**Step 3: Set the env var**

In your `.env` file next to `docker-compose.yml`:
```env
HASHCAT_QUEUE_DIR=D:\markflow-hashcat-queue
```

**Step 4: Rebuild and start MarkFlow**

```powershell
docker compose down
docker compose build --no-cache markflow
docker compose up -d
```

**Step 5: Start the host worker**

```powershell
# From the MarkFlow repo root
python tools/markflow-hashcat-worker.py --queue-dir D:\markflow-hashcat-queue
```

The worker will:
1. Detect your AMD/Intel GPU
2. Write its capabilities (MarkFlow reads them on next health check)
3. Start watching for crack jobs

Leave the worker running in a separate terminal or set it up as a Windows service.

### 9.3 No GPU / Testing

Everything still works — hashcat runs in CPU-only mode inside the container, and john handles what hashcat can't. No host worker needed.

---

## 10. Test Requirements

### New Tests: `tests/test_gpu_detector.py`

| Test | What It Verifies |
|------|-----------------|
| `test_detect_no_gpu` | Returns `execution_path="none"` with no GPU tools |
| `test_detect_nvidia_container` | Mocks nvidia-smi → `execution_path="container"` |
| `test_detect_host_worker_amd` | Mocks capabilities JSON with AMD → `execution_path="host"` |
| `test_detect_host_worker_intel` | Mocks capabilities JSON with Intel → `execution_path="host"` |
| `test_nvidia_takes_precedence` | Both container NVIDIA and host AMD available → container wins |
| `test_capabilities_file_missing` | Missing capabilities file → `host_worker_available=False` |
| `test_capabilities_file_corrupt` | Bad JSON → graceful fallback, no crash |
| `test_cache_singleton` | Second `get_gpu_info()` call returns cached result |

### Additions to `tests/test_password_handler.py`

| Test | What It Verifies |
|------|-----------------|
| `test_hashcat_container_path` | NVIDIA detection routes to `_hashcat_container()` |
| `test_hashcat_host_path` | AMD/Intel detection routes to `_hashcat_host()` |
| `test_hashcat_host_job_written` | Job JSON written to queue directory correctly |
| `test_hashcat_host_result_read` | Result JSON read and password extracted |
| `test_hashcat_host_timeout` | Polling times out, returns None, cleans up job file |
| `test_hashcat_disabled_setting` | `password_hashcat_enabled=false` skips both paths |
| `test_crack_method_hashcat_host` | Host worker crack returns `CrackMethod.HASHCAT_HOST` |
| `test_crack_method_hashcat_gpu` | Container GPU crack returns `CrackMethod.HASHCAT_GPU` |
| `test_cascade_order_full` | Full cascade: empty → org → found → dict → brute → john → hashcat → fail |

### New Tests: `tests/test_hashcat_worker.py`

| Test | What It Verifies |
|------|-----------------|
| `test_worker_detects_gpu_mock` | `detect_host_gpu()` with mocked subprocess returns correct info |
| `test_worker_writes_capabilities` | `write_capabilities()` creates valid JSON |
| `test_worker_processes_job` | `process_job()` with mocked hashcat returns result |
| `test_worker_handles_missing_hash` | Missing hash file returns error result, no crash |
| `test_worker_cleans_up_temp` | Potfile and outfile deleted after processing |

---

## 11. Files to Create or Modify

### New Files
| File | Purpose |
|------|---------|
| `core/gpu_detector.py` | Dual-path GPU detection: container NVIDIA + host worker capabilities |
| `tools/markflow-hashcat-worker.py` | Host-side hashcat worker script (runs outside Docker) |
| `tests/test_gpu_detector.py` | GPU detection tests |
| `tests/test_hashcat_worker.py` | Host worker tests |

### Modified Files
| File | Change |
|------|--------|
| `core/password_handler.py` | `CrackMethod` enum update, GPU-aware init, `_hashcat_attack()` with container/host routing, `_hashcat_container()`, `_hashcat_host()` |
| `core/database.py` | Add `password_hashcat_enabled`, `password_hashcat_workload` to `_PREFERENCE_SCHEMA` |
| `core/health.py` | Add dual-path GPU info to health check response |
| `main.py` | Add `detect_gpu()` call in lifespan startup |
| `static/settings.html` | GPU status card in Password Recovery section |
| `Dockerfile` | Add hashcat, opencl-headers, ocl-icd-libopencl1, clinfo, perl-base |
| `docker-compose.yml` | GPU reservation + `hashcat-queue` volume mount |
| `.env` | Add `HASHCAT_QUEUE_DIR` |
| `tests/test_password_handler.py` | Hashcat routing, cascade, and method tests |
| `CLAUDE.md` | v0.9.9 entry + gotchas |

---

## 12. CLAUDE.md Updates

### Version Entry

```
**v0.9.9** — GPU auto-detection & dual-path hashcat integration.
  `core/gpu_detector.py` probes container for NVIDIA (nvidia-smi) and reads
  host worker capabilities from `/mnt/hashcat-queue/worker_capabilities.json`.
  Execution path resolution: NVIDIA in container → AMD/Intel via host worker →
  hashcat CPU fallback → john → Python. Host worker (`tools/markflow-hashcat-worker.py`)
  runs outside Docker, watches shared queue volume for crack jobs, runs hashcat
  with host GPU (AMD ROCm, Intel OpenCL, or NVIDIA CUDA), writes results back.
  Job queue is file-based JSON over a bind-mounted volume. Docker Compose gains
  GPU reservation (NVIDIA Container Toolkit) and hashcat-queue volume.
  Dockerfile adds hashcat, OpenCL packages, clinfo. Password handler routes
  to _hashcat_container() or _hashcat_host() based on detected path.
  CrackMethod enum: HASHCAT_GPU, HASHCAT_CPU, HASHCAT_HOST. Settings:
  password_hashcat_enabled, password_hashcat_workload. Health endpoint
  reports both container and host GPU info.
```

### New Gotchas

```
- **GPU passthrough requires NVIDIA Container Toolkit**: The deploy.resources.
  reservations.devices block requests GPU access but does NOT fail if no GPU.
  Container starts normally; detect_gpu() returns container_gpu_available=False.
  WSL2 on Windows 11 with NVIDIA drivers 535+ passes GPU through automatically.

- **AMD/Intel GPUs need the host worker**: Docker on WSL2 cannot pass AMD or Intel
  GPUs to containers. The host worker script (tools/markflow-hashcat-worker.py)
  must be running on the host machine for non-NVIDIA GPU cracking. Without it,
  MarkFlow falls back to hashcat CPU or john.

- **Host worker capabilities are read once at startup**: The container reads
  worker_capabilities.json during detect_gpu() at app startup. If the host worker
  starts AFTER MarkFlow, the container won't see it until restart. The health
  endpoint re-reads the file on each call for live status.

- **hashcat --force flag required in Docker**: Without it, hashcat refuses to run
  in container environments. Safe for single-file cracking.

- **hashcat potfile conflicts**: Each attack uses a unique temp potfile. Never use
  hashcat's default potfile — concurrent batch cracking would corrupt it.

- **Host worker queue is fire-and-forget**: If the host worker is not running, jobs
  accumulate in the queue directory. When the worker starts, it processes the backlog.
  MarkFlow times out waiting (timeout_seconds + 120) and falls back.

- **HASHCAT_QUEUE_DIR must be a bind mount, not a Docker named volume**: Named volumes
  aren't easily accessible from the host. The docker-compose.yml uses driver_opts
  with type=none and o=bind to make it a true bind mount to a host directory.

- **pdf2john.pl requires perl**: Bundled with john but needs perl runtime. perl-base
  is added to the Dockerfile apt-get line.

- **hashcat exit codes**: 0=cracked, 1=exhausted, 2=user-abort, -1=error. The handler
  checks output file content rather than exit code for robustness.

- **Host worker on Windows needs hashcat in PATH**: Download the hashcat binary release,
  extract, and add the directory to the system PATH. AMD users also need Adrenalin
  drivers installed for the OpenCL runtime.
```

---

## 13. Done Criteria Checklist

- [ ] `core/gpu_detector.py` exists with dual-path detection (container + host)
- [ ] `detect_gpu()` runs at startup, resolves execution path
- [ ] NVIDIA GPU detected via nvidia-smi inside container
- [ ] Host worker capabilities read from `worker_capabilities.json`
- [ ] Execution path priority: NVIDIA container > host worker > hashcat CPU > none
- [ ] `tools/markflow-hashcat-worker.py` detects host GPU (NVIDIA, AMD, Intel)
- [ ] Host worker writes `worker_capabilities.json`
- [ ] Host worker watches queue dir and processes jobs
- [ ] Host worker runs hashcat with host GPU and writes results
- [ ] `_hashcat_attack()` routes to container or host based on execution path
- [ ] `_hashcat_container()` runs hashcat directly (NVIDIA path)
- [ ] `_hashcat_host()` writes job, polls for result (AMD/Intel path)
- [ ] Queue cleanup: job files, hash files, result files removed after processing
- [ ] `CrackMethod` enum includes `HASHCAT_GPU`, `HASHCAT_CPU`, `HASHCAT_HOST`
- [ ] `password_hashcat_enabled` and `password_hashcat_workload` preferences work
- [ ] Settings page shows GPU status card with execution path
- [ ] Health endpoint reports both container and host GPU info
- [ ] Dockerfile installs hashcat, OpenCL packages, clinfo, perl-base
- [ ] docker-compose.yml has GPU reservation and hashcat-queue volume
- [ ] Container starts and runs normally with NO GPU present
- [ ] All new tests pass (gpu_detector, password_handler, hashcat_worker)
- [ ] Startup log shows GPU detection results and execution path
- [ ] CLAUDE.md updated with v0.9.9 entry + new gotchas
