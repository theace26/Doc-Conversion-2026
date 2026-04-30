/**
 * Active Operations Poller — shared frontend module (v0.35.0).
 *
 * One source of polling for /api/active-ops. Pages register subscribers;
 * one HTTP request per tick fans out to all subscribers. Visibility-
 * aware (pauses while tab hidden, matches auto-refresh.js convention).
 *
 * Public surface:
 *   window.ActiveOpsPoller.subscribe(handler);    // handler(ops_array)
 *   window.ActiveOpsPoller.unsubscribe(handler);
 *   window.ActiveOpsPoller.refresh();              // force one tick
 *
 * Backend contract: GET /api/active-ops returns {"ops": [...]}.
 *
 * Security: all values handed to subscribers are JSON primitives
 * (the server controls the shape). Subscribers must use textContent /
 * createElement, never innerHTML. See active-op-widget.js for
 * conventions.
 */
(function () {
  'use strict';

  if (window.__activeOpsPollerInstalled) return;
  window.__activeOpsPollerInstalled = true;

  var POLL_MS = 2000;
  var subscribers = [];
  var lastResult = null;
  var pollTimer = null;

  async function fetchOnce() {
    try {
      var res = await fetch('/api/active-ops', { credentials: 'same-origin' });
      if (!res.ok) return null;
      var body = await res.json();
      return Array.isArray(body && body.ops) ? body.ops : [];
    } catch (e) {
      return null;
    }
  }

  async function tick() {
    if (document.visibilityState !== 'visible') return;
    var ops = await fetchOnce();
    if (ops == null) return;   // network error; keep last result for subscribers
    lastResult = ops;
    for (var i = 0; i < subscribers.length; i++) {
      try { subscribers[i](ops); } catch (e) { /* subscriber bug; isolate */ }
    }
  }

  function startPolling() {
    if (pollTimer) return;
    tick();
    pollTimer = setInterval(tick, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      startPolling();
      tick();
    } else {
      stopPolling();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startPolling);
  } else {
    startPolling();
  }

  window.ActiveOpsPoller = {
    subscribe: function (handler) {
      if (typeof handler !== 'function') return;
      subscribers.push(handler);
      // If we have a cached result, deliver it immediately
      if (lastResult) { try { handler(lastResult); } catch (e) {} }
    },
    unsubscribe: function (handler) {
      var i = subscribers.indexOf(handler);
      if (i >= 0) subscribers.splice(i, 1);
    },
    refresh: tick,
  };
})();
