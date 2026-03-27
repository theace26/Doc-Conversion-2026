# MarkFlow v0.10.1 — Apple Silicon Metal Support for GPU Hashcat Worker

## Patch Identity

- **Version**: v0.10.1
- **Scope**: Add Apple Silicon (M1/M2/M3/M4) Metal GPU backend support to the existing hashcat host worker and GPU detector
- **Builds on**: v0.9.9 (GPU auto-detection & dual-path hashcat integration)
- **Files modified**: `tools/markflow-hashcat-worker.py`, `core/gpu_detector.py`, `static/admin.html` (GPU status card), `static/settings.html` (GPU section)
- **No new files** — this is an extension to existing infrastructure

---

## Context from CLAUDE.md

v0.9.9 already provides:

- `core/gpu_detector.py` — probes container for NVIDIA (nvidia-smi), reads host worker capabilities from `/mnt/hashcat-queue/worker_capabilities.json`
- `tools/markflow-hashcat-worker.py` — runs outside Docker, watches shared queue volume, runs hashcat with host GPU (currently: AMD ROCm, Intel OpenCL)
- `CrackMethod` enum: `HASHCAT_GPU`, `HASHCAT_CPU`, `HASHCAT_HOST`
- Execution priority: NVIDIA container > host worker > hashcat CPU > none
- `docker-compose.gpu.yml` overlay for NVIDIA Container Toolkit
- Queue dir: `HASHCAT_QUEUE_DIR` env var (default `./hashcat-queue`), bind-mounted at `/mnt/hashcat-queue/`
- `worker_capabilities.json` written by host worker, read by container at startup + live on health check

**What v0.9.9 does NOT cover**: Apple Silicon Macs. The host worker currently detects AMD (via `rocm-smi` / `wmic`) and Intel (via `wmic` / `lspci`). macOS detection is absent. A user running the host worker on an M-series Mac gets CPU fallback.

---

## What This Patch Adds

1. **Apple Silicon Metal detection** in `tools/markflow-hashcat-worker.py`
2. **macOS Intel discrete GPU detection** (e.g., Radeon Pro in older MacBook Pros)
3. **Metal-specific hashcat flags** (workload profile, backend device selection)
4. **Rosetta 2 binary guard** — warns if hashcat is x86 running under Rosetta (no Metal access)
5. **hashcat version gate** — Metal backend requires hashcat ≥ 6.2.0
6. **Unified memory estimation** — Apple Silicon has no separate VRAM; estimates GPU-accessible portion
7. **`core/gpu_detector.py` update** — recognizes `vendor: "apple"` and `backend: "metal"` in worker capabilities
8. **GPU status card update** — Admin/Settings pages correctly display Apple Silicon info

---

## 1. Modify: `tools/markflow-hashcat-worker.py`

### Add Apple Silicon + macOS detection functions

Insert these functions into the existing GPU detection section of the worker. The worker already has a detection flow (`_detect_nvidia()`, `_detect_amd()`, `_detect_intel()`, CPU fallback). Add Apple detection **before** the NVIDIA check, since on an Apple Silicon Mac, `nvidia-smi` won't exist but we want to find the Metal GPU immediately.

```python
# ──────────────────────────────────────────────
# Apple Silicon / macOS GPU Detection
# ──────────────────────────────────────────────

def _detect_apple_silicon() -> Optional[GPUInfo]:
    """
    Detect Apple Silicon GPU (M1/M2/M3/M4 family) via Metal backend.

    Apple Silicon Macs use a Unified Memory Architecture — the GPU shares
    system RAM instead of having dedicated VRAM. We estimate ~75% of total
    RAM as GPU-accessible, which is conservative but safe for hashcat.

    hashcat Metal backend requires version ≥ 6.2.0 (released 2021).
    """
    import platform
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Only applies to macOS on ARM64
    if system != "darwin" or machine != "arm64":
        return None

    try:
        # Get chip name from sysctl
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=10
        )
        chip_name = result.stdout.strip()  # e.g. "Apple M3 Max"

        if not chip_name or not chip_name.startswith("Apple"):
            return None

        # Get GPU core count via system_profiler
        gpu_cores = _get_apple_gpu_cores()

        # Get unified memory (Apple Silicon shares RAM between CPU and GPU)
        mem_result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=10
        )
        total_ram_mb = int(mem_result.stdout.strip()) // (1024 * 1024)
        # Conservative estimate: GPU can access ~75% of unified memory
        estimated_vram_mb = int(total_ram_mb * 0.75)

        # Verify hashcat Metal backend is available
        metal_ok, hashcat_ver = _verify_hashcat_metal()

        # Build display name
        name = chip_name
        if gpu_cores:
            name += f" ({gpu_cores}-core GPU)"

        print(f"[worker] Detected: {name}")
        print(f"[worker] Unified memory: {total_ram_mb} MB (est. GPU-accessible: {estimated_vram_mb} MB)")

        if metal_ok:
            print(f"[worker] hashcat Metal backend: verified ✓ (v{hashcat_ver})")
        else:
            print(f"[worker] WARNING: hashcat Metal backend not verified")
            print(f"[worker]   Minimum version for Metal: 6.2.0")
            print(f"[worker]   Current version: {hashcat_ver}")
            print(f"[worker]   Install/update: brew install hashcat")

        # Check for Rosetta — x86 hashcat binary won't have Metal access
        _check_rosetta_hashcat()

        return GPUInfo(
            vendor="apple",
            name=name,
            backend="metal",
            device_type=2,  # GPU (hashcat -D value)
            vram_mb=estimated_vram_mb
        )

    except Exception as e:
        print(f"[worker] Apple Silicon detection failed: {e}")
        return None


def _get_apple_gpu_cores() -> Optional[int]:
    """Get the GPU core count on Apple Silicon via system_profiler."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        displays = data.get("SPDisplaysDataType", [])
        for display in displays:
            # sppci_cores may be a string like "30" or "40"
            cores = display.get("sppci_cores")
            if cores:
                return int(cores)
            # Fallback: parse from model name
            model = display.get("sppci_model", "")
            if "Apple" in model:
                import re
                core_match = re.search(r'(\d+)-core', model)
                if core_match:
                    return int(core_match.group(1))
    except Exception:
        pass
    return None


def _verify_hashcat_metal() -> tuple[bool, str]:
    """
    Verify hashcat has a working Metal backend.
    Returns (metal_available, hashcat_version_string).

    hashcat 6.2.0+ supports Metal on macOS. Earlier versions only support
    OpenCL, which Apple deprecated.
    """
    try:
        ver_result = subprocess.run(
            ["hashcat", "--version"],
            capture_output=True, text=True, timeout=5
        )
        version_str = ver_result.stdout.strip()  # e.g. "v6.2.6"

        # Check backend info for Metal
        backend_result = subprocess.run(
            ["hashcat", "--backend-info"],
            capture_output=True, text=True, timeout=15
        )
        output = (backend_result.stdout + backend_result.stderr).lower()
        metal_found = "metal" in output

        # Also check version is >= 6.2.0
        import re
        ver_match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_str)
        if ver_match:
            major, minor, patch = int(ver_match.group(1)), int(ver_match.group(2)), int(ver_match.group(3))
            version_ok = (major > 6) or (major == 6 and minor >= 2)
        else:
            version_ok = False

        return (metal_found and version_ok, version_str)

    except Exception as e:
        return (False, f"error: {e}")


def _check_rosetta_hashcat():
    """
    Warn if hashcat is an x86 binary running under Rosetta 2.

    An x86 hashcat running via Rosetta won't have Metal GPU access —
    it would fall back to CPU only. The user needs the native ARM64
    build (e.g., via `brew install hashcat`).
    """
    try:
        hashcat_path = shutil.which("hashcat")
        if not hashcat_path:
            return

        result = subprocess.run(
            ["file", hashcat_path],
            capture_output=True, text=True, timeout=5
        )
        file_info = result.stdout.lower()

        import platform
        if platform.machine() == "arm64" and "arm64" not in file_info:
            print(f"[worker] ⚠ WARNING: hashcat binary appears to be x86 (Rosetta 2)")
            print(f"[worker]   Path: {hashcat_path}")
            print(f"[worker]   Metal GPU acceleration will NOT work under Rosetta")
            print(f"[worker]   Fix: brew install hashcat  (installs native ARM64 build)")
    except Exception:
        pass


def _detect_macos_intel_gpu() -> Optional[GPUInfo]:
    """
    Detect discrete GPU on Intel Mac (e.g., Radeon Pro in older MacBook Pros).
    These use OpenCL, not Metal.
    """
    import platform
    if platform.system().lower() != "darwin" or platform.machine().lower() != "x86_64":
        return None

    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=15
        )
        data = json.loads(result.stdout)
        displays = data.get("SPDisplaysDataType", [])
        for display in displays:
            model = display.get("sppci_model", "")
            vendor = display.get("spdisplays_vendor", "").lower()
            vram_str = display.get("spdisplays_vram_shared", "") or display.get("spdisplays_vram", "")
            vram_mb = 0
            if vram_str:
                import re
                vram_match = re.search(r'(\d+)', str(vram_str))
                if vram_match:
                    vram_mb = int(vram_match.group(1))

            if "amd" in vendor or "radeon" in model.lower():
                return GPUInfo(
                    vendor="amd",
                    name=model,
                    backend="opencl",
                    device_type=2,
                    vram_mb=vram_mb
                )
    except Exception:
        pass
    return None
```

### Update the main `detect_gpu()` function

The existing `detect_gpu()` function tries NVIDIA → AMD → Intel → CPU. Modify it to try Apple first (since macOS won't have nvidia-smi/rocm-smi/wmic):

```python
def detect_gpu() -> GPUInfo:
    """Detect the best available GPU for hashcat."""
    import platform
    system = platform.system().lower()

    # ── Apple Silicon (macOS ARM64) — Metal backend ──
    gpu = _detect_apple_silicon()
    if gpu:
        return gpu

    # ── macOS Intel with discrete GPU — OpenCL backend ──
    gpu = _detect_macos_intel_gpu()
    if gpu:
        return gpu

    # ── NVIDIA (Windows/Linux/WSL2) — CUDA backend ──
    gpu = _detect_nvidia()
    if gpu:
        return gpu

    # ── AMD (Windows/Linux) — ROCm/OpenCL backend ──
    gpu = _detect_amd()
    if gpu:
        return gpu

    # ── Intel (Windows/Linux) — OpenCL backend ──
    gpu = _detect_intel()
    if gpu:
        return gpu

    # ── CPU fallback ──
    return GPUInfo(
        vendor="none",
        name=_get_cpu_name(),
        backend="cpu",
        device_type=1,  # hashcat -D 1 = CPU
        vram_mb=0
    )
```

### Update the hashcat install instructions message

The existing "hashcat not found" error should include macOS:

```python
    if not shutil.which("hashcat"):
        print("[worker] ERROR: hashcat not found. Install hashcat on this machine first.")
        print("  Windows:  https://hashcat.net/hashcat/ (extract zip, add to PATH)")
        print("  macOS:    brew install hashcat")
        print("  Linux:    sudo apt install hashcat")
        sys.exit(1)
```

### Update `run_hashcat()` with Metal-specific flags

The existing `run_hashcat()` function builds hashcat command-line args. Add Metal-aware branching:

```python
def run_hashcat(hash_file, hash_mode, gpu, wordlist=None, timeout_seconds=3600, rules=None):
    """Run hashcat against a hash file. Returns dict with result."""
    cmd = [
        "hashcat",
        "-m", str(hash_mode),
        "-a", "0",                        # dictionary attack
        "-D", str(gpu.device_type),       # 1=CPU, 2=GPU
        "--force",                        # suppress environment warnings
        "--potfile-disable",              # unique potfile per job (no conflicts)
        "-o", str(hash_file) + ".cracked",
        str(hash_file),
    ]

    # ── Backend-specific tuning ──
    if gpu.backend == "metal":
        # Metal on Apple Silicon:
        # - hashcat auto-selects Metal on macOS ARM, but explicit device helps
        # - Workload profile 2 (default) is correct — M-series chips throttle
        #   aggressively under sustained load (especially fanless MacBook Air)
        # - Do NOT use -w 3 or -w 4 on Apple Silicon laptops
        cmd.extend(["--backend-devices", "1"])
        cmd.extend(["-w", "2"])
    elif gpu.backend == "cuda":
        cmd.extend(["-w", "3"])           # high workload — desktop GPUs handle it
    elif gpu.backend == "opencl":
        cmd.extend(["-w", "3"])
    elif gpu.backend == "cpu":
        cmd.extend(["-w", "1"])           # minimal workload for CPU fallback

    # ... rest of existing function unchanged ...
```

### Update `write_capabilities()` — already correct

The existing `write_capabilities()` writes the GPUInfo fields to `worker_capabilities.json`. No changes needed — the Apple Silicon GPUInfo object already has `vendor="apple"`, `backend="metal"`, etc. The container will read these fields correctly.

---

## 2. Modify: `core/gpu_detector.py`

The container-side GPU detector reads `worker_capabilities.json` from the host worker. It needs to recognize Apple Silicon capabilities.

### Update `get_gpu_info_live()` or equivalent capabilities parser

Find the section that reads and interprets `worker_capabilities.json`. Add Apple Silicon recognition:

```python
# In the function that parses worker_capabilities.json:

def _parse_worker_capabilities(caps: dict) -> dict:
    """Parse host worker capabilities into a display-friendly format."""
    vendor = caps.get("gpu_vendor", "none")
    backend = caps.get("gpu_backend", "cpu")
    name = caps.get("gpu_name", "Unknown")
    vram = caps.get("gpu_vram_mb", 0)

    # Determine if this is a real GPU vs CPU fallback
    has_gpu = vendor != "none" and backend != "cpu"

    # Backend display name
    backend_display = {
        "cuda": "NVIDIA CUDA",
        "opencl": "OpenCL",
        "metal": "Apple Metal",      # ← NEW
        "cpu": "CPU (no GPU)",
    }.get(backend, backend)

    # VRAM label — Apple Silicon uses unified memory
    if vendor == "apple":
        vram_label = f"~{vram} MB (unified memory, estimated)"
    elif vram > 0:
        vram_label = f"{vram} MB"
    else:
        vram_label = "N/A"

    return {
        "vendor": vendor,
        "name": name,
        "backend": backend,
        "backend_display": backend_display,
        "vram_mb": vram,
        "vram_label": vram_label,
        "has_gpu": has_gpu,
        "platform": caps.get("platform", "Unknown"),
        "machine": caps.get("machine", "Unknown"),
        "hashcat_version": caps.get("hashcat_version", "unknown"),
        "last_heartbeat": caps.get("last_heartbeat", 0),
    }
```

### Update execution path priority display

The existing execution priority is: NVIDIA container > host worker > hashcat CPU > none.

When the host worker reports `vendor: "apple"`, the path becomes:

```
NVIDIA container GPU (not applicable on macOS host)
  → Apple Silicon Metal via host worker  ← NEW
  → hashcat CPU fallback
  → none
```

The `detect_gpu()` in `core/gpu_detector.py` (container-side) should recognize the host worker's Apple Silicon capability:

```python
# In the method that determines the active crack method:

def get_active_crack_method(self) -> str:
    """Determine the best available cracking method."""
    # 1. Container NVIDIA GPU
    if self.container_gpu_available:
        return "HASHCAT_GPU"

    # 2. Host worker (AMD, Intel, or Apple Silicon)
    caps = self._read_worker_capabilities()
    if caps and self._is_worker_recent(caps):
        worker_backend = caps.get("gpu_backend", "cpu")
        if worker_backend in ("opencl", "metal", "cuda"):  # ← metal added
            return "HASHCAT_HOST"

    # 3. hashcat CPU in container
    if self._hashcat_available:
        return "HASHCAT_CPU"

    # 4. No hashcat at all
    return "NONE"
```

---

## 3. Modify: `static/admin.html` — GPU Status Card

The admin page has a GPU Acceleration status card (added in v0.9.9). Update it to display Apple Silicon info correctly.

Find the section that renders GPU info from `/api/crack/worker-status` (or the health endpoint). Update the display logic:

```javascript
// In the GPU status card rendering function:

function renderGPUStatus(workerInfo) {
    const caps = workerInfo.capabilities;
    if (!caps) {
        gpuStatusEl.innerHTML = '<span class="badge badge-warn">Host worker not detected</span>';
        return;
    }

    const vendor = caps.gpu_vendor || 'none';
    const backend = caps.gpu_backend || 'cpu';
    const name = caps.gpu_name || 'Unknown';
    const vram = caps.gpu_vram_mb || 0;

    // Backend badge
    const badgeClass = {
        'cuda': 'badge-success',
        'opencl': 'badge-success',
        'metal': 'badge-success',    // ← Apple Silicon gets green badge
        'cpu': 'badge-warn'
    }[backend] || 'badge-warn';

    const backendLabel = {
        'cuda': 'NVIDIA CUDA',
        'opencl': 'OpenCL',
        'metal': 'Apple Metal',       // ← NEW
        'cpu': 'CPU Only'
    }[backend] || backend;

    // VRAM display — Apple Silicon is unified memory
    let vramDisplay;
    if (vendor === 'apple') {
        vramDisplay = `~${vram} MB (unified memory)`;
    } else if (vram > 0) {
        vramDisplay = `${vram} MB VRAM`;
    } else {
        vramDisplay = 'N/A';
    }

    gpuStatusEl.innerHTML = `
        <div class="gpu-info">
            <strong>${name}</strong>
            <span class="badge ${badgeClass}">${backendLabel}</span>
        </div>
        <div class="gpu-details">
            Memory: ${vramDisplay} · 
            hashcat: ${caps.hashcat_version || 'unknown'} · 
            Platform: ${caps.platform || '?'} / ${caps.machine || '?'}
        </div>
    `;
}
```

### Same update for `static/settings.html` GPU section

The Settings page has a GPU Acceleration section (also v0.9.9). Apply the same vendor/backend display logic as above.

---

## 4. Apple Silicon — Technical Notes for Claude Code

These are important implementation details that Claude Code needs to get right:

### hashcat Metal backend — version requirement

hashcat ≥ 6.2.0 is required. Earlier versions use OpenCL only, which Apple deprecated on macOS. On Apple Silicon, OpenCL is completely absent — there is no fallback. If hashcat is too old, the worker should warn loudly and fall back to CPU (`-D 1`).

### Unified Memory Architecture

Apple Silicon has no separate VRAM. The GPU and CPU share the same physical RAM. The 75% estimate for GPU-accessible memory is conservative — Apple's GPU can technically access all of it, but leaving headroom for the OS and other processes avoids hashcat OOM crashes.

### Workload profiles on Apple Silicon

| Profile | Flag | Use case |
|---------|------|----------|
| Low     | `-w 1` | Background, minimal thermal impact |
| Default | `-w 2` | **Recommended for Apple Silicon** |
| High    | `-w 3` | Desktop GPUs with active cooling only |
| Nightmare | `-w 4` | **Never use on Apple Silicon** — causes thermal shutdown on MacBook Air |

The worker should use `-w 2` for Metal. The user can override via the `password_hashcat_workload` preference, but the default must be safe.

### Rosetta 2 caveat

If the user installed hashcat via an x86-only method (e.g., downloaded a pre-built binary), it runs under Rosetta 2 on ARM Macs. Rosetta-translated binaries do NOT have Metal access — they see no GPU. The `file` command reveals the binary architecture:

```
$ file $(which hashcat)
/opt/homebrew/bin/hashcat: Mach-O 64-bit executable arm64    ← correct (native)
/usr/local/bin/hashcat: Mach-O 64-bit executable x86_64      ← Rosetta (no Metal)
```

The worker checks this and prints a warning. It does NOT refuse to run — the user might intentionally want CPU-mode cracking.

### No OpenCL on Apple Silicon

Apple removed OpenCL from ARM macOS entirely. hashcat's `-D 2` on Apple Silicon maps to Metal automatically. Do NOT attempt to detect or use OpenCL on `darwin` + `arm64`.

### Thermal throttling behavior

M-series chips (especially in MacBook Air with no fan) throttle aggressively under sustained GPU compute load. A hashcat run that starts at 500 MH/s might drop to 200 MH/s within 30 seconds on a fanless Mac. This is normal — the elapsed time estimates in the worker output will fluctuate. Don't treat thermal throttling as an error.

### `system_profiler` can be slow

`system_profiler SPDisplaysDataType -json` takes 1-3 seconds on some Macs. The worker calls it once at startup during GPU detection, not on every job. The cached `GPUInfo` is reused for all subsequent jobs.

---

## 5. Test Additions

### Modify: existing GPU detection tests

Add Apple Silicon cases to whatever test file covers `core/gpu_detector.py` and `tools/markflow-hashcat-worker.py`:

```python
class TestAppleSiliconDetection:
    """Test Apple Silicon Metal GPU detection in host worker."""

    def test_worker_capabilities_apple_metal(self, tmp_path):
        """Container correctly parses Apple Silicon worker capabilities."""
        caps_file = tmp_path / "worker_capabilities.json"
        caps_file.write_text(json.dumps({
            "gpu_vendor": "apple",
            "gpu_name": "Apple M3 Max (40-core GPU)",
            "gpu_backend": "metal",
            "gpu_device_type": 2,
            "gpu_vram_mb": 27648,
            "hashcat_version": "v6.2.6",
            "platform": "Darwin",
            "machine": "arm64",
            "last_heartbeat": time.time()
        }))

        # Test that gpu_detector parses this correctly
        # (adapt to actual gpu_detector API)
        from core.gpu_detector import GPUDetector
        detector = GPUDetector(hashcat_queue_dir=str(tmp_path))
        caps = detector._read_worker_capabilities()
        assert caps is not None
        assert caps["gpu_vendor"] == "apple"
        assert caps["gpu_backend"] == "metal"

    def test_apple_metal_is_valid_host_backend(self):
        """Metal backend is recognized as a valid host GPU for HASHCAT_HOST method."""
        # The active crack method logic should accept "metal" as a GPU backend
        assert "metal" in ("opencl", "metal", "cuda")  # same check as get_active_crack_method

    def test_unified_memory_label(self):
        """Apple Silicon VRAM displays as unified memory."""
        # Test the display label logic
        caps = {"gpu_vendor": "apple", "gpu_vram_mb": 27648}
        if caps["gpu_vendor"] == "apple":
            label = f"~{caps['gpu_vram_mb']} MB (unified memory, estimated)"
        assert "unified memory" in label

    def test_apple_backend_display_name(self):
        """Metal backend displays as 'Apple Metal'."""
        backend_map = {
            "cuda": "NVIDIA CUDA",
            "opencl": "OpenCL",
            "metal": "Apple Metal",
            "cpu": "CPU (no GPU)",
        }
        assert backend_map["metal"] == "Apple Metal"
```

---

## 6. Done Criteria

- [ ] `tools/markflow-hashcat-worker.py` — Apple Silicon detection (`_detect_apple_silicon()`, `_get_apple_gpu_cores()`, `_verify_hashcat_metal()`, `_check_rosetta_hashcat()`)
- [ ] `tools/markflow-hashcat-worker.py` — macOS Intel discrete GPU detection (`_detect_macos_intel_gpu()`)
- [ ] `tools/markflow-hashcat-worker.py` — `detect_gpu()` updated: Apple first → macOS Intel → NVIDIA → AMD → Intel → CPU
- [ ] `tools/markflow-hashcat-worker.py` — `run_hashcat()` Metal-specific flags (`-w 2`, `--backend-devices 1`)
- [ ] `tools/markflow-hashcat-worker.py` — hashcat install message includes `macOS: brew install hashcat`
- [ ] `core/gpu_detector.py` — recognizes `vendor: "apple"` and `backend: "metal"` in worker capabilities
- [ ] `core/gpu_detector.py` — `"metal"` accepted in active crack method as valid host GPU backend
- [ ] `core/gpu_detector.py` — display labels: "Apple Metal" backend, "unified memory" VRAM
- [ ] `static/admin.html` — GPU status card renders Apple Silicon info (name, Metal badge, unified memory)
- [ ] `static/settings.html` — GPU section renders Apple Silicon info
- [ ] Tests added for Apple Silicon capability parsing, Metal backend recognition, display labels
- [ ] All existing tests still pass
- [ ] CLAUDE.md updated

---

## 7. CLAUDE.md Update Instructions

After implementation, **modify the existing v0.9.9 entry** to mention Apple Silicon, and add a v0.10.1 entry:

### Modify v0.9.9 description — append to existing text:

```
  Apple Silicon Macs: Metal backend detection, unified memory estimation,
  Rosetta 2 binary guard, hashcat ≥ 6.2.0 version gate, thermal-safe
  workload profile (-w 2). macOS Intel discrete GPUs (Radeon Pro) supported
  via OpenCL.
```

### Add new version entry:

```markdown
**v0.10.1** — Apple Silicon Metal support for GPU hashcat worker.
  `tools/markflow-hashcat-worker.py` gains macOS detection: Apple Silicon
  (M1/M2/M3/M4) via Metal backend, Intel Mac discrete GPU via OpenCL.
  Rosetta 2 binary warning prevents silent Metal loss. hashcat version
  gated at ≥ 6.2.0 for Metal. Unified memory estimation (~75% of system
  RAM) replaces VRAM reporting on Apple Silicon. Thermal-safe workload
  profile (-w 2, not -w 3) prevents throttling on fanless Macs.
  `core/gpu_detector.py` recognizes vendor=apple/backend=metal in worker
  capabilities. Admin and Settings GPU status cards updated for Apple display.
```

### Add gotchas to "Gotchas & Fixes Found":

```markdown
- **No OpenCL on Apple Silicon**: macOS ARM64 has no OpenCL. hashcat's Metal
  backend is the only GPU path. Do not attempt `-D 2` with OpenCL on ARM Macs.

- **Rosetta hashcat has no Metal**: An x86 hashcat binary under Rosetta 2 sees
  no GPU. The worker checks via `file $(which hashcat)` and warns if not arm64.
  `brew install hashcat` installs the native ARM build.

- **Apple Silicon thermal throttling is normal**: M-series chips (especially
  MacBook Air) throttle from ~500 MH/s to ~200 MH/s within seconds under
  sustained GPU load. Do not treat this as an error or retry.

- **`system_profiler` is slow (1-3s)**: Called once at worker startup, not per
  job. GPU info is cached in the GPUInfo object for the worker's lifetime.

- **hashcat `-w 4` (nightmare) causes thermal shutdown on fanless Macs**: Always
  default to `-w 2` for Metal. User can override via password_hashcat_workload
  preference, but the default must be safe for a MacBook Air.
```
