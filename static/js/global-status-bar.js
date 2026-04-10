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

  var POLL_VISIBLE = 20000;
  var POLL_HIDDEN = 30000;
  var MAX_HIDDEN_MS = 1800000;
  var hiddenSince = null;
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
    pollTimer = setInterval(poll, POLL_VISIBLE);
  }

  document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
      hiddenSince = Date.now();
      clearInterval(pollTimer);
      pollTimer = setInterval(function() {
        if (Date.now() - hiddenSince > MAX_HIDDEN_MS) {
          clearInterval(pollTimer);
          pollTimer = null;
          return;
        }
        poll();
      }, POLL_HIDDEN);
    } else {
      hiddenSince = null;
      clearInterval(pollTimer);
      location.reload();
    }
  });

  // Expose for immediate refresh from other scripts (e.g. status.html reset)
  window.refreshStatusBadge = poll;

  poll();
  startPolling();
}
