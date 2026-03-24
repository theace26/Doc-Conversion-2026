/**
 * Deletion warning banner — shows a dismissible banner when search results
 * include files with non-active lifecycle status.
 */
function checkDeletionBanner(files, containerId) {
  const container = document.getElementById(containerId || 'deletion-banner');
  if (!container) return;

  // Check sessionStorage for dismissal
  const pageKey = 'dismiss_deletion_' + (location.search || location.pathname);
  if (sessionStorage.getItem(pageKey)) {
    container.hidden = true;
    return;
  }

  // Count non-active files
  const nonActive = (files || []).filter(f =>
    f.lifecycle_status && f.lifecycle_status !== 'active'
  );

  if (nonActive.length === 0) {
    container.hidden = true;
    return;
  }

  const trashed = nonActive.filter(f => f.lifecycle_status === 'in_trash').length;
  const marked = nonActive.filter(f => f.lifecycle_status === 'marked_for_deletion').length;
  const purged = nonActive.filter(f => f.lifecycle_status === 'purged').length;

  let parts = [];
  if (marked) parts.push(`${marked} marked for deletion`);
  if (trashed) parts.push(`${trashed} in trash`);
  if (purged) parts.push(`${purged} purged`);

  container.innerHTML = `
    <div class="deletion-banner">
      <span>Some results include files that are no longer active: ${parts.join(', ')}.</span>
      <a href="/trash.html">Manage Trash</a>
      <button class="btn btn-ghost btn-sm" onclick="dismissDeletionBanner('${pageKey}', '${containerId || 'deletion-banner'}')">Dismiss</button>
    </div>
  `;
  container.hidden = false;
}

function dismissDeletionBanner(key, containerId) {
  sessionStorage.setItem(key, '1');
  const el = document.getElementById(containerId);
  if (el) el.hidden = true;
}
