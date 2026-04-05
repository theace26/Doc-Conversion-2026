"""
AI Assist usage logging and org-wide toggle.
Writes to ai_assist_usage table. All writes go through db_write_with_retry.
Toggle stored in user_preferences table.
"""
import structlog
from core.db.connection import db_fetch_one, db_fetch_all, db_execute, db_write_with_retry

log = structlog.get_logger()

AI_ASSIST_PREF_KEY = "ai_assist_enabled"


# ─── Org toggle ────────────────────────────────────────────────────────────────

async def get_ai_assist_enabled() -> bool:
    """
    Returns True if AI Assist is enabled org-wide.
    Defaults to False — an admin must explicitly enable it.
    """
    row = await db_fetch_one(
        "SELECT value FROM user_preferences WHERE key = ?",
        (AI_ASSIST_PREF_KEY,),
    )
    if not row:
        return False
    return row["value"].strip().lower() in ("1", "true", "yes")


async def set_ai_assist_enabled(enabled: bool) -> None:
    """Persist org-wide AI Assist toggle."""
    value = "true" if enabled else "false"
    await db_write_with_retry(
        lambda: db_execute(
            """
            INSERT INTO user_preferences (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = datetime('now')
            """,
            (AI_ASSIST_PREF_KEY, value),
        )
    )
    log.info("ai_assist.toggle", enabled=enabled)


# ─── Usage logging ─────────────────────────────────────────────────────────────

async def log_ai_usage(
    user_id: str,
    username: str | None,
    query: str,
    mode: str,
    result_count: int,
    input_tokens_est: int,
    output_tokens_est: int,
) -> None:
    """
    Insert a usage record. Fire-and-forget — failure is logged but never
    raised so it cannot interrupt a streaming response.
    """
    try:
        await db_write_with_retry(
            lambda: db_execute(
                """
                INSERT INTO ai_assist_usage
                    (user_id, username, query, mode, result_count,
                     input_tokens_est, output_tokens_est)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username or user_id,
                    query[:500],
                    mode,
                    result_count,
                    input_tokens_est,
                    output_tokens_est,
                ),
            )
        )
        log.info(
            "ai_assist.usage_logged",
            user_id=user_id,
            mode=mode,
            input_tokens_est=input_tokens_est,
            output_tokens_est=output_tokens_est,
        )
    except Exception as exc:
        log.error("ai_assist.usage_log_failed", error=str(exc))


# ─── Admin queries ──────────────────────────────────────────────────────────────

async def get_usage_summary(limit: int = 200) -> list[dict]:
    """Recent usage rows, newest first."""
    return await db_fetch_all(
        """
        SELECT user_id, username, query, mode, result_count,
               input_tokens_est, output_tokens_est, created_at
        FROM ai_assist_usage
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )


async def get_usage_by_user() -> list[dict]:
    """Per-user totals for the admin dashboard."""
    return await db_fetch_all(
        """
        SELECT
            user_id,
            username,
            COUNT(*)                                      AS total_calls,
            SUM(input_tokens_est)                         AS total_input_tokens,
            SUM(output_tokens_est)                        AS total_output_tokens,
            SUM(input_tokens_est + output_tokens_est)     AS total_tokens,
            MAX(created_at)                               AS last_used
        FROM ai_assist_usage
        GROUP BY user_id
        ORDER BY total_tokens DESC
        """,
    )
