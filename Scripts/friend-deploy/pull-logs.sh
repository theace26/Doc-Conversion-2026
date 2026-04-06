#!/usr/bin/env bash
# --------------------------------------------------------------
# MarkFlow Log Extractor (macOS / Linux)
#
# Pulls log files from Docker containers, runs initial triage.
#
# Usage:
#   ./pull-logs.sh                          # defaults (2000 lines, auto-detect)
#   ./pull-logs.sh --tail 5000              # more docker log lines
#   ./pull-logs.sh --output ~/my-logs       # custom output location
#   ./pull-logs.sh --analyze                # extended analysis
#   ./pull-logs.sh --no-archive             # skip archived logs
#   ./pull-logs.sh --debug-only             # only pull debug log
#   ./pull-logs.sh --repo ~/Projects/Doc-Conversion-2026
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
TAIL_LINES=2000
OUTPUT_DIR=""
REPO_DIR=""
SKIP_ARCHIVE=false
DEBUG_ONLY=false
ANALYZE=false

# -- Parse arguments --
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tail)        TAIL_LINES="$2"; shift 2 ;;
        --output)      OUTPUT_DIR="$2"; shift 2 ;;
        --repo)        REPO_DIR="$2"; shift 2 ;;
        --no-archive)  SKIP_ARCHIVE=true; shift ;;
        --debug-only)  DEBUG_ONLY=true; shift ;;
        --analyze)     ANALYZE=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--tail N] [--output DIR] [--repo DIR] [--no-archive] [--debug-only] [--analyze]"
            exit 0
            ;;
        *)  echo -e "${RED}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

# -- Locate repo --
if [[ -z "$REPO_DIR" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # Try: script is in Scripts/friend-deploy/
    CANDIDATE="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd)"
    if [[ -f "$CANDIDATE/docker-compose.yml" ]]; then
        REPO_DIR="$CANDIDATE"
    # Try: current directory
    elif [[ -f "./docker-compose.yml" ]]; then
        REPO_DIR="$(pwd)"
    else
        echo -e "${RED}  [ERROR] Cannot find docker-compose.yml.${NC}"
        echo "  Run from the repo directory or pass --repo /path/to/Doc-Conversion-2026"
        exit 1
    fi
fi

# -- Timestamp and output dir --
TIMESTAMP=$(date +%Y-%m-%d-%H%M)
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="./markflow-logs-${TIMESTAMP}"
fi
mkdir -p "$OUTPUT_DIR"

# -- Find the container --
cd "$REPO_DIR"

CONTAINER=$(docker compose ps --format '{{.Name}}' 2>/dev/null | grep -E 'markflow-1$|markflow$' | grep -v mcp | head -1 || true)

if [[ -z "$CONTAINER" ]]; then
    echo -e "${RED}  [ERROR] MarkFlow container not found. Is it running?${NC}"
    echo "  Check with: docker compose ps"

    # Still capture docker compose logs even if container is stopped
    echo -e "${YELLOW}  Attempting to capture docker compose logs anyway...${NC}"
    docker compose logs --tail "$TAIL_LINES" --timestamps 2>&1 > "$OUTPUT_DIR/docker-stdout.log" || true
    echo -e "${GREEN}  [OK] docker-stdout.log saved${NC}"
    echo "  Files saved to: $OUTPUT_DIR"
    exit 1
fi

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MarkFlow Log Extraction${NC}"
echo -e "${GRAY}  Container: $CONTAINER${NC}"
echo -e "${GRAY}  Output:    $OUTPUT_DIR/${NC}"
echo -e "${CYAN}==========================================${NC}"

# ==============================================================
#  1. Copy app logs from container
# ==============================================================
echo ""
echo -e "${YELLOW}[1/4] Copying app logs...${NC}"

copy_log() {
    local SRC="$1"
    local FILENAME="$2"
    if docker exec "$CONTAINER" test -f "$SRC" 2>/dev/null; then
        docker cp "$CONTAINER:$SRC" "$OUTPUT_DIR/$FILENAME"
        SIZE=$(du -h "$OUTPUT_DIR/$FILENAME" | cut -f1 | tr -d ' ')
        echo -e "${GREEN}  [OK] $FILENAME ($SIZE)${NC}"
    else
        echo -e "${GRAY}  [--] $FILENAME not found (skipped)${NC}"
    fi
}

if [[ "$DEBUG_ONLY" == "true" ]]; then
    copy_log "/app/logs/markflow-debug.log" "markflow-debug.log"
else
    copy_log "/app/logs/markflow.log" "markflow.log"
    copy_log "/app/logs/markflow-debug.log" "markflow-debug.log"

    # Rotated logs
    for i in 1 2 3 4 5; do
        copy_log "/app/logs/markflow.log.$i" "markflow.log.$i"
    done
fi

# Archive directory
if [[ "$SKIP_ARCHIVE" != "true" ]]; then
    if docker exec "$CONTAINER" test -d "/app/logs/archive" 2>/dev/null; then
        ARCHIVE_COUNT=$(docker exec "$CONTAINER" ls /app/logs/archive/ 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$ARCHIVE_COUNT" -gt 0 ]]; then
            mkdir -p "$OUTPUT_DIR/archive"
            docker cp "$CONTAINER:/app/logs/archive/." "$OUTPUT_DIR/archive/"
            ARCHIVE_SIZE=$(du -sh "$OUTPUT_DIR/archive" | cut -f1 | tr -d ' ')
            echo -e "${GREEN}  [OK] archive/ ($ARCHIVE_COUNT files, $ARCHIVE_SIZE)${NC}"
        else
            echo -e "${GRAY}  [--] Archive directory is empty${NC}"
        fi
    else
        echo -e "${GRAY}  [--] No archive directory found${NC}"
    fi
fi

# ==============================================================
#  2. Capture docker compose logs
# ==============================================================
echo ""
echo -e "${YELLOW}[2/4] Capturing Docker stdout...${NC}"

docker compose logs --tail "$TAIL_LINES" --timestamps markflow > "$OUTPUT_DIR/docker-stdout.log" 2>&1 || true
echo -e "${GREEN}  [OK] docker-stdout.log ($TAIL_LINES lines)${NC}"

docker compose logs --tail 500 --timestamps markflow-mcp > "$OUTPUT_DIR/docker-mcp.log" 2>&1 || true
echo -e "${GREEN}  [OK] docker-mcp.log (500 lines)${NC}"

docker compose logs --tail 500 --timestamps meilisearch > "$OUTPUT_DIR/docker-meilisearch.log" 2>&1 || true
echo -e "${GREEN}  [OK] docker-meilisearch.log (500 lines)${NC}"

# ==============================================================
#  3. Triage
# ==============================================================
echo ""
echo -e "${YELLOW}[3/4] Running triage...${NC}"

TRIAGE="$OUTPUT_DIR/triage.txt"
LOG="$OUTPUT_DIR/markflow.log"

echo "MarkFlow Log Triage -- $(date)" > "$TRIAGE"
echo "Container: $CONTAINER" >> "$TRIAGE"
echo "Extracted: $TIMESTAMP" >> "$TRIAGE"
echo "==========================================" >> "$TRIAGE"
echo "" >> "$TRIAGE"

if [[ -f "$LOG" ]]; then
    ERROR_COUNT=$(grep -c '"level": "error"' "$LOG" 2>/dev/null || echo 0)
    WARN_COUNT=$(grep -c '"level": "warning"' "$LOG" 2>/dev/null || echo 0)
    LOCK_COUNT=$(grep -c "database is locked" "$LOG" 2>/dev/null || echo 0)

    echo "=== Counts ===" >> "$TRIAGE"
    echo "Errors:        $ERROR_COUNT" >> "$TRIAGE"
    echo "Warnings:      $WARN_COUNT" >> "$TRIAGE"
    echo "DB lock errors: $LOCK_COUNT" >> "$TRIAGE"
    echo "" >> "$TRIAGE"

    echo -e "  Errors:   ${ERROR_COUNT}"
    echo -e "  Warnings: ${WARN_COUNT}"
    echo -e "  DB locks: ${LOCK_COUNT}"

    echo "=== Last 20 Errors ===" >> "$TRIAGE"
    grep '"level": "error"' "$LOG" 2>/dev/null | tail -20 >> "$TRIAGE" || true
    echo "" >> "$TRIAGE"

    echo "=== Last 10 Warnings ===" >> "$TRIAGE"
    grep '"level": "warning"' "$LOG" 2>/dev/null | tail -10 >> "$TRIAGE" || true
    echo "" >> "$TRIAGE"

    # -- Extended analysis --
    if [[ "$ANALYZE" == "true" ]]; then
        echo ""
        echo -e "${YELLOW}  Running extended analysis...${NC}"

        echo "=== Top Error Events ===" >> "$TRIAGE"
        grep '"level": "error"' "$LOG" 2>/dev/null |
            grep -oE '"event": "[^"]*"' |
            sort | uniq -c | sort -rn | head -15 >> "$TRIAGE" || true
        echo "" >> "$TRIAGE"

        echo "=== Errors by Hour ===" >> "$TRIAGE"
        grep '"level": "error"' "$LOG" 2>/dev/null |
            grep -oE '"timestamp": "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}' |
            sed 's/"timestamp": "//' |
            sort | uniq -c | sort -k2 >> "$TRIAGE" || true
        echo "" >> "$TRIAGE"

        echo "=== Conversion Failures ===" >> "$TRIAGE"
        CONV_FAILS=$(grep '"level": "error"' "$LOG" 2>/dev/null |
            grep -c '"event": "conversion_failed\|ingest_error\|handler_error"' || echo 0)
        echo "Conversion-related errors: $CONV_FAILS" >> "$TRIAGE"
        echo "" >> "$TRIAGE"

        echo "=== Log Directory Size ===" >> "$TRIAGE"
        docker exec "$CONTAINER" du -sh /app/logs/ 2>/dev/null >> "$TRIAGE" || echo "  (container not accessible)" >> "$TRIAGE"
        docker exec "$CONTAINER" du -sh /app/logs/archive/ 2>/dev/null >> "$TRIAGE" || true
        echo "" >> "$TRIAGE"

        MCP_LOG="$OUTPUT_DIR/docker-mcp.log"
        if [[ -f "$MCP_LOG" ]]; then
            MCP_STARTS=$(grep -c "Application startup complete\|Uvicorn running" "$MCP_LOG" 2>/dev/null || echo 0)
            echo "=== MCP Health ===" >> "$TRIAGE"
            echo "MCP startup events: $MCP_STARTS (>3 may indicate crash-loop)" >> "$TRIAGE"
            echo "" >> "$TRIAGE"
        fi

        echo -e "${GREEN}  [OK] Extended analysis complete${NC}"
    fi
else
    echo "  [--] No markflow.log found -- skipping triage" >> "$TRIAGE"
    echo -e "${GRAY}  [--] No markflow.log found (debug-only mode or container issue)${NC}"
fi

# ==============================================================
#  4. Summary
# ==============================================================
echo ""
echo -e "${YELLOW}[4/4] Done!${NC}"
echo ""

TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" | cut -f1 | tr -d ' ')

echo -e "${CYAN}==========================================${NC}"
echo ""
echo -e "  Files saved to: ${GREEN}$OUTPUT_DIR/${NC}"
echo -e "  Total size:     $TOTAL_SIZE"
echo -e "  Triage:         $OUTPUT_DIR/triage.txt"
echo ""
echo "  Tip: Upload markflow.log to Claude.ai for full analysis."
echo "       For large files, filter first:"
echo "         grep '\"level\": \"error\"' markflow.log > errors-only.log"
echo ""
echo -e "${CYAN}==========================================${NC}"
