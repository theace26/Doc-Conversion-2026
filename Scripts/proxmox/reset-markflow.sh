#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MarkFlow Docker Reset & Rebuild Script (Proxmox VM)
#  Tears down everything, force-pulls latest from GitHub,
#  auto-detects GPU, writes .env for NAS mounts, rebuilds.
#
#  Usage:
#    chmod +x ~/reset-markflow.sh && ~/reset-markflow.sh
#    ./reset-markflow.sh --skip-prune
#    ./reset-markflow.sh --source /mnt/custom --output /mnt/out
# ============================================================

# ── Defaults ────────────────────────────────────────────────────
REPO_DIR="/opt/doc-conversion-2026"
SOURCE_DIR="/mnt/source-share"
OUTPUT_DIR="/mnt/markflow-output"
SKIP_PRUNE=false
DEV_MODE=false

# ── Parse args ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)        REPO_DIR="$2"; shift 2 ;;
        --source)      SOURCE_DIR="$2"; shift 2 ;;
        --output)      OUTPUT_DIR="$2"; shift 2 ;;
        --skip-prune)  SKIP_PRUNE=true; shift ;;
        --dev)         DEV_MODE=true; shift ;;   # enables DEV_BYPASS_AUTH
        --gpu)         shift ;;  # legacy flag, ignored (auto-detect now)
        *)             echo "Unknown arg: $1"; exit 1 ;;
    esac
done

COMPOSE_FILE="$REPO_DIR/docker-compose.yml"

echo "=========================================="
echo "  MarkFlow Docker Reset & Rebuild"
echo "  Machine: Proxmox VM (Linux)"
echo "=========================================="

# ----------------------------------------------------------
#  Disk Space Check
# ----------------------------------------------------------
AVAIL_GB=$(df -BG / | awk 'NR==2 {gsub("G",""); print $4}')
if [[ "${AVAIL_GB:-0}" -lt 10 ]]; then
    echo "  ⚠️  WARNING: Only ${AVAIL_GB}GB free on /. Docker builds may fail."
    echo "     Free space before continuing: docker system prune -f"
else
    echo "  [OK] Disk space: ${AVAIL_GB}GB free"
fi

# ----------------------------------------------------------
#  GPU Auto-Detection
# ----------------------------------------------------------
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

# -- worker_capabilities.json is written after git pull (step 2) --
# so that git reset --hard doesn't overwrite it with stale data

# -- Summary --
if $USE_NVIDIA_OVERLAY; then
    echo "  [GPU] NVIDIA container passthrough: ENABLED"
elif [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo "  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo "  [GPU] GPU found but hashcat not installed -- install hashcat for GPU cracking"
fi

# ── Build compose args ──────────────────────────────────────────
COMPOSE_ARGS=("-f" "$COMPOSE_FILE")

if $USE_NVIDIA_OVERLAY; then
    COMPOSE_ARGS+=("-f" "$REPO_DIR/docker-compose.gpu.yml")
fi

# ----------------------------------------------------------
#  1. Tear down everything
# ----------------------------------------------------------
echo ""
echo "[1/5] Tearing down containers, volumes, and images..."
cd "$REPO_DIR"

docker compose "${COMPOSE_ARGS[@]}" down -v 2>/dev/null || true

if ! $SKIP_PRUNE; then
    echo "  Pruning dangling images and build cache (preserving markflow-base)..."
    # Only prune dangling images — NOT volumes (docker compose down -v already removed ours)
    # docker system prune --volumes would nuke ALL unused volumes on the host, not just ours
    docker image prune -f
    # Remove markflow app images but preserve the base image
    docker images "markflow-*" --format "{{.Repository}}:{{.Tag}}" \
        | grep -v "markflow-base:latest" \
        | xargs -r docker rmi 2>/dev/null || true
fi

# Build base image if missing
if ! docker images markflow-base:latest -q | grep -q .; then
    echo ""
    echo "  [!] markflow-base:latest not found -- building it now..."
    echo "  (This is the slow step -- only needed once)"
    docker build -f "$REPO_DIR/Dockerfile.base" -t markflow-base:latest "$REPO_DIR"
fi

# ----------------------------------------------------------
#  2. Force-pull latest code from GitHub
# ----------------------------------------------------------
echo ""
echo "[2/5] Force-pulling latest code from GitHub..."

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

# ----------------------------------------------------------
#  3. Configure .env for Proxmox VM (NAS mounts)
# ----------------------------------------------------------
echo ""
echo "[3/5] Configuring .env for Proxmox VM..."

ENV_FILE="$REPO_DIR/.env"

cat > "$ENV_FILE" << ENV_CONTENT
# MarkFlow Environment Configuration
# Proxmox VM (Linux) - auto-generated by reset-markflow.sh
# Run with --dev to enable DEV_BYPASS_AUTH (development only)

# Host paths - mounted into Docker containers
SOURCE_DIR=$SOURCE_DIR
OUTPUT_DIR=$OUTPUT_DIR
DRIVE_C=$SOURCE_DIR
DRIVE_D=$OUTPUT_DIR

# Meilisearch — set a real key before exposing port 7700 to the network
MEILI_MASTER_KEY=

# Bulk conversion
BULK_WORKER_COUNT=4

# App — replace SECRET_KEY with: openssl rand -hex 32
SECRET_KEY=dev-secret-change-in-prod
DEFAULT_LOG_LEVEL=normal
DEV_BYPASS_AUTH=$DEV_MODE
ENV_CONTENT

if $DEV_MODE; then
    echo "  ⚠️  DEV_MODE: DEV_BYPASS_AUTH=true — authentication disabled"
else
    echo "  [OK] Auth enabled (DEV_BYPASS_AUTH=false)"
fi

echo "  [OK] .env written"
echo "    SOURCE_DIR = $SOURCE_DIR"
echo "    OUTPUT_DIR = $OUTPUT_DIR"

# ----------------------------------------------------------
#  4. Verify paths exist
# ----------------------------------------------------------
echo ""
echo "[4/5] Verifying paths..."

if [[ -d "$SOURCE_DIR" ]]; then
    SOURCE_COUNT=$(find "$SOURCE_DIR" -maxdepth 3 -type f 2>/dev/null | wc -l | xargs)
    echo "  [OK] Source dir exists ($SOURCE_COUNT files in top 3 levels)"
else
    echo "  [!] Source dir not found: $SOURCE_DIR"
    echo "      Check NAS mount: mount -a"
fi

if [[ -d "$OUTPUT_DIR" ]]; then
    echo "  [OK] Output dir exists"
else
    echo "  [!] Output dir not found: $OUTPUT_DIR -- creating it..."
    sudo mkdir -p "$OUTPUT_DIR"
    echo "  [OK] Output dir created"
fi

# ----------------------------------------------------------
#  5. Rebuild and start
# ----------------------------------------------------------
echo ""
echo "[5/5] Building and starting MarkFlow..."
docker compose "${COMPOSE_ARGS[@]}" up -d --build

# ----------------------------------------------------------
#  Auto-start hashcat host worker (non-NVIDIA or no toolkit)
# ----------------------------------------------------------
if [[ -n "$HASHCAT_PATH" && "$GPU_VENDOR" != "none" && "$USE_NVIDIA_OVERLAY" == "false" ]]; then
    WORKER_SCRIPT="$REPO_DIR/tools/markflow-hashcat-worker.py"
    WORKER_PID_FILE="$QUEUE_DIR/worker.pid"
    if [[ -f "$WORKER_SCRIPT" ]]; then
        echo ""
        echo "[GPU] Starting hashcat host worker in background..."
        # Kill any stale worker from a previous run before starting a new one
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

# ----------------------------------------------------------
#  Health Check
# ----------------------------------------------------------
echo ""
echo "Waiting for MarkFlow to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
        echo "  [OK] MarkFlow is up and healthy"
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo "  ⚠️  Health check timed out after 60s"
        echo "     Check logs: docker compose logs markflow"
    else
        sleep 2
    fi
done

# ----------------------------------------------------------
#  Done
# ----------------------------------------------------------
echo ""
echo "=========================================="
echo "  Reset Complete!"
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
