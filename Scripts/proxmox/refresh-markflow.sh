#!/usr/bin/env bash
#
# MarkFlow Quick Refresh (Proxmox VM)
#
# Unlike reset-markflow.sh, this keeps your database, Meilisearch index,
# and converted output intact. It only:
#   1. Force-pulls latest code from GitHub
#   2. Auto-detects GPU hardware on the host
#   3. Rebuilds the Docker images with the new code
#   4. Restarts the containers (with NVIDIA passthrough if applicable)
#   5. Starts the hashcat host worker for non-NVIDIA GPUs (if hashcat installed)
#
# Usage:
#   ./refresh-markflow.sh                  # auto-detects GPU
#   ./refresh-markflow.sh --no-build       # just restart, skip rebuild
#   ./refresh-markflow.sh --repo /path     # custom repo location

set -euo pipefail

# -- Defaults ----------------------------------------------------
REPO_DIR="/opt/doc-conversion-2026"
NO_BUILD=false

# -- Parse args --------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)      REPO_DIR="$2"; shift 2 ;;
        --no-build)  NO_BUILD=true; shift ;;
        --gpu)       shift ;;  # legacy flag, ignored (auto-detect now)
        *)           echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "=========================================="
echo "  MarkFlow Quick Refresh"
echo "  Machine: Proxmox VM (Linux)"
echo "=========================================="

# -- GPU Auto-Detection ------------------------------------------
echo ""
echo "[GPU] Detecting host GPU hardware..."

GPU_VENDOR="none"
GPU_NAME=""
GPU_VRAM_MB=0
USE_NVIDIA_OVERLAY=false
HASHCAT_PATH=""
HASHCAT_VERSION=""
HASHCAT_BACKEND=""

OS_NAME="$(uname -s)"
MACHINE="$(uname -m)"

# -- Linux: NVIDIA via nvidia-smi --
if [[ "$OS_NAME" == "Linux" ]] && command -v nvidia-smi &>/dev/null; then
    NVIDIA_OUT=$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null || true)
    if [[ -n "$NVIDIA_OUT" ]]; then
        GPU_VENDOR="nvidia"
        GPU_NAME=$(echo "$NVIDIA_OUT" | cut -d',' -f1 | xargs)
        GPU_VRAM_MB=$(echo "$NVIDIA_OUT" | cut -d',' -f2 | xargs | cut -d'.' -f1)
        if [[ -f "$REPO_DIR/docker-compose.gpu.yml" ]]; then
            USE_NVIDIA_OVERLAY=true
        fi
        echo "  [OK] NVIDIA GPU: $GPU_NAME ($GPU_VRAM_MB MB)"
    fi
fi

# -- Linux: AMD via rocm-smi --
if [[ "$GPU_VENDOR" == "none" && "$OS_NAME" == "Linux" ]] && command -v rocm-smi &>/dev/null; then
    AMD_NAME=$(rocm-smi --showproductname 2>/dev/null | grep -v "^=" | head -1 | xargs || true)
    if [[ -n "$AMD_NAME" ]]; then
        GPU_VENDOR="amd"
        GPU_NAME="$AMD_NAME"
        echo "  [OK] AMD GPU: $GPU_NAME"
    fi
fi

# -- Linux: Intel via clinfo --
if [[ "$GPU_VENDOR" == "none" && "$OS_NAME" == "Linux" ]] && command -v clinfo &>/dev/null; then
    if clinfo --list 2>/dev/null | grep -qi "intel"; then
        GPU_VENDOR="intel"
        GPU_NAME="Intel GPU (via OpenCL)"
        echo "  [OK] Intel GPU detected via OpenCL"
    fi
fi

if [[ "$GPU_VENDOR" == "none" ]]; then
    echo "  [--] No supported GPU detected"
fi

# -- Check for hashcat (auto-install if missing) --
if ! command -v hashcat &>/dev/null; then
    echo "  [--] hashcat not found -- attempting auto-install..."
    if command -v apt-get &>/dev/null; then
        echo "  Installing via apt (may prompt for sudo password)..."
        sudo apt-get install -y hashcat 2>/dev/null && echo "  [OK] hashcat installed via apt" || \
            echo "  [WARN] apt install failed -- install manually: sudo apt-get install hashcat"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y hashcat 2>/dev/null && echo "  [OK] hashcat installed via dnf" || \
            echo "  [WARN] dnf install failed -- install manually: sudo dnf install hashcat"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm hashcat 2>/dev/null && echo "  [OK] hashcat installed via pacman" || \
            echo "  [WARN] pacman install failed -- install manually: sudo pacman -S hashcat"
    else
        echo "  [WARN] No supported package manager found -- install hashcat manually"
        echo "         https://hashcat.net/hashcat/"
    fi
fi

if command -v hashcat &>/dev/null; then
    HASHCAT_PATH=$(command -v hashcat)
    HASHCAT_VERSION=$(hashcat --version 2>/dev/null | tr -d '\n' || echo "unknown")
    echo "  [OK] hashcat: $HASHCAT_VERSION"

    # Probe backend (hashcat resolves OpenCL/ relative to cwd, so cd to its dir)
    HASHCAT_DIR=$(dirname "$HASHCAT_PATH")
    BACKEND_OUT=$(cd "$HASHCAT_DIR" && hashcat -I 2>&1 | tr '[:upper:]' '[:lower:]' || true)
    if echo "$BACKEND_OUT" | grep -q "cuda"; then
        HASHCAT_BACKEND="CUDA"
    elif echo "$BACKEND_OUT" | grep -q "rocm"; then
        HASHCAT_BACKEND="ROCm"
    elif echo "$BACKEND_OUT" | grep -q "opencl" && echo "$BACKEND_OUT" | grep -q "gpu"; then
        HASHCAT_BACKEND="OpenCL"
    elif echo "$BACKEND_OUT" | grep -q "opencl"; then
        HASHCAT_BACKEND="OpenCL-CPU"
    fi
    if [[ -n "$HASHCAT_BACKEND" ]]; then
        echo "  [OK] hashcat backend: $HASHCAT_BACKEND"
    fi
else
    echo "  [--] hashcat unavailable (GPU cracking disabled)"
fi

# -- worker_capabilities.json is written after git pull (step 1) --
# so that git reset --hard doesn't overwrite it with stale data

# -- Summary --
if $USE_NVIDIA_OVERLAY; then
    echo "  [GPU] NVIDIA container passthrough: ENABLED"
elif [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo "  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo "  [GPU] GPU found but hashcat not installed -- install hashcat for GPU cracking"
fi

# -- Build compose args ------------------------------------------
COMPOSE_ARGS=("-f" "$REPO_DIR/docker-compose.yml")

if $USE_NVIDIA_OVERLAY; then
    COMPOSE_ARGS+=("-f" "$REPO_DIR/docker-compose.gpu.yml")
fi

# -- 1. Pull latest code ----------------------------------------
echo ""
echo "[1/3] Pulling latest code from GitHub..."

git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" reset --hard origin/main

COMMIT=$(git -C "$REPO_DIR" log -1 --format="%h %s")
echo "  [OK] Now at: $COMMIT"

# -- Write worker_capabilities.json (after git pull so reset --hard doesn't overwrite) --
QUEUE_DIR="$REPO_DIR/hashcat-queue"
mkdir -p "$QUEUE_DIR"

cat > "$QUEUE_DIR/worker_capabilities.json" <<CAPS
{
  "available": $([ "$GPU_VENDOR" != "none" ] && echo "true" || echo "false"),
  "gpu_vendor": "$GPU_VENDOR",
  "gpu_name": "$GPU_NAME",
  "gpu_vram_mb": $GPU_VRAM_MB,
  "hashcat_backend": $([ -n "$HASHCAT_BACKEND" ] && echo "\"$HASHCAT_BACKEND\"" || echo "null"),
  "hashcat_version": $([ -n "$HASHCAT_VERSION" ] && echo "\"$HASHCAT_VERSION\"" || echo "null"),
  "host_os": "$OS_NAME",
  "host_machine": "$MACHINE",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
CAPS
echo "  [OK] worker_capabilities.json written"

# -- 2. Rebuild (or skip) ---------------------------------------
echo ""

if $NO_BUILD; then
    echo "[2/3] Skipping rebuild (--no-build flag)"
else
    echo "[2/3] Rebuilding Docker images..."
    docker compose "${COMPOSE_ARGS[@]}" build
    echo "  [OK] Build complete"
fi

# -- 3. Restart containers --------------------------------------
echo ""
echo "[3/3] Restarting containers..."

# Stop any stale containers from a previous compose project that may be
# holding ports (e.g. project name 'markflow' left over from an earlier run)
for STALE_PROJECT in markflow; do
    if docker compose -p "$STALE_PROJECT" ps -q 2>/dev/null | grep -q .; then
        echo "  [--] Stopping stale project '$STALE_PROJECT'..."
        docker compose -p "$STALE_PROJECT" down
    fi
done

docker compose "${COMPOSE_ARGS[@]}" up -d

# -- Auto-start hashcat host worker -----------------------------
if [[ -n "$HASHCAT_PATH" && "$GPU_VENDOR" != "none" && "$USE_NVIDIA_OVERLAY" == "false" ]]; then
    WORKER_SCRIPT="$REPO_DIR/tools/markflow-hashcat-worker.py"
    WORKER_PID_FILE="$QUEUE_DIR/worker.pid"
    if [[ -f "$WORKER_SCRIPT" ]]; then
        echo ""
        echo "[GPU] Starting hashcat host worker in background..."
        # Kill any stale worker before starting a new one
        if [[ -f "$WORKER_PID_FILE" ]] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
            echo "  [--] Stopping existing worker (PID: $(cat "$WORKER_PID_FILE"))..."
            kill "$(cat "$WORKER_PID_FILE")" 2>/dev/null || true
            sleep 1
        fi
        nohup python3 "$WORKER_SCRIPT" --queue-dir "$QUEUE_DIR" > "$QUEUE_DIR/worker.log" 2>&1 &
        echo $! > "$WORKER_PID_FILE"
        echo "  [OK] Host worker started (PID: $!, log: $QUEUE_DIR/worker.log)"
    fi
fi

# -- Health Check ------------------------------------------------
echo ""
echo "Waiting for MarkFlow to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "  [OK] MarkFlow is up and healthy"
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo "  [!!]  Health check timed out after 60s"
        echo "     Check logs: docker compose logs markflow"
    else
        sleep 2
    fi
done

# -- Done --------------------------------------------------------
echo ""
echo "=========================================="
echo "  Refresh Complete!"
echo "=========================================="
echo ""

docker compose "${COMPOSE_ARGS[@]}" ps

VM_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/{print $7; exit}')
echo ""
echo "  MarkFlow UI:  http://$VM_IP:8000"
echo "  Meilisearch:  http://$VM_IP:7700"
echo "  MCP Server:   http://$VM_IP:8001"
if $USE_NVIDIA_OVERLAY; then
    echo "  GPU Mode:     NVIDIA container passthrough"
elif [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo "  GPU Mode:     $GPU_NAME (host worker)"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo "  GPU Mode:     $GPU_NAME (hashcat not installed)"
else
    echo "  GPU Mode:     None detected"
fi
echo "=========================================="
