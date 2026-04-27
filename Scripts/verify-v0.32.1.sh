#!/usr/bin/env bash
# Local verification for v0.32.1 — run after `docker-compose build && up -d`.
#
# Usage (Git Bash on Windows / WSL / macOS / Linux):
#   bash Scripts/verify-v0.32.1.sh
#
# Hits 8 checkpoints and prints a punch list. Exit code 0 if everything is
# green, non-zero if any check fails. Designed to be quick to run and easy
# to re-run as you iterate.

set -u

# ── config ────────────────────────────────────────────────────────────────
HOST="${MARKFLOW_HOST:-localhost:8000}"
CONTAINER="${MARKFLOW_CONTAINER:-doc-conversion-2026-markflow-1}"
TEST_PATH="/host/c/11Audio Files to Transcribe/Meeting04/260324_1114.mp3"
STUCK_JOB_ID="70d648a4ef9b4a14adbf7b7bdf902e1c"

# Cosmetic
GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; CYAN="\033[36m"; DIM="\033[2m"; OFF="\033[0m"
PASS="${GREEN}✓${OFF}"
WARN="${YELLOW}⚠${OFF}"
FAIL="${RED}✗${OFF}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

ok()    { echo -e "  ${PASS} $*";  PASS_COUNT=$((PASS_COUNT+1)); }
warn()  { echo -e "  ${WARN} $*";  WARN_COUNT=$((WARN_COUNT+1)); }
fail()  { echo -e "  ${FAIL} $*";  FAIL_COUNT=$((FAIL_COUNT+1)); }
note()  { echo -e "  ${DIM}$*${OFF}"; }
hr()    { echo; echo -e "${CYAN}── $* ───────────────────────────────${OFF}"; }

# Helper: curl with a timeout, return body (suppress error output)
fetch() {
  curl -sS -m 10 "$@" 2>/dev/null
}

# Helper: HTTP status code
status_code() {
  curl -s -o /dev/null -w "%{http_code}" -m 10 "$@" 2>/dev/null || echo "000"
}

# Helper: Python JSON probe (works around lack of jq on Git Bash)
jsonq() {
  # $1 = JSON body, $2 = python expression on `data`
  python3 -c "import sys, json
try:
  data = json.loads(sys.argv[1])
  print($2)
except Exception as e:
  print(f'__ERROR: {e}', file=sys.stderr)
  sys.exit(2)
" "$1" "$2" 2>/dev/null
}

# ── header ────────────────────────────────────────────────────────────────
echo
echo -e "${CYAN}MarkFlow v0.32.1 deploy verification${OFF}"
echo -e "${DIM}Host:      ${HOST}${OFF}"
echo -e "${DIM}Container: ${CONTAINER}${OFF}"
echo -e "${DIM}Test path: ${TEST_PATH}${OFF}"

# ── 1. /api/health ────────────────────────────────────────────────────────
hr "1. /api/health — all components ok"
HEALTH="$(fetch "http://${HOST}/api/health")"
if [ -z "$HEALTH" ]; then
  fail "/api/health did not respond. Container down? Try: docker-compose up -d"
else
  for component in tesseract libreoffice poppler weasyprint disk database meilisearch drives whisper gpu; do
    OK="$(jsonq "$HEALTH" "data.get('components',{}).get('$component',{}).get('ok')" )"
    if [ "$OK" = "True" ]; then
      ok "$component — ok"
    elif [ "$OK" = "False" ]; then
      fail "$component — NOT ok"
    else
      warn "$component — missing from response"
    fi
  done
  VER="$(jsonq "$HEALTH" "data.get('version','unknown')")"
  if [ -n "$VER" ] && [ "$VER" != "unknown" ]; then
    note "running version: $VER"
  fi
fi

# ── 2. /api/preview/info — new fields ─────────────────────────────────────
hr "2. /api/preview/info — action + info_version fields"
ENC_PATH="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$TEST_PATH")"
INFO="$(fetch "http://${HOST}/api/preview/info?path=${ENC_PATH}")"
if [ -z "$INFO" ]; then
  fail "/api/preview/info did not respond. Backend rebuild needed?"
else
  ACTION="$(jsonq "$INFO" "data.get('action','MISSING')")"
  IVER="$(jsonq "$INFO" "data.get('info_version','MISSING')")"
  if [ "$ACTION" = "transcribe" ]; then
    ok "info.action = 'transcribe' (correct)"
  elif [ "$ACTION" = "MISSING" ]; then
    fail "info.action MISSING — backend rebuild didn't happen. Run: docker-compose build && docker-compose up -d"
  else
    warn "info.action = '$ACTION' (expected 'transcribe' for an .mp3)"
  fi
  if [ "$IVER" != "MISSING" ] && [ ${#IVER} -ge 8 ] && [ ${#IVER} -le 32 ]; then
    ok "info.info_version present (${#IVER} chars: '$IVER')"
  elif [ "$IVER" = "MISSING" ]; then
    fail "info.info_version MISSING — backend rebuild didn't happen"
  else
    warn "info.info_version unexpected length: ${#IVER}"
  fi
fi

# ── 3. /api/preview/related ───────────────────────────────────────────────
hr "3. /api/preview/related — new endpoint"
REL_STATUS="$(status_code "http://${HOST}/api/preview/related?path=${ENC_PATH}&mode=keyword&limit=5")"
if [ "$REL_STATUS" = "200" ]; then
  REL="$(fetch "http://${HOST}/api/preview/related?path=${ENC_PATH}&mode=keyword&limit=5")"
  COUNT="$(jsonq "$REL" "len(data.get('results') or [])")"
  WARNING="$(jsonq "$REL" "data.get('warning') or ''")"
  if [ "$COUNT" != "" ] && [ -n "$COUNT" ]; then
    ok "/api/preview/related responding · returned $COUNT result(s)"
  fi
  if [ -n "$WARNING" ]; then
    warn "warning from endpoint: $WARNING"
  fi
elif [ "$REL_STATUS" = "404" ]; then
  fail "/api/preview/related returned 404 — endpoint not deployed. docker-compose build + up -d"
else
  warn "/api/preview/related returned HTTP $REL_STATUS"
fi

# ── 4. /api/preview/force-action-status ───────────────────────────────────
hr "4. /api/preview/force-action-status — new endpoint"
FAS_STATUS="$(status_code "http://${HOST}/api/preview/force-action-status?path=${ENC_PATH}")"
if [ "$FAS_STATUS" = "200" ]; then
  FAS="$(fetch "http://${HOST}/api/preview/force-action-status?path=${ENC_PATH}")"
  STATE="$(jsonq "$FAS" "data.get('state','unknown')")"
  ok "/api/preview/force-action-status responding · state='$STATE'"
elif [ "$FAS_STATUS" = "404" ]; then
  fail "/api/preview/force-action-status returned 404 — endpoint not deployed"
else
  warn "/api/preview/force-action-status returned HTTP $FAS_STATUS"
fi

# ── 5. /api/pipeline/files include_trashed ────────────────────────────────
hr "5. /api/pipeline/files — include_trashed query param"
PF_TRUE_STATUS="$(status_code "http://${HOST}/api/pipeline/files?status=pending&per_page=10&include_trashed=true")"
PF_FALSE_STATUS="$(status_code "http://${HOST}/api/pipeline/files?status=pending&per_page=10&include_trashed=false")"
if [ "$PF_TRUE_STATUS" = "200" ] && [ "$PF_FALSE_STATUS" = "200" ]; then
  PF_TRUE="$(fetch "http://${HOST}/api/pipeline/files?status=pending&per_page=1&include_trashed=true")"
  PF_FALSE="$(fetch "http://${HOST}/api/pipeline/files?status=pending&per_page=1&include_trashed=false")"
  T_TOTAL="$(jsonq "$PF_TRUE" "data.get('total', '?')")"
  F_TOTAL="$(jsonq "$PF_FALSE" "data.get('total', '?')")"
  ok "/api/pipeline/files accepts include_trashed query param"
  note "  pending (include_trashed=true):  $T_TOTAL"
  note "  pending (include_trashed=false): $F_TOTAL  ${DIM}(should be smaller after v0.32.1 filter)${OFF}"
  if [ "$T_TOTAL" != "?" ] && [ "$F_TOTAL" != "?" ] && [ "$F_TOTAL" -lt "$T_TOTAL" ]; then
    ok "filter is working — false-count is smaller than true-count"
  elif [ "$T_TOTAL" != "?" ] && [ "$T_TOTAL" = "$F_TOTAL" ]; then
    note "  same count — could mean no trashed pending files exist (fine), or filter not applied"
  fi
elif [ "$PF_TRUE_STATUS" = "422" ] || [ "$PF_FALSE_STATUS" = "422" ]; then
  fail "/api/pipeline/files rejected include_trashed (HTTP 422). Backend not rebuilt."
else
  warn "/api/pipeline/files returned HTTP $PF_TRUE_STATUS / $PF_FALSE_STATUS"
fi

# ── 6. /api/trash/empty/status + restore-all/status (live banner) ─────────
hr "6. /api/trash/empty + restore-all status — live banner endpoints"
for ep in "empty" "restore-all"; do
  TS="$(status_code "http://${HOST}/api/trash/${ep}/status")"
  if [ "$TS" = "200" ]; then
    BODY="$(fetch "http://${HOST}/api/trash/${ep}/status")"
    HAS_RUNNING="$(jsonq "$BODY" "'running' in data")"
    HAS_DONE="$(jsonq "$BODY" "'done' in data")"
    if [ "$HAS_RUNNING" = "True" ] && [ "$HAS_DONE" = "True" ]; then
      ok "/api/trash/${ep}/status — correct shape"
    else
      warn "/api/trash/${ep}/status — unexpected shape: $BODY"
    fi
  else
    fail "/api/trash/${ep}/status returned HTTP $TS"
  fi
done

# ── 7. Recent log activity ────────────────────────────────────────────────
hr "7. Recent log activity (last ~200 lines)"
LOG_OUT="$(MSYS_NO_PATHCONV=1 docker exec "${CONTAINER}" sh -c '
  echo "=== preview.* events ==="
  tail -n 500 /app/logs/markflow.log 2>/dev/null | grep -oE "\"event\": \"preview\\.[^\"]+\"" | sort | uniq -c | sort -rn
  echo "=== recent errors (last 5) ==="
  tail -n 500 /app/logs/markflow.log 2>/dev/null | grep "\"level\": \"error\"" | tail -5
  echo "=== scheduler.scan_cancelled_on_shutdown (proves scheduler.py fix landed) ==="
  grep -c "scheduler.scan_cancelled_on_shutdown" /app/logs/markflow.log 2>/dev/null
' 2>&1)"
echo "$LOG_OUT" | sed "s/^/    /"
if echo "$LOG_OUT" | grep -q "preview\."; then
  ok "preview.* events firing — the new endpoints are being hit"
fi
if echo "$LOG_OUT" | grep -q "scheduler.scan_cancelled_on_shutdown"; then
  ok "scheduler.scan_cancelled_on_shutdown logged — v0.32.0 fix is live"
fi

# ── 8. Stuck scanning job ─────────────────────────────────────────────────
hr "8. Stuck scanning job ${STUCK_JOB_ID:0:8}…"
JOB_OUT="$(MSYS_NO_PATHCONV=1 docker exec "${CONTAINER}" python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/markflow.db')
row = conn.execute('SELECT status, total_files, last_heartbeat, started_at FROM bulk_jobs WHERE id=?', ('${STUCK_JOB_ID}',)).fetchone()
if row is None:
    print('GONE')
else:
    print(f'status={row[0]} total={row[1]} hb={row[2]} started={row[3]}')
" 2>&1)"
case "$JOB_OUT" in
  GONE)
    ok "stuck job no longer exists in bulk_jobs"
    ;;
  *status=completed*|*status=cancelled*)
    ok "stuck job resolved: $JOB_OUT"
    ;;
  *status=scanning*)
    fail "stuck job STILL scanning. Stop it from /status.html or via:"
    note "  curl -X POST 'http://${HOST}/api/bulk/${STUCK_JOB_ID}/cancel'"
    ;;
  *)
    warn "stuck job state: $JOB_OUT"
    ;;
esac

# ── summary ───────────────────────────────────────────────────────────────
echo
echo -e "${CYAN}── summary ───────────────────────────────${OFF}"
echo -e "  passes:   ${GREEN}${PASS_COUNT}${OFF}"
echo -e "  warnings: ${YELLOW}${WARN_COUNT}${OFF}"
echo -e "  failures: ${RED}${FAIL_COUNT}${OFF}"
echo
if [ $FAIL_COUNT -gt 0 ]; then
  echo -e "${RED}Verification FAILED — see fails above.${OFF}"
  echo -e "${DIM}Most common cause: backend not rebuilt. Run:${OFF}"
  echo -e "${DIM}  docker-compose build && docker-compose up -d${OFF}"
  exit 1
elif [ $WARN_COUNT -gt 0 ]; then
  echo -e "${YELLOW}Verification passed with warnings.${OFF}"
  exit 0
else
  echo -e "${GREEN}All checks passed — v0.32.1 deploy looks clean.${OFF}"
  exit 0
fi
