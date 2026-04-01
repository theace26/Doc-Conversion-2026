"""
core.db — Domain-split database package.

All public symbols are re-exported here for convenience.
External code should import from ``core.database`` (backward-compatible wrapper).
"""

# Connection & utilities
from core.db.connection import (
    DB_PATH,
    _count_by_status,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_write_with_retry,
    get_db,
    get_db_path,
    now_iso,
)

# Schema & init
from core.db.schema import (
    cleanup_orphaned_jobs,
    init_db,
)

# Preferences
from core.db.preferences import (
    DEFAULT_PREFERENCES,
    get_all_preferences,
    get_preference,
    set_preference,
)

# Bulk jobs & files
from core.db.bulk import (
    create_bulk_job,
    get_bulk_file_count,
    get_bulk_files,
    get_bulk_job,
    get_unprocessed_bulk_files,
    increment_bulk_job_counter,
    list_bulk_jobs,
    update_bulk_file,
    update_bulk_job_status,
    upsert_bulk_file,
    upsert_source_file,
)

# Conversions & OCR
from core.db.conversions import (
    add_to_review_queue,
    get_batch_state,
    get_flag_counts,
    get_flags_for_batch,
    get_ocr_gap_fill_candidates,
    get_ocr_gap_fill_count,
    get_review_queue,
    get_review_queue_count,
    get_review_queue_entry,
    get_review_queue_summary,
    get_scene_keyframes,
    insert_ocr_flag,
    record_conversion,
    record_scene_keyframes,
    resolve_all_pending,
    resolve_flag,
    update_bulk_file_confidence,
    update_history_ocr_stats,
    update_history_vision_stats,
    update_review_queue_entry,
    upsert_batch_state,
)

# Catalog (adobe, locations, LLM, unrecognized, archives)
from core.db.catalog import (
    create_llm_provider,
    create_location,
    delete_llm_provider,
    delete_location,
    get_active_provider,
    get_adobe_index_entry,
    get_archive_member_by_hash,
    get_archive_member_count,
    get_archive_members,
    get_llm_provider,
    get_location,
    get_unindexed_adobe_entries,
    get_unrecognized_files,
    get_unrecognized_stats,
    list_llm_providers,
    list_locations,
    mark_adobe_meili_indexed,
    set_active_provider,
    update_archive_member,
    update_llm_provider,
    update_location,
    upsert_adobe_index,
    upsert_archive_member,
)

# Lifecycle, versions, scans, maintenance
from core.db.lifecycle import (
    create_scan_run,
    create_version_snapshot,
    get_bulk_file_by_content_hash,
    get_bulk_file_by_path,
    get_bulk_files_by_lifecycle_status,
    get_bulk_files_pending_purge,
    get_bulk_files_pending_trash,
    get_collision_group,
    get_latest_scan_run,
    get_maintenance_log,
    get_next_version_number,
    get_path_issue_count,
    get_path_issue_summary,
    get_path_issues,
    get_scan_run,
    get_source_file_by_path,
    get_source_file_count,
    get_source_files_by_lifecycle_status,
    get_source_files_pending_purge,
    get_source_files_pending_trash,
    get_version,
    get_version_history,
    log_maintenance,
    record_path_issue,
    update_path_issue_resolution,
    update_scan_run,
    update_source_file,
)

# API keys
from core.db.auth import (
    create_api_key,
    get_api_key_by_hash,
    list_api_keys,
    revoke_api_key,
    touch_api_key,
)

__all__ = [
    # connection
    "DB_PATH", "get_db_path", "get_db", "db_write_with_retry",
    "db_fetch_one", "db_fetch_all", "db_execute",
    "_count_by_status", "now_iso",
    # schema
    "init_db", "cleanup_orphaned_jobs",
    # preferences
    "DEFAULT_PREFERENCES", "get_preference", "set_preference", "get_all_preferences",
    # bulk
    "create_bulk_job", "get_bulk_job", "list_bulk_jobs",
    "update_bulk_job_status", "increment_bulk_job_counter",
    "upsert_source_file", "upsert_bulk_file",
    "get_bulk_files", "get_bulk_file_count", "update_bulk_file",
    "get_unprocessed_bulk_files",
    # conversions
    "record_conversion", "upsert_batch_state", "get_batch_state",
    "insert_ocr_flag", "get_flags_for_batch", "resolve_flag",
    "resolve_all_pending", "get_flag_counts",
    "add_to_review_queue", "get_review_queue", "get_review_queue_entry",
    "update_review_queue_entry", "get_review_queue_summary",
    "get_review_queue_count", "get_ocr_gap_fill_candidates",
    "get_ocr_gap_fill_count", "update_bulk_file_confidence",
    "update_history_ocr_stats", "update_history_vision_stats",
    "record_scene_keyframes", "get_scene_keyframes",
    # catalog
    "upsert_adobe_index", "get_adobe_index_entry",
    "get_unindexed_adobe_entries", "mark_adobe_meili_indexed",
    "create_location", "get_location", "list_locations",
    "update_location", "delete_location",
    "create_llm_provider", "get_llm_provider", "list_llm_providers",
    "update_llm_provider", "delete_llm_provider",
    "set_active_provider", "get_active_provider",
    "get_unrecognized_files", "get_unrecognized_stats",
    "upsert_archive_member", "update_archive_member",
    "get_archive_members", "get_archive_member_by_hash",
    "get_archive_member_count",
    # lifecycle
    "get_bulk_file_by_path", "get_bulk_file_by_content_hash",
    "get_bulk_files_by_lifecycle_status",
    "get_bulk_files_pending_trash", "get_bulk_files_pending_purge",
    "get_source_file_by_path", "get_source_file_count",
    "update_source_file", "get_source_files_by_lifecycle_status",
    "get_source_files_pending_trash", "get_source_files_pending_purge",
    "record_path_issue", "get_path_issues", "get_path_issue_summary",
    "get_path_issue_count", "update_path_issue_resolution",
    "get_collision_group",
    "create_version_snapshot", "get_version_history",
    "get_version", "get_next_version_number",
    "create_scan_run", "update_scan_run", "get_scan_run",
    "get_latest_scan_run",
    "log_maintenance", "get_maintenance_log",
    # auth
    "create_api_key", "get_api_key_by_hash", "revoke_api_key",
    "list_api_keys", "touch_api_key",
]
