/**
 * MarkFlow Auto-Refresh helper (v0.32.0).
 *
 * Tiny shared utility for pages that show server-side state that
 * changes outside of user interaction (file lists, batch statuses,
 * flagged-file queues, etc.). Pages opt in by calling
 * `AutoRefresh.start({...})` with a refresh callback.
 *
 * Behavior:
 *   - Calls the refresh callback every `intervalMs` while the tab
 *     is visible (default 30 s).
 *   - Pauses polling when the tab is hidden (visibilitychange ===
 *     'hidden') so we don't burn API calls on backgrounded tabs.
 *   - On tab focus (visibilitychange === 'visible'), fires one
 *     immediate refresh and resumes the interval.
 *   - Tracks a `lastRefreshAt` timestamp the page can render in a
 *     "last updated 14s ago" indicator if it wants.
 *
 * Why a shared helper rather than copy-pasted per page:
 *   - Consistent policy across the app — every list page polls at
 *     the same cadence, pauses while hidden, refreshes on focus.
 *   - Single place to change defaults if the policy needs tuning.
 *   - Lets pages with their own polling (status.html, bulk.html
 *     SSE) continue on their existing pattern without conflict.
 */
(function (global) {
  'use strict';

  // Defaults — match the cadence of /api/health and the Status page
  // so all of MarkFlow's auto-refresh feels coherent.
  var DEFAULT_INTERVAL_MS = 30 * 1000;

  function startAutoRefresh(opts) {
    opts = opts || {};
    var refresh = opts.refresh;
    if (typeof refresh !== 'function') {
      throw new Error('AutoRefresh.start: opts.refresh must be a function');
    }
    var intervalMs = Math.max(2000, opts.intervalMs || DEFAULT_INTERVAL_MS);
    var pauseWhenHidden = opts.pauseWhenHidden !== false;
    var refreshOnFocus = opts.refreshOnFocus !== false;
    var onTick = opts.onTick;  // optional hook (called after each refresh)

    var timer = null;
    var lastRefreshAt = 0;
    var inFlight = false;

    async function safeRefresh(reason) {
      // Guard: never run two refreshes concurrently. Slow networks
      // / slow backends would otherwise stack and burn server time.
      if (inFlight) return;
      inFlight = true;
      try {
        await refresh(reason);
        lastRefreshAt = Date.now();
        if (typeof onTick === 'function') {
          try { onTick(reason, lastRefreshAt); } catch (e) {}
        }
      } catch (e) {
        // Swallow — refresh failures shouldn't break the page.
        if (global.console) console.warn('AutoRefresh: refresh failed', e);
      } finally {
        inFlight = false;
      }
    }

    function schedule() {
      if (timer) return;
      timer = setInterval(function () {
        safeRefresh('interval');
      }, intervalMs);
    }

    function unschedule() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    function onVisibilityChange() {
      if (document.visibilityState === 'visible') {
        if (refreshOnFocus) {
          safeRefresh('focus');
        }
        schedule();
      } else if (pauseWhenHidden) {
        unschedule();
      }
    }

    if (pauseWhenHidden) {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }

    // Kick off if the tab is currently visible (page just loaded).
    if (document.visibilityState === 'visible') {
      schedule();
    }

    // Public handle for callers that want to force a refresh
    // (e.g. after a user action like cancel-batch / re-flag).
    return {
      refreshNow: function () { return safeRefresh('manual'); },
      stop: function () {
        unschedule();
        document.removeEventListener('visibilitychange', onVisibilityChange);
      },
      lastRefreshAt: function () { return lastRefreshAt; },
    };
  }

  // Render a human-readable "last updated 14s ago" string for the
  // optional indicator. Pages can wire this up to a status element
  // by calling it from `onTick`.
  function formatRelativeTime(ts) {
    if (!ts) return 'never';
    var s = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (s < 60) return s + 's ago';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm ago';
    var h = Math.floor(m / 60);
    return h + 'h ago';
  }

  global.AutoRefresh = {
    start: startAutoRefresh,
    formatRelativeTime: formatRelativeTime,
    DEFAULT_INTERVAL_MS: DEFAULT_INTERVAL_MS,
  };

})(window);
