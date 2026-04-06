#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MarkFlow Log Extraction Script
#  Copies logs from the Docker container to the VM home dir
#  with timestamps, then prints scp commands for downloading.
#
#  Usage:  ~/pull-logs.sh
#          ~/pull-logs.sh --tail 5000    (last N lines only)
# ============================================================

CONTAINER="doc-conversion-2026-markflow-1"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
MAIN_LOG="markflow-${TIMESTAMP}.log"
DEBUG_LOG="markflow-debug-${TIMESTAMP}.log"
VM_IP="192.168.1.208"
VM_USER="xerxes"
TAIL_LINES=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tail|-t)
            TAIL_LINES="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--tail N]"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "  MarkFlow Log Extraction"
echo "  Timestamp: ${TIMESTAMP}"
echo "=========================================="

# ----------------------------------------------------------
#  1. Verify container is running
# ----------------------------------------------------------
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo ""
    echo "  [!!]  Container '${CONTAINER}' is not running."
    echo "  Available containers:"
    docker ps -a --format "  {{.Names}}  ({{.Status}})"
    exit 1
fi

# ----------------------------------------------------------
#  2. Copy logs from container
# ----------------------------------------------------------
echo ""
echo "[1/3] Copying logs from container..."

docker cp "${CONTAINER}:/app/logs/markflow.log" ~/"${MAIN_LOG}" 2>/dev/null && \
    echo "  [OK] Main log copied" || \
    echo "  [!!]  Main log not found in container"

docker cp "${CONTAINER}:/app/logs/markflow-debug.log" ~/"${DEBUG_LOG}" 2>/dev/null && \
    echo "  [OK] Debug log copied" || \
    echo "  [!!]  Debug log not found in container"

# ----------------------------------------------------------
#  3. Tail if requested (for large logs)
# ----------------------------------------------------------
if [ -n "${TAIL_LINES}" ]; then
    echo ""
    echo "[2/3] Trimming to last ${TAIL_LINES} lines..."

    if [ -f ~/"${MAIN_LOG}" ]; then
        FULL_MAIN="${MAIN_LOG}"
        MAIN_LOG="markflow-tail-${TIMESTAMP}.log"
        tail -n "${TAIL_LINES}" ~/"${FULL_MAIN}" > ~/"${MAIN_LOG}"
        rm ~/"${FULL_MAIN}"
        echo "  [OK] Main log trimmed -> ${MAIN_LOG}"
    fi

    if [ -f ~/"${DEBUG_LOG}" ]; then
        FULL_DEBUG="${DEBUG_LOG}"
        DEBUG_LOG="markflow-debug-tail-${TIMESTAMP}.log"
        tail -n "${TAIL_LINES}" ~/"${FULL_DEBUG}" > ~/"${DEBUG_LOG}"
        rm ~/"${FULL_DEBUG}"
        echo "  [OK] Debug log trimmed -> ${DEBUG_LOG}"
    fi
else
    echo ""
    echo "[2/3] No --tail flag, keeping full logs"
fi

# ----------------------------------------------------------
#  4. Report sizes and print scp commands
# ----------------------------------------------------------
echo ""
echo "[3/3] Log files ready:"
echo ""

if [ -f ~/"${MAIN_LOG}" ]; then
    MAIN_SIZE=$(ls -lh ~/"${MAIN_LOG}" | awk '{print $5}')
    echo "  [>] ~/${MAIN_LOG}  (${MAIN_SIZE})"
else
    echo "  [X] Main log -- not available"
fi

if [ -f ~/"${DEBUG_LOG}" ]; then
    DEBUG_SIZE=$(ls -lh ~/"${DEBUG_LOG}" | awk '{print $5}')
    echo "  [>] ~/${DEBUG_LOG}  (${DEBUG_SIZE})"
else
    echo "  [X] Debug log -- not available"
fi

echo ""
echo "=========================================="
echo "  Download commands (run on your Mac):"
echo "=========================================="
echo ""

if [ -f ~/"${MAIN_LOG}" ]; then
    echo "  scp ${VM_USER}@${VM_IP}:~/${MAIN_LOG} ~/Downloads/"
fi

if [ -f ~/"${DEBUG_LOG}" ]; then
    echo "  scp ${VM_USER}@${VM_IP}:~/${DEBUG_LOG} ~/Downloads/"
fi

echo ""
echo "  After downloading, clean up on VM with:"
echo "  rm ~/${MAIN_LOG} ~/${DEBUG_LOG}"
echo "=========================================="
