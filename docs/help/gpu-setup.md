# GPU Setup

MarkFlow uses GPU acceleration for **password cracking** via hashcat. This
dramatically speeds up brute-force and mask attacks compared to CPU-only
execution. A modern GPU can test millions of password candidates per second.

There are two paths to GPU acceleration, depending on your hardware.

---

## Two Paths

| Path | GPU Vendor | Where Hashcat Runs | Setup Complexity |
|------|-----------|-------------------|-----------------|
| **Container path** | NVIDIA only | Inside the Docker container | Moderate -- requires NVIDIA Container Toolkit |
| **Host worker path** | NVIDIA, AMD, Intel | On your host machine (outside Docker) | Easy -- install hashcat and run a script |

MarkFlow detects which path is available at startup and picks the best one
automatically. The resolution priority is:

1. **NVIDIA container GPU** -- nvidia-smi + hashcat with CUDA/OpenCL inside the container
2. **Host worker GPU** -- host worker has reported its capabilities
3. **Hashcat CPU** -- hashcat installed in container but no GPU detected
4. **None** -- hashcat not installed

---

## NVIDIA Container Path (Auto-Detected)

This passes your NVIDIA GPU directly into the Docker container. It works on
Linux hosts and Windows hosts running WSL2 with Docker Desktop.

### Prerequisites

- An NVIDIA GPU with up-to-date drivers
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed on the host
- Docker configured to use the NVIDIA runtime

### Step 1: Install NVIDIA Container Toolkit

On Ubuntu/Debian:

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

On Windows with Docker Desktop and WSL2, GPU passthrough works automatically
if the NVIDIA driver is installed on the Windows host.

### Step 2: Use the GPU Docker Compose Overlay

MarkFlow includes a `docker-compose.gpu.yml` overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

> **Warning:** Do not use the GPU overlay if you do not have an NVIDIA GPU
> or the Container Toolkit installed. Docker will fail to start the container.

### Step 3: Verify

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

Look for `components.gpu.execution_path: "container"` and your GPU name under
`effective_gpu`. You can also check the Settings page GPU Acceleration card.

---

## AMD / Intel Host Worker Path

AMD and Intel GPUs cannot be passed into Docker containers. Instead, MarkFlow
uses a **host worker** -- a Python script that runs on your host machine with
native GPU access. This also works for NVIDIA if you prefer to skip the
Container Toolkit.

### Step 1: Install Hashcat on Your Host

**Windows:** `winget install hashcat.hashcat` or download from
[hashcat.net](https://hashcat.net/hashcat/).

**Linux:** `sudo apt-get install hashcat`

**macOS:** `brew install hashcat`

Verify with `hashcat --version` and `hashcat -I` (shows detected compute devices).

> **Tip:** For AMD GPUs on Linux, install ROCm drivers. For Intel GPUs,
> install the Intel OpenCL runtime. Hashcat detects backends automatically.

### Step 2: Set Up the Shared Queue Directory

Create a directory and mount it in Docker Compose:

```bash
mkdir -p /path/to/hashcat-queue
```

Add to `docker-compose.yml` under the `markflow` service:

```yaml
volumes:
  - /path/to/hashcat-queue:/mnt/hashcat-queue
```

Rebuild and restart the container.

### Step 3: Run the Host Worker Script

```bash
python tools/markflow-hashcat-worker.py --queue-dir /path/to/hashcat-queue
```

The worker detects your GPU, writes `worker_capabilities.json`, and begins
watching for jobs. You should see:

```
[worker] GPU: AMD Radeon RX 7900 XTX (amd)
[worker] Hashcat: v6.2.6 (backend: ROCm)
[worker] Watching /path/to/hashcat-queue/jobs
[worker] Press Ctrl+C to stop.
```

> **Warning:** Keep the worker running while MarkFlow processes password-
> protected files. If the worker is stopped, jobs time out after the
> configured timeout plus a 120-second grace window.

### Step 4: Verify

Check `GET /api/health` for `components.gpu.execution_path: "host"` and your
GPU under `host_worker`. The Settings page GPU card shows "AMD (Host Worker)"
or similar.

---

## The docker-compose.gpu.yml Overlay

Only needed for the NVIDIA container path. Full content:

```yaml
services:
  markflow:
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
```

To stop using GPU passthrough, simply omit the overlay file:
`docker compose up -d`.

---

## Verifying GPU Detection via the Health Endpoint

The `GET /api/health` endpoint always includes `components.gpu`. Here is
what each `execution_path` value means:

| Value | Meaning |
|-------|---------|
| `container` | NVIDIA GPU available inside container with CUDA or OpenCL |
| `host` | Host worker detected with a GPU backend |
| `container_cpu` | Hashcat installed but no GPU; CPU fallback |
| `none` | Hashcat not installed; GPU cracking unavailable |

Quick check script:

```bash
curl -s http://localhost:8000/api/health | python3 -c "
import sys, json
data = json.load(sys.stdin)
gpu = data.get('components', {}).get('gpu', {})
print(f\"Path: {gpu.get('execution_path')}\")
print(f\"GPU: {gpu.get('effective_gpu', 'none')}\")
print(f\"Backend: {gpu.get('effective_backend', 'none')}\")
"
```

---

## How Jobs Flow Between MarkFlow and the Host Worker

1. MarkFlow extracts a hash from the encrypted file.
2. Hash written to `/mnt/hashcat-queue/hashes/<job_id>.hash`.
3. Job description written to `/mnt/hashcat-queue/jobs/<job_id>.json`.
4. Host worker picks up the job, runs hashcat, writes result to
   `/mnt/hashcat-queue/results/<job_id>.json`.
5. MarkFlow polls for the result (every 1 second).
6. On success, MarkFlow uses the cracked password to decrypt the file.
7. Temporary files are cleaned up by both sides.

---

## Troubleshooting

### "hashcat not found on host"

Install hashcat and ensure it is on your PATH. Run `hashcat --version`.

### Worker says "No GPU detected"

GPU drivers may not be installed. Run `hashcat -I` to check detected devices.
For AMD install ROCm; for Intel install the OpenCL runtime.

### Container GPU shows "none" despite NVIDIA GPU

Ensure you are using the GPU overlay and the Container Toolkit is installed.
Test with `docker compose exec markflow nvidia-smi`.

### Jobs time out without cracking

Normal for strong passwords. Increase the timeout or reduce the brute-force
length in Settings. GPU acceleration helps but cannot crack every password.

---

## Performance Expectations

| Encryption | Typical Speed (mid-range GPU) |
|-----------|------------------------------|
| PDF RC4 (older PDFs) | Millions of attempts/second |
| PDF AES-256 (modern PDFs) | Thousands of attempts/second |
| Office 2013+ AES-256 | Thousands of attempts/second |
| Office 97-03 RC4 | Millions of attempts/second |

> **Tip:** Start with the dictionary attack before brute-force. Most
> real-world passwords are in common wordlists and their mutations.

---

## Related

- [Password Recovery](/help#password-recovery) -- full cracking cascade and settings
- [Settings Guide](/help#settings-guide) -- hashcat workload profile and timeout settings
