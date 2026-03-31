#!/usr/bin/env bash
#
# MarkFlow Quick Refresh (macOS / Linux)
#
# Pulls latest code, auto-detects GPU, rebuilds, restarts containers,
# and starts the hashcat host worker if applicable.
#
# Usage:
#   ./refresh-markflow.sh                  # auto-detects GPU
#   ./refresh-markflow.sh --no-build       # just restart, skip rebuild
#   ./refresh-markflow.sh --repo /path     # custom repo location

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
NO_BUILD=false

# ── Parse args ──────────────────────────────────────────────────────
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
echo "=========================================="

# ── GPU Auto-Detection ──────────────────────────────────────────────
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

# -- Apple Silicon (macOS ARM64) --
if [[ "$OS_NAME" == "Darwin" && "$MACHINE" == "arm64" ]]; then
    CHIP_NAME=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)
    if [[ "$CHIP_NAME" == Apple* ]]; then
        GPU_VENDOR="apple"
        # Get GPU core count from system_profiler
        GPU_CORES=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -i "total number of cores" | head -1 | awk -F: '{print $2}' | tr -d ' ' || true)
        if [[ -n "$GPU_CORES" ]]; then
            GPU_NAME="$CHIP_NAME (${GPU_CORES}-core GPU)"
        else
            GPU_NAME="$CHIP_NAME"
        fi
        # Estimate VRAM from unified memory (~75% GPU-accessible)
        TOTAL_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        GPU_VRAM_MB=$(( TOTAL_RAM_BYTES / 1048576 * 75 / 100 ))
        echo "  [OK] Apple Silicon: $GPU_NAME ($GPU_VRAM_MB MB estimated GPU memory)" | sed 's/\x1b\[[0-9;]*m//g'
    fi
fi

# -- macOS Intel with discrete GPU --
if [[ "$GPU_VENDOR" == "none" && "$OS_NAME" == "Darwin" && "$MACHINE" == "x86_64" ]]; then
    DISCRETE=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -i "chipset model" | head -1 | awk -F: '{print $2}' | xargs || true)
    if [[ -n "$DISCRETE" ]]; then
        DISCRETE_LOWER=$(echo "$DISCRETE" | tr '[:upper:]' '[:lower:]')
        if [[ "$DISCRETE_LOWER" == *"amd"* || "$DISCRETE_LOWER" == *"radeon"* ]]; then
            GPU_VENDOR="amd"
            GPU_NAME="$DISCRETE"
            echo "  [OK] AMD GPU: $GPU_NAME"
        elif [[ "$DISCRETE_LOWER" == *"nvidia"* ]]; then
            GPU_VENDOR="nvidia"
            GPU_NAME="$DISCRETE"
            echo "  [OK] NVIDIA GPU: $GPU_NAME (host worker path on macOS)"
        fi
    fi
fi

# -- Linux: NVIDIA via nvidia-smi --
if [[ "$GPU_VENDOR" == "none" && "$OS_NAME" == "Linux" ]] && command -v nvidia-smi &>/dev/null; then
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
    if [[ "$OS_NAME" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install hashcat 2>/dev/null && echo "  [OK] hashcat installed via Homebrew" || \
                echo "  [WARN] brew install hashcat failed -- install manually: brew install hashcat"
        else
            echo "  [WARN] Homebrew not found -- install hashcat manually:"
            echo "         /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo "         brew install hashcat"
        fi
    else
        # Linux -- try apt, fall back to instructions
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
fi

if command -v hashcat &>/dev/null; then
    HASHCAT_PATH=$(command -v hashcat)
    HASHCAT_VERSION=$(hashcat --version 2>/dev/null | tr -d '\n' || echo "unknown")
    echo "  [OK] hashcat: $HASHCAT_VERSION"

    # Probe backend
    BACKEND_OUT=$(hashcat -I 2>&1 | tr '[:upper:]' '[:lower:]' || true)
    if echo "$BACKEND_OUT" | grep -q "metal"; then
        HASHCAT_BACKEND="Metal"
    elif echo "$BACKEND_OUT" | grep -q "cuda"; then
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

    # Warn about Rosetta on Apple Silicon
    if [[ "$OS_NAME" == "Darwin" && "$MACHINE" == "arm64" && -n "$HASHCAT_PATH" ]]; then
        FILE_INFO=$(file "$HASHCAT_PATH" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)
        if [[ "$FILE_INFO" != *"arm64"* ]]; then
            echo "  [WARN] hashcat binary appears to be x86 (Rosetta 2)"
            echo "         Metal GPU acceleration will NOT work under Rosetta"
            echo "         Fix: brew install hashcat  (installs native ARM64 build)"
        fi
    fi
else
    echo "  [--] hashcat unavailable (GPU cracking disabled)"
fi

# -- Write worker_capabilities.json --
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

# -- Summary --
if $USE_NVIDIA_OVERLAY; then
    echo "  [GPU] NVIDIA container passthrough: ENABLED"
elif [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo "  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo "  [GPU] GPU found but hashcat not installed -- install hashcat for GPU cracking"
fi

# ── Build compose args ──────────────────────────────────────────────
COMPOSE_ARGS=("-f" "$REPO_DIR/docker-compose.yml")

if $USE_NVIDIA_OVERLAY; then
    COMPOSE_ARGS+=("-f" "$REPO_DIR/docker-compose.gpu.yml")
fi

# ── 1. Pull latest code ────────────────────────────────────────────
echo ""
echo "[1/3] Pulling latest code from GitHub..."

git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" reset --hard origin/main

COMMIT=$(git -C "$REPO_DIR" log -1 --format="%h %s")
echo "  [OK] Now at: $COMMIT"

# ── 2. Rebuild (or skip) ───────────────────────────────────────────
echo ""

if $NO_BUILD; then
    echo "[2/3] Skipping rebuild (--no-build flag)"
else
    echo "[2/3] Rebuilding Docker images..."
    docker compose "${COMPOSE_ARGS[@]}" build
    echo "  [OK] Build complete"
fi

# ── 3. Restart containers ──────────────────────────────────────────
echo ""
echo "[3/3] Restarting containers..."

docker compose "${COMPOSE_ARGS[@]}" up -d

# ── Auto-start hashcat host worker ─────────────────────────────────
if [[ -n "$HASHCAT_PATH" && "$GPU_VENDOR" != "none" && "$USE_NVIDIA_OVERLAY" == "false" ]]; then
    WORKER_SCRIPT="$REPO_DIR/tools/markflow-hashcat-worker.py"
    if [[ -f "$WORKER_SCRIPT" ]]; then
        echo ""
        echo "[GPU] Starting hashcat host worker in background..."
        nohup python3 "$WORKER_SCRIPT" --queue-dir "$QUEUE_DIR" > "$QUEUE_DIR/worker.log" 2>&1 &
        echo "  [OK] Host worker started (PID: $!, log: $QUEUE_DIR/worker.log)"
    fi
fi

# ── Done ────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Refresh Complete!"
echo "=========================================="
echo ""

docker compose "${COMPOSE_ARGS[@]}" ps

echo ""
echo "  MarkFlow UI:  http://localhost:8000"
echo "  Meilisearch:  http://localhost:7700"
echo "  MCP Server:   http://localhost:8001"
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
