"""
File retention and cleanup logic.

- Deletes output files older than `retention_days` preference (default: 30 days)
- Preserves SQLite history records after file cleanup
- Disk space check: warns if < 1GB free before conversion
- Manual cleanup via POST /api/cleanup
"""
