#!/usr/bin/env python3
"""
MarkFlow Hashcat Host Worker — GPU password cracking outside Docker.

Runs on the host machine to provide GPU-accelerated password cracking
for AMD/Intel/Apple GPUs (or NVIDIA if not using Docker GPU passthrough).

Usage:
    python tools/markflow-hashcat-worker.py --queue-dir /path/to/hashcat-queue

The worker will:
1. Detect your GPU and write capabilities to the queue dir
2. Watch for job files from MarkFlow
3. Run hashcat with your GPU for each job
4. Write results back for MarkFlow to read
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────
# Apple Silicon / macOS GPU Detection
# ──────────────────────────────────────────────────────────────────────

def _detect_apple_silicon() -> dict | None:
    """
    Detect Apple Silicon GPU (M1/M2/M3/M4 family) via Metal backend.

    Apple Silicon uses Unified Memory Architecture — the GPU shares system
    RAM instead of having dedicated VRAM.  We estimate ~75% of total RAM
    as GPU-accessible, which is conservative but safe for hashcat.

    hashcat Metal backend requires version >= 6.2.0.
    """
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None

    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=10,
        )
        chip_name = result.stdout.strip()  # e.g. "Apple M3 Max"
        if not chip_name or not chip_name.startswith("Apple"):
            return None

        gpu_cores = _get_apple_gpu_cores()

        mem_result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=10,
        )
        total_ram_mb = int(mem_result.stdout.strip()) // (1024 * 1024)
        estimated_vram_mb = int(total_ram_mb * 0.75)

        metal_ok, hashcat_ver = _verify_hashcat_metal()

        name = chip_name
        if gpu_cores:
            name += f" ({gpu_cores}-core GPU)"

        print(f"[worker] Detected: {name}")
        print(f"[worker] Unified memory: {total_ram_mb} MB "
              f"(est. GPU-accessible: {estimated_vram_mb} MB)")

        if metal_ok:
            print(f"[worker] hashcat Metal backend: verified (v{hashcat_ver})")
        else:
            print(f"[worker] WARNING: hashcat Metal backend not verified")
            print(f"[worker]   Minimum version for Metal: 6.2.0")
            print(f"[worker]   Current version: {hashcat_ver}")
            print(f"[worker]   Install/update: brew install hashcat")

        _check_rosetta_hashcat()

        return {
            "available": True,
            "gpu_vendor": "apple",
            "gpu_name": name,
            "gpu_vram_mb": estimated_vram_mb,
            "hashcat_backend": "Metal" if metal_ok else None,
        }
    except Exception as e:
        print(f"[worker] Apple Silicon detection failed: {e}")
        return None


def _get_apple_gpu_cores() -> int | None:
    """Get the GPU core count on Apple Silicon via system_profiler."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        displays = data.get("SPDisplaysDataType", [])
        for display in displays:
            cores = display.get("sppci_cores")
            if cores:
                return int(cores)
            model = display.get("sppci_model", "")
            if "Apple" in model:
                core_match = re.search(r"(\d+)-core", model)
                if core_match:
                    return int(core_match.group(1))
    except Exception:
        pass
    return None


def _verify_hashcat_metal() -> tuple:
    """
    Verify hashcat has a working Metal backend.
    Returns (metal_available, hashcat_version_string).
    hashcat >= 6.2.0 supports Metal on macOS.
    """
    try:
        ver_result = subprocess.run(
            ["hashcat", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version_str = ver_result.stdout.strip()

        backend_result = subprocess.run(
            ["hashcat", "--backend-info"],
            capture_output=True, text=True, timeout=15,
        )
        output = (backend_result.stdout + backend_result.stderr).lower()
        metal_found = "metal" in output

        ver_match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_str)
        if ver_match:
            major, minor = int(ver_match.group(1)), int(ver_match.group(2))
            version_ok = (major > 6) or (major == 6 and minor >= 2)
        else:
            version_ok = False

        return (metal_found and version_ok, version_str)
    except Exception as e:
        return (False, f"error: {e}")


def _check_rosetta_hashcat():
    """
    Warn if hashcat is an x86 binary running under Rosetta 2.
    An x86 hashcat under Rosetta won't have Metal GPU access.
    """
    try:
        hashcat_path = shutil.which("hashcat")
        if not hashcat_path:
            return
        result = subprocess.run(
            ["file", hashcat_path],
            capture_output=True, text=True, timeout=5,
        )
        file_info = result.stdout.lower()
        if platform.machine() == "arm64" and "arm64" not in file_info:
            print("[worker] WARNING: hashcat binary appears to be x86 (Rosetta 2)")
            print(f"[worker]   Path: {hashcat_path}")
            print("[worker]   Metal GPU acceleration will NOT work under Rosetta")
            print("[worker]   Fix: brew install hashcat  (installs native ARM64 build)")
    except Exception:
        pass


def _detect_macos_intel_gpu() -> dict | None:
    """
    Detect discrete GPU on Intel Mac (e.g., Radeon Pro in older MacBook Pros).
    These use OpenCL, not Metal.
    """
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        return None

    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        displays = data.get("SPDisplaysDataType", [])
        for display in displays:
            model = display.get("sppci_model", "")
            vendor = display.get("spdisplays_vendor", "").lower()
            vram_str = (display.get("spdisplays_vram_shared", "")
                        or display.get("spdisplays_vram", ""))
            vram_mb = 0
            if vram_str:
                vram_match = re.search(r"(\d+)", str(vram_str))
                if vram_match:
                    vram_mb = int(vram_match.group(1))

            if "amd" in vendor or "radeon" in model.lower():
                return {
                    "available": True,
                    "gpu_vendor": "amd",
                    "gpu_name": model,
                    "gpu_vram_mb": vram_mb,
                    "hashcat_backend": "OpenCL",
                }
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────
# Main GPU detection
# ──────────────────────────────────────────────────────────────────────

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
        "host_machine": platform.machine(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # ── Apple Silicon (macOS ARM64) — Metal backend ──
    apple = _detect_apple_silicon()
    if apple:
        info.update(apple)

    # ── macOS Intel with discrete GPU — OpenCL backend ──
    if not info["available"]:
        mac_intel = _detect_macos_intel_gpu()
        if mac_intel:
            info.update(mac_intel)

    # ── NVIDIA ──
    if not info["available"] and shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
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

    # ── AMD (Linux: rocm-smi, Windows: PowerShell WMI) ──
    if not info["available"]:
        if platform.system() == "Linux" and shutil.which("rocm-smi"):
            try:
                result = subprocess.run(
                    ["rocm-smi", "--showproductname", "--csv"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines()[1:]:
                        if line.strip():
                            info["available"] = True
                            info["gpu_vendor"] = "amd"
                            info["gpu_name"] = line.strip().split(",")[0]
                            break
            except Exception:
                pass
        elif platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Get-WmiObject Win32_VideoController | "
                     "Select-Object Name, AdapterRAM | ConvertTo-Json"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0 and result.stdout.strip():
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
                        elif "intel" in name and any(k in name for k in ("arc", "iris", "xe")):
                            info["available"] = True
                            info["gpu_vendor"] = "intel"
                            info["gpu_name"] = gpu["Name"]
                            ram = gpu.get("AdapterRAM", 0)
                            if ram:
                                info["gpu_vram_mb"] = int(ram) // (1024 * 1024)
                            break
            except Exception:
                pass

    # ── Intel (Linux: clinfo) ──
    if not info["available"] and platform.system() == "Linux" and shutil.which("clinfo"):
        try:
            result = subprocess.run(
                ["clinfo", "--list"], capture_output=True, text=True, timeout=10,
            )
            if "intel" in result.stdout.lower():
                info["available"] = True
                info["gpu_vendor"] = "intel"
                info["gpu_name"] = "Intel GPU (via OpenCL)"
        except Exception:
            pass

    # ── Hashcat availability and backend ──
    if shutil.which("hashcat"):
        try:
            result = subprocess.run(
                ["hashcat", "--version"], capture_output=True, text=True, timeout=10,
            )
            info["hashcat_version"] = result.stdout.strip()
        except Exception:
            pass
        # Only probe backend if not already set by Apple detection
        if not info["hashcat_backend"]:
            try:
                result = subprocess.run(
                    ["hashcat", "-I"], capture_output=True, text=True, timeout=15,
                )
                stdout_lower = result.stdout.lower()
                if "metal" in stdout_lower:
                    info["hashcat_backend"] = "Metal"
                elif "cuda" in stdout_lower:
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


def process_job(queue_dir: Path, job_file: Path, caps: dict | None = None) -> dict:
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
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    potfile = queue_dir / "temp" / f"{job_id}.potfile"
    outfile = queue_dir / "temp" / f"{job_id}.out"
    potfile.parent.mkdir(exist_ok=True)

    # Determine workload profile — Metal/Apple Silicon defaults to 2 (thermal-safe)
    default_workload = 3
    backend = caps.get("hashcat_backend", "") if caps else ""
    if backend == "Metal":
        default_workload = 2
    workload = job.get("workload_profile", default_workload)

    cmd = [
        "hashcat",
        "-m", str(job["hash_mode"]),
        "-a", str(job.get("attack_mode", 3)),
        "--potfile-path", str(potfile),
        "-o", str(outfile),
        "--force",
        "--runtime", str(job.get("timeout_seconds", 300)),
        "--quiet",
        "-w", str(workload),
        str(hash_file),
        job["mask"],
    ]

    # Metal backend: help hashcat select the right device
    if backend == "Metal":
        cmd.insert(cmd.index("--force") + 1, "--backend-devices")
        cmd.insert(cmd.index("--backend-devices") + 1, "1")

    print(f"[worker] Starting hashcat for {job_id} ({job.get('source_file', '?')})")
    start = time.time()

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=job.get("timeout_seconds", 300) + 60,
        )
        duration = time.time() - start
        result["duration_seconds"] = round(duration, 1)

        # Check for cracked password in output or potfile
        for f in [outfile, potfile]:
            if f.exists() and f.stat().st_size > 0:
                for line in f.read_text().strip().splitlines():
                    if ":" in line:
                        result["status"] = "cracked"
                        result["password"] = line.split(":")[-1]
                        print(f"[worker] CRACKED {job_id} in {duration:.1f}s")
                        break
            if result["status"] == "cracked":
                break

        if result["status"] != "cracked":
            if proc.returncode == 1:
                result["status"] = "exhausted"
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
    for d in [jobs_dir, results_dir, queue_dir / "hashes", queue_dir / "temp"]:
        d.mkdir(parents=True, exist_ok=True)

    caps = detect_host_gpu()
    (queue_dir / "worker_capabilities.json").write_text(json.dumps(caps, indent=2))

    print(f"[worker] GPU: {caps['gpu_name'] or 'None detected'} ({caps['gpu_vendor']})")
    print(f"[worker] Hashcat: {caps['hashcat_version'] or 'N/A'} (backend: {caps['hashcat_backend'] or 'N/A'})")
    print(f"[worker] Watching {jobs_dir}")
    print(f"[worker] Press Ctrl+C to stop.\n")

    lock_path = queue_dir / "worker.lock"
    lock_path.write_text(str(os.getpid()))

    caps_path = queue_dir / "worker_capabilities.json"
    _HEARTBEAT_INTERVAL = 120  # seconds
    _last_heartbeat = time.monotonic()

    try:
        while True:
            for job_file in sorted(jobs_dir.glob("*.json")):
                result_file = results_dir / job_file.name
                if result_file.exists():
                    continue

                result = process_job(queue_dir, job_file, caps)
                result["backend"] = caps.get("hashcat_backend")
                result["gpu_name"] = caps.get("gpu_name")
                result_file.write_text(json.dumps(result, indent=2))
                print(f"[worker] Result: {result_file.name} (status={result['status']})\n")

                # Cleanup
                try:
                    (queue_dir / f"hashes/{result['job_id']}.hash").unlink(missing_ok=True)
                    job_file.unlink(missing_ok=True)
                except OSError:
                    pass

            # Heartbeat — keep capabilities timestamp fresh so the server can
            # detect a stale/dead worker even if the lock file is not removed.
            now = time.monotonic()
            if now - _last_heartbeat >= _HEARTBEAT_INTERVAL:
                caps["timestamp"] = datetime.now(timezone.utc).isoformat()
                caps_path.write_text(json.dumps(caps, indent=2))
                _last_heartbeat = now

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("\n[worker] Shutting down.")
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MarkFlow Hashcat Host Worker")
    parser.add_argument("--queue-dir", type=Path, required=True,
                        help="Path to the shared hashcat-queue directory")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="Seconds between polling (default: 1.0)")
    args = parser.parse_args()

    if not shutil.which("hashcat"):
        print("[worker] ERROR: hashcat not found. Install hashcat on this machine first.")
        print("  Windows:  https://hashcat.net/hashcat/ (extract zip, add to PATH)")
        print("  macOS:    brew install hashcat")
        print("  Linux:    sudo apt install hashcat")
        sys.exit(1)

    run_worker(args.queue_dir, args.poll_interval)
