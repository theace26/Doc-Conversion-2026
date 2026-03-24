/**
 * Lifecycle badge component — renders a colored status badge for file lifecycle state.
 */
function renderLifecycleBadge(status, details) {
  const badge = document.createElement('span');
  badge.className = 'lifecycle-badge';

  const config = {
    active:              { color: 'ok',    label: 'Active' },
    marked_for_deletion: { color: 'warn',  label: 'Marked for Deletion' },
    in_trash:            { color: 'error', label: 'In Trash' },
    purged:              { color: 'muted', label: 'Purged' },
  };

  const c = config[status] || config.active;
  badge.classList.add(`lifecycle-${c.color}`);
  badge.textContent = c.label;

  // Tooltip text
  if (status === 'marked_for_deletion' && details) {
    const markedAt = details.marked_for_deletion_at;
    if (markedAt) {
      const hrs = Math.round((Date.now() - new Date(markedAt).getTime()) / 3600000);
      const grace = (details.grace_period_hours || 36) - hrs;
      badge.title = `Marked ${hrs}h ago \u2014 moves to trash in ${Math.max(0, grace)}h`;
    }
  } else if (status === 'in_trash' && details) {
    const trashedAt = details.moved_to_trash_at;
    if (trashedAt) {
      const days = Math.round((Date.now() - new Date(trashedAt).getTime()) / 86400000);
      const remaining = (details.trash_retention_days || 60) - days;
      badge.title = `Trashed ${days}d ago \u2014 deleted in ${Math.max(0, remaining)}d`;
    }
  }

  return badge;
}

/**
 * Returns an HTML string for inline use.
 */
function lifecycleBadgeHTML(status, details) {
  const el = renderLifecycleBadge(status, details);
  return el.outerHTML;
}
