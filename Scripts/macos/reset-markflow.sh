#!/usr/bin/env bash
# --------------------------------------------------------------
# MarkFlow Docker Reset & Rebuild (macOS - personal machine)
#
# Tears down everything, force-pulls latest from GitHub, rebuilds
# from scratch. Database, indexes, and converted output are WIPED.
#
# Hardcoded paths for this machine:
#   Source: ~/Library/CloudStorage/OneDrive-Personal/IBEW 46 Internship/1_K_Drive_Test
#   Output: ~/Documents/test_k_drv_test
#
# Usage:
#   ./reset-markflow.sh                    # full reset
#   ./reset-markflow.sh --skip-prune       # keep old Docker artifacts
#   ./reset-markflow.sh --repo /my/path    # custom repo location
# --------------------------------------------------------------

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m'

# -- Defaults --
REPO_DIR=""
SOURCE_DIR="$HOME/Library/CloudStorage/OneDrive-Personal/IBEW 46 Internship/1_K_Drive_Test"
OUTPUT_DIR="$HOME/Documents/test_k_drv_test"
SKIP_PRUNE=false

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)        REPO_DIR="$2"; shift 2 ;;
        --source)      SOURCE_DIR="$2"; shift 2 ;;
        --output)      OUTPUT_DIR="$2"; shift 2 ;;
        --skip-prune)  SKIP_PRUNE=true; shift ;;
        *)             echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# -- Locate repo --
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

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Docker Reset & Rebuild${NC}"
echo -e "${CYAN}  Machine: macOS (personal)${NC}"
echo -e "${GRAY}  Repo: $REPO_DIR${NC}"
echo -e "${CYAN}==========================================${NC}"

# ==============================================================
#  GPU Auto-Detection
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
echo -e "${GREEN}  [OK] worker_capabilities.json written${NC}"

if [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo -e "${MAGENTA}  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)${NC}"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo -e "${YELLOW}  [GPU] GPU found but hashcat not installed -- install hashcat for GPU cracking${NC}"
fi

# ==============================================================
#  Compose args (no NVIDIA overlay on macOS)
# ==============================================================
COMPOSE_ARGS=(-f docker-compose.yml)

# ==============================================================
#  1. Tear down everything
# ==============================================================
echo ""
echo -e "${YELLOW}[1/5] Tearing down containers, volumes, and images...${NC}"

cd "$REPO_DIR"

docker compose "${COMPOSE_ARGS[@]}" down -v 2>/dev/null || true

if [[ "$SKIP_PRUNE" != "true" ]]; then
    echo "  Pruning unused Docker artifacts (preserving base image)..."
    docker system prune -f --volumes 2>/dev/null || true
    # Remove markflow app images but NOT the base image
    docker images "markflow-*" --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep -v "markflow-base:latest" | while read -r img; do
        docker rmi "$img" 2>/dev/null || true
    done
fi

# Build base image if missing
BASE_EXISTS=$(docker images markflow-base:latest --format "{{.ID}}" 2>/dev/null || true)
if [[ -z "$BASE_EXISTS" ]]; then
    echo ""
    echo -e "${YELLOW}  ============================================${NC}"
    echo -e "${YELLOW}  Building markflow-base:latest (first time)${NC}"
    echo -e "${YELLOW}  This is the slow step -- 5-15 min on SSD.${NC}"
    echo -e "${YELLOW}  ============================================${NC}"
    echo ""

    START_TIME=$(date +%s)
    docker build -f Dockerfile.base -t markflow-base:latest .
    END_TIME=$(date +%s)
    ELAPSED=$(( END_TIME - START_TIME ))
    ELAPSED_MIN=$(( ELAPSED / 60 ))
    ELAPSED_SEC=$(( ELAPSED % 60 ))
    echo -e "${GREEN}  [OK] Base image built in ${ELAPSED_MIN}m ${ELAPSED_SEC}s${NC}"
else
    BASE_INFO=$(docker images markflow-base:latest --format "{{.CreatedSince}} ({{.Size}})" 2>/dev/null)
    echo -e "${GREEN}  [OK] Base image already exists: $BASE_INFO${NC}"
fi

# ==============================================================
#  2. Force-pull latest code from GitHub
# ==============================================================
echo ""
echo -e "${YELLOW}[2/5] Force-pulling latest code from GitHub...${NC}"

git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" reset --hard origin/main

COMMIT_HASH=$(git -C "$REPO_DIR" log -1 --format="%h %s")
echo -e "${GREEN}  [OK] Now at: $COMMIT_HASH${NC}"

# ==============================================================
#  3. Write .env for this machine
# ==============================================================
echo ""
echo -e "${YELLOW}[3/5] Configuring .env for macOS personal machine...${NC}"

# Auto-detect hardware for tuning
DETECTED_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || echo 4)
DETECTED_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
DETECTED_RAM_GB=$(( DETECTED_RAM_BYTES / 1073741824 ))

# Calculate optimal worker count: ~67% of threads, min 2, max 12
CALC_WORKERS=$(( DETECTED_CORES * 2 / 3 ))
[[ "$CALC_WORKERS" -lt 2 ]] && CALC_WORKERS=2
[[ "$CALC_WORKERS" -gt 12 ]] && CALC_WORKERS=12

# Calculate Meilisearch memory based on RAM
if [[ "$DETECTED_RAM_GB" -ge 32 ]]; then
    MEILI_MEM="1g"
    MEILI_MEM_BYTES=1073741824
elif [[ "$DETECTED_RAM_GB" -ge 16 ]]; then
    MEILI_MEM="512m"
    MEILI_MEM_BYTES=536870912
elif [[ "$DETECTED_RAM_GB" -ge 8 ]]; then
    MEILI_MEM="256m"
    MEILI_MEM_BYTES=268435456
else
    MEILI_MEM="128m"
    MEILI_MEM_BYTES=134217728
fi

# Generate Meilisearch master key
MEILI_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p 2>/dev/null || echo "markflow-$(date +%s)")

ENV_FILE="$REPO_DIR/.env"

cat > "$ENV_FILE" << EOF
# MarkFlow Environment Configuration
# macOS personal machine - auto-generated by reset-markflow.sh on $(date '+%Y-%m-%d %H:%M')
# Hardware: ${DETECTED_CORES} threads, ${DETECTED_RAM_GB}GB RAM

# Host paths - mounted into Docker containers
SOURCE_DIR=$SOURCE_DIR
OUTPUT_DIR=$OUTPUT_DIR

# Drive browser mounts (macOS -- no C:/D: drives)
DRIVE_C=$HOME
DRIVE_D=$HOME/Documents

# Meilisearch (full-text search engine)
MEILI_MASTER_KEY=$MEILI_KEY
MEILI_MEMORY_LIMIT=$MEILI_MEM
MEILI_MAX_INDEXING_MEMORY=$MEILI_MEM_BYTES

# Bulk conversion (tuned for $DETECTED_CORES threads)
BULK_WORKER_COUNT=$CALC_WORKERS

# App
SECRET_KEY=dev-secret-change-in-prod
DEFAULT_LOG_LEVEL=normal
DEV_BYPASS_AUTH=true
EOF

echo -e "${GREEN}  [OK] .env written${NC}"
echo "    SOURCE_DIR    = $SOURCE_DIR"
echo "    OUTPUT_DIR    = $OUTPUT_DIR"
echo "    WORKERS       = $CALC_WORKERS"
echo "    MEILI_MEMORY  = $MEILI_MEM"

# ==============================================================
#  4. Verify paths exist
# ==============================================================
echo ""
echo -e "${YELLOW}[4/5] Verifying paths...${NC}"

if [[ -d "$SOURCE_DIR" ]]; then
    FILE_COUNT=$(find "$SOURCE_DIR" -type f 2>/dev/null | head -1001 | wc -l | tr -d ' ')
    if [[ "$FILE_COUNT" -ge 1001 ]]; then
        echo -e "${GREEN}  [OK] Source dir exists (1000+ files)${NC}"
    else
        echo -e "${GREEN}  [OK] Source dir exists ($FILE_COUNT files)${NC}"
    fi
else
    echo -e "${RED}  [!] Source dir not found: $SOURCE_DIR${NC}"
    echo -e "${YELLOW}      Make sure OneDrive is synced and the folder exists.${NC}"
fi

if [[ -d "$OUTPUT_DIR" ]]; then
    echo -e "${GREEN}  [OK] Output dir exists${NC}"
else
    echo -e "${YELLOW}  [--] Output dir not found -- creating it...${NC}"
    mkdir -p "$OUTPUT_DIR"
    echo -e "${GREEN}  [OK] Output dir created: $OUTPUT_DIR${NC}"
fi

# ==============================================================
#  5. Build and start
# ==============================================================
echo ""
echo -e "${YELLOW}[5/5] Building and starting MarkFlow...${NC}"

docker compose "${COMPOSE_ARGS[@]}" up -d --build

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
echo -e "${GREEN}  Reset Complete!${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

docker compose "${COMPOSE_ARGS[@]}" ps

echo ""
echo -e "${WHITE}  MarkFlow UI:  http://localhost:8000${NC}"
echo -e "${WHITE}  Meilisearch:  http://localhost:7700${NC}"
echo -e "${WHITE}  MCP Server:   http://localhost:8001${NC}"
if [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo -e "${MAGENTA}  GPU Mode:     $GPU_NAME (host worker, $HASHCAT_BACKEND)${NC}"
elif [[ "$GPU_VENDOR" != "none" ]]; then
    echo -e "${YELLOW}  GPU Mode:     $GPU_NAME (hashcat not installed)${NC}"
else
    echo -e "${GRAY}  GPU Mode:     None detected${NC}"
fi
echo ""
echo "  Source: $SOURCE_DIR"
echo "  Output: $OUTPUT_DIR"
echo -e "${CYAN}==========================================${NC}"
