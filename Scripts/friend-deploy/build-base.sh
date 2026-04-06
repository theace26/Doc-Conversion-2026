#!/usr/bin/env bash
# --------------------------------------------------------------
# Build the MarkFlow base Docker image (macOS)
#
# Builds the heavy base layer containing all apt packages
# (LibreOffice, Tesseract, ffmpeg, etc.). Run this once.
#
# Usage:
#   ./build-base.sh              # build the base image
#   ./build-base.sh --no-cache   # force full rebuild
#   ./build-base.sh --repo /path # custom repo location
# --------------------------------------------------------------

set -euo pipefail

# -- Colors --
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

# -- Defaults --
REPO_DIR=""
NO_CACHE=""

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)     REPO_DIR="$2"; shift 2 ;;
        --no-cache) NO_CACHE="--no-cache"; shift ;;
        *)          echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# -- Locate repo --
if [[ -z "$REPO_DIR" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CANDIDATE="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd)"
    if [[ -f "$CANDIDATE/Dockerfile.base" ]]; then
        REPO_DIR="$CANDIDATE"
    else
        read -rp "  Enter the full path to the Doc-Conversion-2026 folder: " REPO_DIR
        if [[ ! -f "$REPO_DIR/Dockerfile.base" ]]; then
            echo -e "${RED}  [ERROR] Dockerfile.base not found at: $REPO_DIR${NC}"
            exit 1
        fi
    fi
fi

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Base Image Builder (macOS)${NC}"
echo -e "${GRAY}  Repo: $REPO_DIR${NC}"
echo -e "${CYAN}==========================================${NC}"

# Check existing
EXISTING=$(docker images markflow-base:latest --format "{{.ID}} ({{.CreatedSince}}, {{.Size}})" 2>/dev/null || true)
if [[ -n "$EXISTING" ]]; then
    echo ""
    echo -e "${GRAY}  Existing base image: $EXISTING${NC}"
    echo -e "${GRAY}  This will be replaced.${NC}"
fi

echo ""
echo -e "${YELLOW}Building markflow-base:latest ...${NC}"
echo -e "${GRAY}  (5-15 min on SSD -- only needs to happen once)${NC}"
echo ""

START_TIME=$(date +%s)

cd "$REPO_DIR"
docker build -f Dockerfile.base -t markflow-base:latest $NO_CACHE .
EXIT_CODE=$?

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))
ELAPSED_MIN=$(( ELAPSED / 60 ))
ELAPSED_SEC=$(( ELAPSED % 60 ))

if [[ $EXIT_CODE -eq 0 ]]; then
    SIZE=$(docker images markflow-base:latest --format "{{.Size}}")
    echo ""
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${GREEN}  Base image built successfully! (${ELAPSED_MIN}m ${ELAPSED_SEC}s)${NC}"
    echo -e "${CYAN}==========================================${NC}"
    echo ""
    echo "  Image: markflow-base:latest ($SIZE)"
    echo ""
    echo "  Next steps:"
    echo "    ./setup-markflow.sh      # first-time setup"
    echo "    ./refresh-markflow.sh    # quick rebuild (code + pip only)"
    echo -e "${CYAN}==========================================${NC}"
else
    echo ""
    echo -e "${RED}  Build FAILED (exit code $EXIT_CODE, ${ELAPSED_MIN}m ${ELAPSED_SEC}s elapsed)${NC}"
    echo -e "${RED}  Check the output above for errors.${NC}"
    exit $EXIT_CODE
fi
