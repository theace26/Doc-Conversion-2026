# Claude Code: Pull & Analyze MarkFlow Docker Logs

## Purpose

This document instructs Claude Code to extract log files from the MarkFlow Docker
containers, save them to the host machine, and perform initial triage. Works on
both **Windows** (PowerShell) and **macOS/Linux** (bash).

Claude Code should auto-detect the platform and use the appropriate commands.

---

## Quick Reference

| Log Source | Location Inside Container | Format | Notes |
|------------|--------------------------|--------|-------|
| **App log** | `/app/logs/markflow.log` | structlog JSON | Operational log, always active. 50 MB max, 5 rotated backups. |
| **Debug log** | `/app/logs/markflow-debug.log` | structlog JSON | Verbose trace, only when log_level = developer. 100 MB max, 3 backups. |
| **Rotated logs** | `/app/logs/markflow.log.1` through `.5` | structlog JSON | Previous rotation files, pre-archive. |
| **Archived logs** | `/app/logs/archive/*.gz` | gzip'd JSON | Compressed rotated logs. 90-day retention. |
| **Docker stdout** | `docker compose logs` | Mixed text | Container stdout/stderr including startup messages. |
| **MCP server log** | `docker compose logs markflow-mcp` | Text | MCP container stdout. No internal log files. |
| **Meilisearch log** | `docker compose logs meilisearch` | Text | Search engine stdout. No internal log files. |

The main MarkFlow container name is typically `doc-conversion-2026-markflow-1`.
Verify with `docker compose ps`.

---

## What to Generate

A single script that:

1. Auto-detects the MarkFlow container name
2. Creates a timestamped output directory on the host
3. Copies log files out of the container via `docker cp`
4. Captures `docker compose logs` output with configurable tail length
5. Runs initial triage (error counts, warning counts, last 20 errors)
6. Prints a summary with file sizes and locations

### Output Structure

```
markflow-logs-{YYYY-MM-DD-HHmm}/
  markflow.log                    # Current app log
  markflow-debug.log              # Current debug log (if exists)
  markflow.log.1                  # Most recent rotated log (if exists)
  docker-stdout.log               # docker compose logs output (all services)
  docker-mcp.log                  # MCP container logs
  docker-meilisearch.log          # Meilisearch container logs
  archive/                        # Compressed archive logs (if any)
    markflow-20260329-020000.gz
    ...
  triage.txt                      # Auto-generated triage summary
```

---

## Platform-Specific Commands

### Detect the container name

```bash
# bash (macOS/Linux)
CONTAINER=$(docker compose ps --format '{{.Name}}' | grep -E 'markflow-1$|markflow$' | head -1)

# PowerShell (Windows)
$Container = docker compose ps --format '{{.Name}}' | Where-Object { $_ -match 'markflow-1$|markflow$' } | Select-Object -First 1
```

### Copy files out

```bash
# bash -- copy entire logs directory
docker cp "$CONTAINER:/app/logs/." "$OUTPUT_DIR/"

# PowerShell
docker cp "${Container}:/app/logs/." "$OutputDir/"
```

### Capture docker compose logs

```bash
# bash -- last 2000 lines per service, with timestamps
docker compose logs --tail 2000 --timestamps markflow > "$OUTPUT_DIR/docker-stdout.log" 2>&1
docker compose logs --tail 500 --timestamps markflow-mcp > "$OUTPUT_DIR/docker-mcp.log" 2>&1
docker compose logs --tail 500 --timestamps meilisearch > "$OUTPUT_DIR/docker-meilisearch.log" 2>&1

# PowerShell
docker compose logs --tail 2000 --timestamps markflow 2>&1 | Out-File "$OutputDir\docker-stdout.log" -Encoding utf8
docker compose logs --tail 500 --timestamps markflow-mcp 2>&1 | Out-File "$OutputDir\docker-mcp.log" -Encoding utf8
docker compose logs --tail 500 --timestamps meilisearch 2>&1 | Out-File "$OutputDir\docker-meilisearch.log" -Encoding utf8
```

### Triage: count errors and warnings

The app log is structured JSON. Each line is a JSON object with a `"level"` field.

```bash
# bash
echo "=== Error/Warning Counts ===" > "$OUTPUT_DIR/triage.txt"
echo "Errors:   $(grep -c '"level": "error"'   "$OUTPUT_DIR/markflow.log" 2>/dev/null || echo 0)" >> "$OUTPUT_DIR/triage.txt"
echo "Warnings: $(grep -c '"level": "warning"' "$OUTPUT_DIR/markflow.log" 2>/dev/null || echo 0)" >> "$OUTPUT_DIR/triage.txt"
echo "" >> "$OUTPUT_DIR/triage.txt"

echo "=== Last 20 Errors ===" >> "$OUTPUT_DIR/triage.txt"
grep '"level": "error"' "$OUTPUT_DIR/markflow.log" 2>/dev/null | tail -20 >> "$OUTPUT_DIR/triage.txt"
echo "" >> "$OUTPUT_DIR/triage.txt"

echo "=== Last 10 Warnings ===" >> "$OUTPUT_DIR/triage.txt"
grep '"level": "warning"' "$OUTPUT_DIR/markflow.log" 2>/dev/null | tail -10 >> "$OUTPUT_DIR/triage.txt"
```

```powershell
# PowerShell
$logFile = Join-Path $OutputDir "markflow.log"
$triageFile = Join-Path $OutputDir "triage.txt"

$errorCount = (Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue | Measure-Object).Count
$warnCount  = (Select-String -Path $logFile -Pattern '"level": "warning"' -ErrorAction SilentlyContinue | Measure-Object).Count

@(
    "=== Error/Warning Counts ==="
    "Errors:   $errorCount"
    "Warnings: $warnCount"
    ""
    "=== Last 20 Errors ==="
) | Out-File $triageFile -Encoding utf8

Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue |
    Select-Object -Last 20 | ForEach-Object { $_.Line } |
    Out-File $triageFile -Append -Encoding utf8

"" | Out-File $triageFile -Append -Encoding utf8
"=== Last 10 Warnings ===" | Out-File $triageFile -Append -Encoding utf8

Select-String -Path $logFile -Pattern '"level": "warning"' -ErrorAction SilentlyContinue |
    Select-Object -Last 10 | ForEach-Object { $_.Line } |
    Out-File $triageFile -Append -Encoding utf8
```

---

## Script Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--tail` / `-Tail` | `2000` | Number of lines to capture from `docker compose logs` |
| `--output` / `-OutputDir` | `./markflow-logs-{timestamp}` | Where to save extracted logs |
| `--repo` / `-RepoDir` | Auto-detect (parent of script or cwd) | Path to the repo (for `docker compose` context) |
| `--no-archive` / `-SkipArchive` | `false` | Skip copying the `logs/archive/` directory (can be large) |
| `--debug-only` / `-DebugOnly` | `false` | Only pull the debug log (smaller, faster) |
| `--analyze` / `-Analyze` | `false` | Run extended analysis after extraction (see below) |

---

## Extended Analysis (--analyze flag)

When the analyze flag is set, after extracting logs the script should also:

1. **Error frequency by event type**: Parse the `"event"` field from error-level JSON lines
   and count occurrences of each unique event name. Print the top 15 most frequent.

2. **Error timeline**: Group errors by hour and show a simple histogram (e.g., `14:00  ######## 43`).

3. **Database lock detection**: Count occurrences of `"database is locked"` -- this indicates
   SQLite concurrency issues.

4. **Conversion failure summary**: Count errors where the event matches common conversion
   failure patterns (`conversion_failed`, `ingest_error`, `handler_error`).

5. **MCP health**: Check the MCP docker log for crash-loops (repeated restart messages).

6. **Disk usage inside container**: Run `docker exec` to check `/app/logs/` directory size.

### Analysis commands (bash)

```bash
# Top error events
echo "=== Top Error Events ===" >> "$OUTPUT_DIR/triage.txt"
grep '"level": "error"' "$OUTPUT_DIR/markflow.log" |
    grep -oP '"event": "[^"]*"' |
    sort | uniq -c | sort -rn | head -15 >> "$OUTPUT_DIR/triage.txt"

# Database lock count
LOCKS=$(grep -c "database is locked" "$OUTPUT_DIR/markflow.log" 2>/dev/null || echo 0)
echo "Database lock errors: $LOCKS" >> "$OUTPUT_DIR/triage.txt"

# Error timeline (by hour)
echo "=== Errors by Hour ===" >> "$OUTPUT_DIR/triage.txt"
grep '"level": "error"' "$OUTPUT_DIR/markflow.log" |
    grep -oP '"timestamp": "\d{4}-\d{2}-\d{2}T\d{2}' |
    sed 's/"timestamp": "//' |
    sort | uniq -c | sort -k2 >> "$OUTPUT_DIR/triage.txt"

# Container disk usage
echo "=== Log Directory Size ===" >> "$OUTPUT_DIR/triage.txt"
docker exec "$CONTAINER" du -sh /app/logs/ 2>/dev/null >> "$OUTPUT_DIR/triage.txt"
docker exec "$CONTAINER" du -sh /app/logs/archive/ 2>/dev/null >> "$OUTPUT_DIR/triage.txt"

# MCP crash-loop check
MCP_RESTARTS=$(grep -c "Started reloading\|Application startup complete" "$OUTPUT_DIR/docker-mcp.log" 2>/dev/null || echo 0)
echo "MCP startup events: $MCP_RESTARTS (>3 may indicate crash-loop)" >> "$OUTPUT_DIR/triage.txt"
```

### Analysis commands (PowerShell)

```powershell
# Top error events
"=== Top Error Events ===" | Out-File $triageFile -Append -Encoding utf8
Select-String -Path $logFile -Pattern '"level": "error"' -ErrorAction SilentlyContinue |
    ForEach-Object {
        if ($_.Line -match '"event":\s*"([^"]*)"') { $Matches[1] }
    } | Group-Object | Sort-Object Count -Descending | Select-Object -First 15 |
    ForEach-Object { "  $($_.Count) $($_.Name)" } |
    Out-File $triageFile -Append -Encoding utf8

# Database lock count
$lockCount = (Select-String -Path $logFile -Pattern "database is locked" -ErrorAction SilentlyContinue | Measure-Object).Count
"Database lock errors: $lockCount" | Out-File $triageFile -Append -Encoding utf8

# Container disk usage
"=== Log Directory Size ===" | Out-File $triageFile -Append -Encoding utf8
docker exec $Container du -sh /app/logs/ 2>$null | Out-File $triageFile -Append -Encoding utf8
docker exec $Container du -sh /app/logs/archive/ 2>$null | Out-File $triageFile -Append -Encoding utf8

# MCP crash-loop check
$mcpLog = Join-Path $OutputDir "docker-mcp.log"
$mcpRestarts = (Select-String -Path $mcpLog -Pattern "Started reloading|Application startup complete" -ErrorAction SilentlyContinue | Measure-Object).Count
"MCP startup events: $mcpRestarts (>3 may indicate crash-loop)" | Out-File $triageFile -Append -Encoding utf8
```

---

## Questions to Ask the User

Before generating the script, ask:

1. **Platform?** Windows or macOS/Linux. Determines script language.

2. **Where is the repo?** Needed for `docker compose` context. Default: auto-detect from
   current directory or script location.

3. **Where should logs be saved?** Default: a timestamped folder in the current directory.
   Some users may want a fixed location (e.g., `~/markflow-logs/` or `C:\MarkFlowLogs\`).

4. **Include archived logs?** The `logs/archive/` directory can be large (hundreds of MB
   of gzip files over time). Default: yes. Offer a skip flag.

5. **Run extended analysis?** Default: no (just extraction + basic triage). Yes adds the
   error frequency, timeline, and health checks described above.

---

## Important Gotchas

### Both Platforms
- **Container must be running** for `docker cp` and `docker exec`. If the container is
  stopped, `docker compose logs` still works (reads from Docker's log driver) but
  `docker cp` fails. Check with `docker compose ps` first.
- **Log files are structured JSON** -- one JSON object per line. Do NOT try to parse them
  as plain text with naive string splitting. Use `grep` for field matching.
- **Debug log may not exist** if the user has never set log_level to "developer". Handle
  missing files gracefully (skip with a message, not an error).
- **Archive directory may not exist** on fresh installations. Same -- skip gracefully.
- **Large log files consume context**: If the user plans to upload logs to Claude.ai for
  analysis, warn them that files over 1-2 MB will consume significant context window.
  Recommend filtering to errors/warnings first, or using `--tail` to limit scope.

### Windows-Specific
- **PowerShell encoding**: Use `-Encoding utf8` on `Out-File` to avoid UTF-16 output.
  Do NOT use `Set-Content` for large files (BOM issues on PS 5.x).
- **Path separators**: `docker cp` accepts forward slashes even on Windows. Use them
  for the container-side path (e.g., `container:/app/logs/markflow.log`).
- **Long paths**: If the output directory path exceeds 260 characters, `docker cp` may
  fail on older Windows. Keep output paths short.

### macOS-Specific
- **Docker Desktop file sharing**: The output directory must be in a Docker-accessible
  location. Typically `~/*` works. `/tmp` also works.
- **grep -P (Perl regex)**: macOS's default grep does not support `-P`. Use `grep -oE`
  with extended regex instead, or install GNU grep via `brew install grep` (as `ggrep`).
  The script should use POSIX-compatible patterns or detect and adapt.
- **sed differences**: macOS uses BSD sed. For in-place edits, use `sed -i ''` (empty
  string backup suffix) instead of `sed -i` (GNU). For this script, sed is only used
  for output formatting -- no in-place edits needed.

---

## Example Script Output

```
==========================================
  MarkFlow Log Extraction
  Container: doc-conversion-2026-markflow-1
  Output:    ./markflow-logs-2026-03-31-1445/
==========================================

[1/4] Copying app logs...
  [OK] markflow.log (12.4 MB)
  [OK] markflow-debug.log (47.2 MB)
  [OK] markflow.log.1 (50.0 MB)
  [--] No archive directory found

[2/4] Capturing Docker stdout...
  [OK] docker-stdout.log (2000 lines)
  [OK] docker-mcp.log (500 lines)
  [OK] docker-meilisearch.log (500 lines)

[3/4] Running triage...
  Errors:   23
  Warnings: 147
  DB locks: 5

[4/4] Done!

  Files saved to: ./markflow-logs-2026-03-31-1445/
  Total size:     109.6 MB
  Triage:         ./markflow-logs-2026-03-31-1445/triage.txt

  Tip: Upload markflow.log to Claude.ai for full analysis.
       For large files, filter first:
         grep '"level": "error"' markflow.log > errors-only.log
==========================================
```

---

## Recommended Follow-Up Workflow

After extracting logs, the typical analysis workflow is:

1. **Read triage.txt** for the quick summary (error counts, top events, DB locks).
2. **If errors are low (<50)**: Upload the full `markflow.log` to Claude.ai for analysis.
3. **If errors are high or log is large**: Filter first with grep, then upload:
   ```bash
   grep '"level": "error"' markflow.log > errors-only.log
   grep '"level": "warning"' markflow.log > warnings-only.log
   ```
4. **For conversion failures**: Look for `"event": "conversion_failed"` lines -- they
   include the source file path and the exception message.
5. **For SQLite issues**: Look for `"database is locked"` -- if frequent, check whether
   the lifecycle scanner is running during active bulk jobs (should be yielding as of v0.13.7).
6. **For MCP issues**: Check `docker-mcp.log` for crash-loops or connection errors.
7. **For startup crashes**: Check the first 50 lines of `docker-stdout.log` -- import errors
   and missing dependencies show up here before structlog is initialized.
