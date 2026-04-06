#!/usr/bin/env bash
# --------------------------------------------------------------
# MarkFlow First-Time Setup Script (macOS)
#
# Interactive directory picker, GPU detection, Docker build,
# and service startup.
#
# Usage:
#   ./setup-markflow.sh                    # interactive
#   ./setup-markflow.sh --skip-prune       # keep old Docker artifacts
#   ./setup-markflow.sh --repo /my/path    # custom repo location
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
NC='\033[0m' # No Color

# -- Defaults --
REPO_DIR=""
SKIP_PRUNE=false

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)       REPO_DIR="$2"; shift 2 ;;
        --skip-prune) SKIP_PRUNE=true; shift ;;
        *)            echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
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
        echo ""
        echo -e "${YELLOW}  Could not auto-detect the MarkFlow repo location.${NC}"
        read -rp "  Enter the full path to the Doc-Conversion-2026 folder: " REPO_DIR
        if [[ ! -f "$REPO_DIR/docker-compose.yml" ]]; then
            echo -e "${RED}  [ERROR] docker-compose.yml not found at: $REPO_DIR${NC}"
            exit 1
        fi
    fi
fi

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Setup (macOS)${NC}"
echo -e "${GRAY}  Repo: $REPO_DIR${NC}"
echo -e "${CYAN}==========================================${NC}"

# ==============================================================
#  Prerequisites check
# ==============================================================
echo ""
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v docker &>/dev/null; then
    echo -e "${RED}  [ERROR] Docker not found.${NC}"
    echo -e "  Install Docker Desktop for Mac: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo -e "${RED}  [ERROR] Docker is not running. Start Docker Desktop first.${NC}"
    exit 1
fi
echo -e "${GREEN}  [OK] Docker$(docker --version | sed 's/Docker version /: /')${NC}"

if ! command -v git &>/dev/null; then
    echo -e "${RED}  [ERROR] Git not found. Install via: xcode-select --install${NC}"
    exit 1
fi
echo -e "${GREEN}  [OK] Git $(git --version | sed 's/git version //')${NC}"

if ! command -v docker compose &>/dev/null && ! docker compose version &>/dev/null; then
    echo -e "${RED}  [ERROR] docker compose not available. Update Docker Desktop.${NC}"
    exit 1
fi

# ==============================================================
#  Folder Picker (macOS native via AppleScript)
# ==============================================================
pick_folder() {
    local PROMPT="$1"
    local DEFAULT_DIR="${2:-$HOME}"
    local RESULT

    RESULT=$(osascript -e "
        set defaultPath to POSIX file \"$DEFAULT_DIR\" as alias
        try
            set chosen to choose folder with prompt \"$PROMPT\" default location defaultPath
            return POSIX path of chosen
        on error
            return \"\"
        end try
    " 2>/dev/null)

    # Remove trailing slash
    echo "${RESULT%/}"
}

# ==============================================================
#  1. Pick Source Directory
# ==============================================================
echo ""
echo -e "${YELLOW}[1/6] Select your SOURCE directory${NC}"
echo -e "${GRAY}  This is the folder containing documents you want to convert.${NC}"
echo -e "${GRAY}  (It will be mounted read-only -- MarkFlow never modifies your originals)${NC}"
echo ""
echo -e "${GRAY}  A folder picker dialog will open...${NC}"

SOURCE_DIR=$(pick_folder "Select your SOURCE directory -- the folder of documents to convert" "$HOME/Documents")

if [[ -z "$SOURCE_DIR" ]]; then
    echo -e "${RED}  [ERROR] No source directory selected. Setup cancelled.${NC}"
    exit 1
fi

if [[ -d "$SOURCE_DIR" ]]; then
    FILE_COUNT=$(find "$SOURCE_DIR" -type f 2>/dev/null | head -1001 | wc -l | tr -d ' ')
    if [[ "$FILE_COUNT" -eq 0 ]]; then
        echo -e "${YELLOW}  [WARN] Source directory is empty: $SOURCE_DIR${NC}"
        echo -e "${YELLOW}         Add some documents before running a bulk conversion.${NC}"
    elif [[ "$FILE_COUNT" -ge 1001 ]]; then
        echo -e "${GREEN}  [OK] Source dir: $SOURCE_DIR (1000+ files)${NC}"
    else
        echo -e "${GREEN}  [OK] Source dir: $SOURCE_DIR ($FILE_COUNT files)${NC}"
    fi
else
    echo -e "${YELLOW}  [WARN] Source directory does not exist: $SOURCE_DIR${NC}"
fi

# ==============================================================
#  2. Pick Output Directory
# ==============================================================
echo ""
echo -e "${YELLOW}[2/6] Select your OUTPUT directory${NC}"
echo -e "${GRAY}  This is where MarkFlow writes converted Markdown files during bulk jobs.${NC}"
echo ""
echo -e "${GRAY}  A folder picker dialog will open...${NC}"

OUTPUT_DIR=$(pick_folder "Select your OUTPUT directory -- where converted files will be saved" "$HOME")

if [[ -z "$OUTPUT_DIR" ]]; then
    echo -e "${RED}  [ERROR] No output directory selected. Setup cancelled.${NC}"
    exit 1
fi

if [[ ! -d "$OUTPUT_DIR" ]]; then
    echo -e "${YELLOW}  [--] Output directory does not exist -- creating it...${NC}"
    mkdir -p "$OUTPUT_DIR"
fi
echo -e "${GREEN}  [OK] Output dir: $OUTPUT_DIR${NC}"

# ==============================================================
#  3. Hardware Detection & Tuning
# ==============================================================
echo ""
echo -e "${YELLOW}[3/7] Detecting hardware for optimal configuration...${NC}"

# Auto-detect CPU cores and RAM
DETECTED_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 0)
DETECTED_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
if [[ "$DETECTED_RAM_BYTES" -eq 0 ]]; then
    # Linux fallback
    DETECTED_RAM_BYTES=$(awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo 2>/dev/null || echo 0)
fi
DETECTED_RAM_GB=$(( DETECTED_RAM_BYTES / 1073741824 ))

echo ""
if [[ "$DETECTED_CORES" -gt 0 && "$DETECTED_RAM_GB" -gt 0 ]]; then
    echo -e "${GREEN}  Detected: ${DETECTED_CORES} CPU threads, ${DETECTED_RAM_GB} GB RAM${NC}"
    echo ""
    echo -e "${GRAY}  MarkFlow uses these values to set parallel worker count and${NC}"
    echo -e "${GRAY}  Meilisearch search engine memory. You can override if needed.${NC}"
    echo ""
    read -rp "  CPU threads to use [$DETECTED_CORES]: " USER_CORES
    USER_CORES=${USER_CORES:-$DETECTED_CORES}
    read -rp "  Total RAM in GB [$DETECTED_RAM_GB]: " USER_RAM_GB
    USER_RAM_GB=${USER_RAM_GB:-$DETECTED_RAM_GB}
else
    echo -e "${YELLOW}  Could not auto-detect hardware. Please enter your specs:${NC}"
    echo -e "${GRAY}  (Check System Settings > General > About, or run: sysctl hw.logicalcpu)${NC}"
    echo ""
    read -rp "  CPU threads (logical cores): " USER_CORES
    read -rp "  Total RAM in GB: " USER_RAM_GB
fi

# Calculate optimal worker count: ~67% of threads, min 2, max 12
CALC_WORKERS=$(( USER_CORES * 2 / 3 ))
[[ "$CALC_WORKERS" -lt 2 ]] && CALC_WORKERS=2
[[ "$CALC_WORKERS" -gt 12 ]] && CALC_WORKERS=12

# Calculate Meilisearch memory based on RAM
if [[ "$USER_RAM_GB" -ge 32 ]]; then
    MEILI_MEM="1g"
    MEILI_MEM_BYTES=1073741824
elif [[ "$USER_RAM_GB" -ge 16 ]]; then
    MEILI_MEM="512m"
    MEILI_MEM_BYTES=536870912
elif [[ "$USER_RAM_GB" -ge 8 ]]; then
    MEILI_MEM="256m"
    MEILI_MEM_BYTES=268435456
else
    MEILI_MEM="128m"
    MEILI_MEM_BYTES=134217728
fi

echo ""
echo -e "${GREEN}  [OK] Workers: $CALC_WORKERS (of $USER_CORES threads)${NC}"
echo -e "${GREEN}  [OK] Meilisearch memory: $MEILI_MEM (of ${USER_RAM_GB}GB RAM)${NC}"

# Generate Meilisearch master key
MEILI_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p 2>/dev/null || echo "markflow-$(date +%s)-$(od -An -tx4 -N4 /dev/urandom | tr -d ' ')")
echo -e "${GREEN}  [OK] Meilisearch API key generated${NC}"

# ==============================================================
#  4. GPU Detection (macOS)
# ==============================================================
echo ""
echo -e "${YELLOW}[4/7] Detecting GPU and hashcat...${NC}"

GPU_VENDOR="none"
GPU_NAME=""
GPU_VRAM_MB=0
HASHCAT_PATH=""
HASHCAT_VERSION=""
HASHCAT_BACKEND=""

# macOS GPU detection via system_profiler
if command -v system_profiler &>/dev/null; then
    GPU_INFO=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset Model|VRAM" || true)
    if [[ -n "$GPU_INFO" ]]; then
        GPU_NAME=$(echo "$GPU_INFO" | grep "Chipset Model" | head -1 | sed 's/.*: //')
        VRAM_LINE=$(echo "$GPU_INFO" | grep "VRAM" | head -1 | sed 's/.*: //')

        if echo "$GPU_NAME" | grep -qi "apple"; then
            GPU_VENDOR="apple"
            # Apple Silicon unified memory -- report system memory
            TOTAL_MEM=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
            GPU_VRAM_MB=$((TOTAL_MEM / 1048576))
            echo -e "${GREEN}  [OK] Apple Silicon: $GPU_NAME (unified memory: ${GPU_VRAM_MB} MB)${NC}"
        elif echo "$GPU_NAME" | grep -qi "amd\|radeon"; then
            GPU_VENDOR="amd"
            echo -e "${GREEN}  [OK] AMD GPU: $GPU_NAME${NC}"
        elif echo "$GPU_NAME" | grep -qi "intel"; then
            GPU_VENDOR="intel"
            echo -e "${GREEN}  [OK] Intel GPU: $GPU_NAME${NC}"
        else
            GPU_VENDOR="other"
            echo -e "${GREEN}  [OK] GPU: $GPU_NAME${NC}"
        fi
    fi
fi

if [[ "$GPU_VENDOR" == "none" ]]; then
    echo -e "${GRAY}  [--] No dedicated GPU detected (password cracking will use CPU)${NC}"
fi

# hashcat detection
if command -v hashcat &>/dev/null; then
    HASHCAT_PATH=$(command -v hashcat)
    HASHCAT_VERSION=$(hashcat --version 2>/dev/null || echo "unknown")
    echo -e "${GREEN}  [OK] hashcat: $HASHCAT_VERSION${NC}"

    BACKEND_OUT=$(hashcat -I 2>&1 || true)
    BACKEND_LOWER=$(echo "$BACKEND_OUT" | tr '[:upper:]' '[:lower:]')
    if echo "$BACKEND_LOWER" | grep -q "metal"; then
        HASHCAT_BACKEND="Metal"
    elif echo "$BACKEND_LOWER" | grep -q "opencl.*gpu"; then
        HASHCAT_BACKEND="OpenCL"
    elif echo "$BACKEND_LOWER" | grep -q "opencl"; then
        HASHCAT_BACKEND="OpenCL-CPU"
    fi
    if [[ -n "$HASHCAT_BACKEND" ]]; then
        echo -e "${GREEN}  [OK] hashcat backend: $HASHCAT_BACKEND${NC}"
    fi
else
    echo -e "${GRAY}  [--] hashcat not found (optional -- install via: brew install hashcat)${NC}"
fi

# Write worker_capabilities.json
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
  "host_machine": "$(uname -m)",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo -e "${GREEN}  [OK] worker_capabilities.json written${NC}"

# GPU summary
if [[ "$GPU_VENDOR" != "none" && -n "$HASHCAT_PATH" ]]; then
    echo -e "${MAGENTA}  [GPU] Host worker path: $GPU_VENDOR ($HASHCAT_BACKEND)${NC}"
fi

# ==============================================================
#  5. Write .env
# ==============================================================
echo ""
echo -e "${YELLOW}[5/7] Writing .env configuration...${NC}"

ENV_FILE="$REPO_DIR/.env"

cat > "$ENV_FILE" << EOF
# MarkFlow Environment Configuration
# Auto-generated by setup-markflow.sh on $(date '+%Y-%m-%d %H:%M')
# Hardware: ${USER_CORES} threads, ${USER_RAM_GB}GB RAM

# Host paths - mounted into Docker containers
SOURCE_DIR=$SOURCE_DIR
OUTPUT_DIR=$OUTPUT_DIR

# Meilisearch (full-text search engine)
MEILI_MASTER_KEY=$MEILI_KEY
MEILI_MEMORY_LIMIT=$MEILI_MEM
MEILI_MAX_INDEXING_MEMORY=$MEILI_MEM_BYTES

# Bulk conversion (tuned for $USER_CORES threads)
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
#  6. Prepare Docker environment
# ==============================================================
echo ""
echo -e "${YELLOW}[6/7] Preparing Docker environment...${NC}"

cd "$REPO_DIR"

COMPOSE_ARGS=(-f docker-compose.yml)

# macOS: NVIDIA container passthrough is not available
# All GPU work goes through the host worker path

docker compose "${COMPOSE_ARGS[@]}" down -v 2>/dev/null || true

if [[ "$SKIP_PRUNE" != "true" ]]; then
    echo "  Pruning unused Docker artifacts (preserving base image)..."
    docker system prune -f --volumes 2>/dev/null || true
fi

# Build base image if missing
BASE_EXISTS=$(docker images markflow-base:latest --format "{{.ID}}" 2>/dev/null || true)
if [[ -z "$BASE_EXISTS" ]]; then
    echo ""
    echo -e "${YELLOW}  ============================================${NC}"
    echo -e "${YELLOW}  Building markflow-base:latest (first time)${NC}"
    echo -e "${YELLOW}  This is the slow step -- 5-15 min on SSD.${NC}"
    echo -e "${YELLOW}  It only needs to happen ONCE. Go grab a coffee.${NC}"
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
#  7. Build and start
# ==============================================================
echo ""
echo -e "${YELLOW}[7/7] Building and starting MarkFlow...${NC}"

docker compose "${COMPOSE_ARGS[@]}" up -d --build

# Start hashcat host worker if applicable
if [[ -n "$HASHCAT_PATH" && "$GPU_VENDOR" != "none" ]]; then
    WORKER_SCRIPT="$REPO_DIR/tools/markflow-hashcat-worker.py"
    if [[ -f "$WORKER_SCRIPT" ]]; then
        echo ""
        echo -e "${MAGENTA}[GPU] Starting hashcat host worker in background...${NC}"
        nohup python3 "$WORKER_SCRIPT" --queue-dir "$QUEUE_DIR" &>/dev/null &
        echo -e "${GREEN}  [OK] Host worker started (PID: $!)${NC}"
    fi
fi

# ==============================================================
#  Done
# ==============================================================
echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

docker compose "${COMPOSE_ARGS[@]}" ps

echo ""
echo -e "${WHITE}  MarkFlow UI:  http://localhost:8000${NC}"
echo -e "${WHITE}  Meilisearch:  http://localhost:7700${NC}"
echo -e "${WHITE}  MCP Server:   http://localhost:8001${NC}"
echo -e "${WHITE}  API Docs:     http://localhost:8000/docs${NC}"
echo ""
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
echo ""
echo "  Next steps:"
echo "    1. Open http://localhost:8000 in your browser"
echo "    2. Drop a file to test single-file conversion"
echo "    3. Go to /bulk.html to run a bulk scan + conversion"
echo "    4. Use ./refresh-markflow.sh to pull updates later"
echo -e "${CYAN}==========================================${NC}"
