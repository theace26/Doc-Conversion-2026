#!/usr/bin/env bash
# --------------------------------------------------------------
# MarkFlow Quick Refresh (macOS - personal machine)
#
# Pulls latest code and rebuilds without wiping data.
# Your database, Meilisearch index, and converted files are preserved.
#
# Usage:
#   ./refresh-markflow.sh                    # auto-detects everything
#   ./refresh-markflow.sh --no-build         # just restart, skip rebuild
#   ./refresh-markflow.sh --repo /my/path    # custom repo location
# --------------------------------------------------------------

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRAY='\033[0;90m'
NC='\033[0m'

# -- Defaults --
REPO_DIR=""
NO_BUILD=false

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_DIR="$2"; shift 2 ;;
        --no-build) NO_BUILD=true; shift ;;
        *)          echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# ==============================================================
#  Locate the repository
# ==============================================================
if [[ -z "$REPO_DIR" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CANDIDATE="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd)"
    if [[ -f "$CANDIDATE/docker-compose.yml" ]]; then
        REPO_DIR="$CANDIDATE"
    else
        read -rp "  Enter the full path to the Doc-Conversion-2026 folder: " REPO_DIR
        if [[ ! -f "$REPO_DIR/docker-compose.yml" ]]; then
            echo -e "${RED}  [ERROR] docker-compose.yml not found at: $REPO_DIR${NC}"
            exit 1
        fi
    fi
fi

# Verify .env exists
if [[ ! -f "$REPO_DIR/.env" ]]; then
    echo -e "${RED}  [ERROR] .env not found at: $REPO_DIR/.env${NC}"
    echo -e "${YELLOW}  Run reset-markflow.sh first to configure your environment.${NC}"
    exit 1
fi

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Quick Refresh${NC}"
echo -e "${CYAN}  Machine: macOS (personal)${NC}"
echo -e "${GRAY}  Repo: $REPO_DIR${NC}"
echo -e "${CYAN}==========================================${NC}"

# ==============================================================
#  GPU Detection
# ==============================================================
echo ""
echo -e "${YELLOW}[GPU] Detecting host GPU hardware...${NC}"

GPU_VENDOR="none"
GPU_NAME=""
GPU_VRAM_MB=0
HASHCAT_PATH=""
HASHCAT_VERSION=""
HASHCAT_BACKEND=""

MACHINE="$(uname -m)"

# -- Apple Silicon --
if [[ "$MACHINE" == "arm64" ]]; then
    CHIP_NAME=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)
    if [[ "$CHIP_NAME" == Apple* ]]; then
        GPU_VENDOR="apple"
        GPU_CORES=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -i "total number of cores" | head -1 | awk -F: '{print $2}' | tr -d ' ' || true)
        if [[ -n "$GPU_CORES" ]]; then
            GPU_NAME="$CHIP_NAME (${GPU_CORES}-core GPU)"
        else
            GPU_NAME="$CHIP_NAME"
        fi
        TOTAL_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        GPU_VRAM_MB=$(( TOTAL_RAM_BYTES / 1048576 * 75 / 100 ))
        echo -e "${GREEN}  [OK] Apple Silicon: $GPU_NAME ($GPU_VRAM_MB MB estimated GPU memory)${NC}"
    fi
fi

# -- Intel Mac with discrete GPU --
if [[ "$GPU_VENDOR" == "none" && "$MACHINE" == "x86_64" ]]; then
    DISCRETE=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -i "chipset model" | head -1 | awk -F: '{print $2}' | xargs || true)
    if [[ -n "$DISCRETE" ]]; then
        DISCRETE_LOWER=$(echo "$DISCRETE" | tr '[:upper:]' '[:lower:]')
        if [[ "$DISCRETE_LOWER" == *"amd"* || "$DISCRETE_LOWER" == *"radeon"* ]]; then
            GPU_VENDOR="amd"
            GPU_NAME="$DISCRETE"
            echo -e "${GREEN}  [OK] AMD GPU: $GPU_NAME${NC}"
        elif [[ "$DISCRETE_LOWER" == *"nvidia"* ]]; then
            GPU_VENDOR="nvidia"
            GPU_NAME="$DISCRETE"
            echo -e "${GREEN}  [OK] NVIDIA GPU: $GPU_NAME${NC}"
        elif [[ "$DISCRETE_LOWER" == *"intel"* ]]; then
            GPU_VENDOR="intel"
            GPU_NAME="$DISCRETE"
            echo -e "${GREEN}  [OK] Intel GPU: $GPU_NAME${NC}"
        fi
    fi
fi

if [[ "$GPU_VENDOR" == "none" ]]; then
    echo -e "${GRAY}  [--] No supported GPU detected${NC}"
fi

# -- hashcat (auto-install via Homebrew if missing) --
if ! command -v hashcat &>/dev/null; then
    echo -e "${YELLOW}  [--] hashcat not found -- attempting auto-install...${NC}"
    if command -v brew &>/dev/null; then
        brew install hashcat 2>/dev/null && echo -e "${GREEN}  [OK] hashcat installed via Homebrew${NC}" || \
            echo -e "${YELLOW}  [WARN] brew install hashcat failed -- install manually: brew install hashcat${NC}"
    else
        echo -e "${YELLOW}  [WARN] Homebrew not found -- install hashcat manually:${NC}"
        echo "         brew install hashcat"
    fi
fi

if command -v hashcat &>/dev/null; then
    HASHCAT_PATH=$(command -v hashcat)
    HASHCAT_VERSION=$(hashcat --version 2>/dev/null | tr -d '\n' || echo "unknown")
    echo -e "${GREEN}  [OK] hashcat: $HASHCAT_VERSION${NC}"

    # Probe backend
    HASHCAT_DIR=$(dirname "$HASHCAT_PATH")
    BACKEND_OUT=$(cd "$HASHCAT_DIR" && hashcat -I 2>&1 | tr '[:upper:]' '[:lower:]' || true)
    if echo "$BACKEND_OUT" | grep -q "metal"; then
        HASHCAT_BACKEND="Metal"
    elif echo "$BACKEND_OUT" | grep -q "opencl.*gpu"; then
        HASHCAT_BACKEND="OpenCL"
    elif echo "$BACKEND_OUT" | grep -q "opencl"; then
        HASHCAT_BACKEND="OpenCL-CPU"
    fi
    if [[ -n "$HASHCAT_BACKEND" ]]; then
        echo -e "${GREEN}  [OK] hashcat backend: $HASHCAT_BACKEND${NC}"
    fi

    # Warn about Rosetta on Apple Silicon
    if [[ "$MACHINE" == "arm64" && -n "$HASHCAT_PATH" ]]; then
        FILE_INFO=$(file "$HASHCAT_PATH" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)
        if [[ "$FILE_INFO" != *"arm64"* ]]; then
            echo -e "${YELLOW}  [WARN] hashcat binary appears to be x86 (Rosetta 2)${NC}"
            echo -e "${YELLOW}         Metal GPU acceleration will NOT work under Rosetta${NC}"
            echo "         Fix: brew install hashcat  (installs native ARM64 build)"
        fi
    fi
else
    echo -e "${GRAY}  [--] hashcat unavailable (GPU cracking disabled)${NC}"
fi

# -- Write worker_capabilities.json --
QUEUE_DIR="$REPO_DIR/hashcat-queue"
mkdir -p "$QUEUE_DIR"

cat > "$QUEUE_DIR/worker_capabilities.json" << EOF
{
  "available": $([ "$GPU_VENDOR" != "none" ] && echo "true" || echo "false"),
  "gpu_vendor": "$GPU_VENDOR",
  "gpu_name": "$GPU_NAME",
  "gpu_vram_mb": $GPU_VRAM_MB,
  "hashcat_backend": $([ -n "$HASHCAT_BACKEND" ] && echo "\"$HASHCAT_BACKEND\"" || echo "null"),
  "hashcat_version": $([ -n "$HASHCAT_VERSION" ] && echo "\"$HASHCAT_VERSION\"" || echo "null"),
  "host_os": "macOS",
  "host_machine": "$MACHINE",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo -e "${GREEN}  [OK] worker_capabilities.json updated${NC}"

if [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo -e "${MAGENTA}  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)${NC}"
fi

# ==============================================================
#  Compose args (no NVIDIA overlay on macOS)
# ==============================================================
COMPOSE_ARGS=(-f docker-compose.yml)

# ==============================================================
#  1. Pull latest code
# ==============================================================
echo ""
echo -e "${YELLOW}[1/3] Pulling latest code from GitHub...${NC}"

cd "$REPO_DIR"
git fetch origin
git reset --hard origin/main

COMMIT_HASH=$(git log -1 --format="%h %s")
echo -e "${GREEN}  [OK] Now at: $COMMIT_HASH${NC}"

# ==============================================================
#  2. Rebuild images
# ==============================================================
echo ""

if [[ "$NO_BUILD" == "true" ]]; then
    echo -e "${GRAY}[2/3] Skipping rebuild (--no-build flag)${NC}"
else
    echo -e "${YELLOW}[2/3] Rebuilding Docker images...${NC}"

    # Check base image
    BASE_EXISTS=$(docker images markflow-base:latest --format "{{.ID}}" 2>/dev/null || true)
    if [[ -z "$BASE_EXISTS" ]]; then
        echo -e "${YELLOW}  [!] Base image missing -- building it first...${NC}"
        echo -e "${GRAY}  (This takes 5-15 min on SSD)${NC}"
        docker build -f Dockerfile.base -t markflow-base:latest .
    fi

    docker compose "${COMPOSE_ARGS[@]}" build
    echo -e "${GREEN}  [OK] Build complete${NC}"
fi

# ==============================================================
#  3. Restart containers
# ==============================================================
echo ""
echo -e "${YELLOW}[3/3] Restarting containers...${NC}"

docker compose "${COMPOSE_ARGS[@]}" up -d

# Start hashcat host worker if applicable
if [[ -n "$HASHCAT_PATH" && "$GPU_VENDOR" != "none" ]]; then
    WORKER_SCRIPT="$REPO_DIR/tools/markflow-hashcat-worker.py"
    if [[ -f "$WORKER_SCRIPT" ]]; then
        echo ""
        echo -e "${MAGENTA}[GPU] Starting hashcat host worker in background...${NC}"
        nohup python3 "$WORKER_SCRIPT" --queue-dir "$QUEUE_DIR" > "$QUEUE_DIR/worker.log" 2>&1 &
        echo -e "${GREEN}  [OK] Host worker started (PID: $!, log: $QUEUE_DIR/worker.log)${NC}"
    fi
fi

# ==============================================================
#  Done
# ==============================================================
echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}  Refresh Complete!${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

docker compose "${COMPOSE_ARGS[@]}" ps

echo ""
echo "  MarkFlow UI:  http://localhost:8000"
echo "  Meilisearch:  http://localhost:7700"
echo "  MCP Server:   http://localhost:8001"
if [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo -e "${MAGENTA}  GPU Mode:     $GPU_NAME (host worker, $HASHCAT_BACKEND)${NC}"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo -e "${YELLOW}  GPU Mode:     $GPU_NAME (hashcat not installed)${NC}"
else
    echo -e "${GRAY}  GPU Mode:     None detected${NC}"
fi
echo -e "${CYAN}==========================================${NC}"
