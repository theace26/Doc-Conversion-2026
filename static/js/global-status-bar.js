/**
 * global-status-bar.js — v2 (badge-only)
 *
 * No longer injects a floating bar. Instead, updates a badge on the
 * "Status" nav link to show the active job count.
 *
 * Called from app.js after buildNav() completes.
 */

function initStatusBadge() {
  // Find the badge span inside the Status nav link
  var badge = document.querySelector('.nav-badge');
  if (!badge) return;

  var pollTimer = null;

  async function poll() {
    try {
      var res = await fetch('/api/admin/active-jobs');
      if (res.status === 401 || res.status === 403) return;
      if (!res.ok) return;
      var data = await res.json();
      var count = data.running_count || 0;
      var stopped = data.stop_requested;

      if (count > 0 || stopped) {
        badge.style.display = '';
        badge.textContent = stopped ? '!' : String(count);
        badge.className = stopped ? 'nav-badge nav-badge--stopped' : 'nav-badge';
      } else {
        badge.style.display = 'none';
      }
    } catch (e) { /* ignore */ }
  }

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, document.hidden ? 30000 : 5000);
  }

  document.addEventListener('visibilitychange', function () {
    startPolling();
    if (!document.hidden) poll();
  });

  poll();
  startPolling();
}
