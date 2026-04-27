/**
 * Live Status Banner — shared across pages.
 *
 * Polls a small set of long-running operation endpoints and injects
 * a sticky banner at the top of the page (right under the nav bar)
 * when any of them are in flight. The same banner content shows on
 * every page that includes this script — so an operator emptying
 * trash from the Trash page sees the progress on Status / Pipeline
 * Files / wherever they navigate to.
 *
 * Format:
 *   🗑 Emptying trash · [bar 25%] · 127/500 files · 2.4 files/s · ETA 2m 35s · ×
 *
 * Endpoints polled (silently — failures are ignored):
 *   GET /api/trash/empty/status        {running, total, done, errors}
 *   GET /api/trash/restore-all/status  {running, total, done, errors}
 *
 * Architecture:
 *   - Single banner DOM element, position:fixed near the top
 *   - 2 s poll cadence (matches the Status page's existing rhythm)
 *   - Pauses while tab is hidden
 *   - ETA derived client-side from EWMA throughput so we don't have
 *     to add ETA fields to every backend status endpoint
 *   - Auto-collapses 4 s after the operation finishes (so the operator
 *     gets to see the final state)
 *   - Built entirely via createElement / textContent — no innerHTML
 *     so the banner is XSS-safe even if a status endpoint were
 *     ever to return operator-controlled text
 *
 * Usage:
 *   <script src="/static/js/live-banner.js"></script>
 *   No further config — the script self-installs on DOMContentLoaded.
 */
(function () {
  'use strict';

  if (window.__liveBannerInstalled) return;
  window.__liveBannerInstalled = true;

  // Tunables
  var POLL_MS = 2000;
  var FINISHED_GRACE_MS = 4000;  // Keep showing finished state for 4s
  var EWMA_ALPHA = 0.3;          // Smoothing for rate-of-progress

  // Endpoint registry — add new long-running ops here. Each entry
  // describes: how to fetch the status, how to label it, and which
  // fields carry done/total. Banner picks the first running entry
  // each tick (single-banner UX; if two ops run concurrently we show
  // the most recently started one — rare in practice).
  var endpoints = [
    {
      key: 'trash-empty',
      url: '/api/trash/empty/status',
      label: 'Emptying trash',
      icon: '\u{1F5D1}',  // 🗑
      noun: 'files',
    },
    {
      key: 'trash-restore-all',
      url: '/api/trash/restore-all/status',
      label: 'Restoring all from trash',
      icon: '♻',  // ♻
      noun: 'files',
    },
  ];

  // Per-endpoint state for ETA computation. Tracks the last (done,
  // timestamp) snapshot and a smoothed rate (files / sec).
  var rateState = {};

  function getRateState(key) {
    if (!rateState[key]) {
      rateState[key] = { last: null, rate: 0 };
    }
    return rateState[key];
  }

  function updateRate(key, done) {
    var s = getRateState(key);
    var now = Date.now();
    if (s.last) {
      var dt = (now - s.last.t) / 1000;
      var dd = done - s.last.done;
      if (dt > 0 && dd >= 0) {
        var instant = dd / dt;
        s.rate = (s.rate === 0)
          ? instant
          : (EWMA_ALPHA * instant + (1 - EWMA_ALPHA) * s.rate);
      }
    }
    s.last = { t: now, done: done };
    return s.rate;
  }

  function fmtDuration(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '?';
    seconds = Math.round(seconds);
    if (seconds < 60) return seconds + 's';
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    if (m < 60) return m + 'm ' + s + 's';
    var h = Math.floor(m / 60);
    return h + 'h ' + (m % 60) + 'm';
  }

  function fmtNum(n) {
    if (n == null) return '?';
    return Number(n).toLocaleString();
  }

  // ── Banner DOM (built entirely via createElement / textContent) ──
  // Refs to inner span elements so we update them without rebuilding
  // the banner each tick.
  var bannerEl = null;
  var iconEl = null;
  var labelEl = null;
  var barFillEl = null;
  var counterEl = null;
  var rateEl = null;
  var etaEl = null;

  function makeSpan(opts) {
    var s = document.createElement('span');
    if (opts && opts.cls) s.className = opts.cls;
    if (opts && opts.style) s.style.cssText = opts.style;
    if (opts && opts.text != null) s.textContent = opts.text;
    return s;
  }

  function ensureBanner() {
    if (bannerEl) return bannerEl;
    var el = document.createElement('div');
    el.id = 'live-status-banner';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = [
      'position: fixed',
      'top: 0',
      'left: 0',
      'right: 0',
      'z-index: 9999',
      'background: linear-gradient(90deg, rgba(99,102,241,0.18), rgba(96,165,250,0.18))',
      'border-bottom: 1px solid rgba(96,165,250,0.45)',
      'color: #e0e7ff',
      'font-family: system-ui, sans-serif',
      'font-size: 0.85rem',
      'padding: 0.5rem 1rem',
      'display: none',
      'gap: 1rem',
      'align-items: center',
      'box-shadow: 0 2px 6px rgba(0,0,0,0.3)',
      'backdrop-filter: blur(4px)',
    ].join(';');

    iconEl = makeSpan({ cls: 'lb-icon', style: 'font-size:1.05rem;', text: '⏳' });
    labelEl = makeSpan({ cls: 'lb-label', style: 'font-weight:600;', text: 'Working' });

    var progressWrap = makeSpan({
      cls: 'lb-progress-wrap',
      style: 'flex:1; min-width:8rem; max-width:24rem;',
    });
    var barTrack = document.createElement('div');
    barTrack.className = 'lb-bar-track';
    barTrack.style.cssText = 'height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;';
    barFillEl = document.createElement('div');
    barFillEl.className = 'lb-bar-fill';
    barFillEl.style.cssText = 'height:100%;background:linear-gradient(90deg,#6366f1,#3b82f6);width:0%;transition:width 0.4s ease-out;';
    barTrack.appendChild(barFillEl);
    progressWrap.appendChild(barTrack);

    counterEl = makeSpan({
      cls: 'lb-counter',
      style: 'font-family:ui-monospace,monospace;font-size:0.78rem;white-space:nowrap;',
      text: '0 / 0',
    });
    rateEl = makeSpan({
      cls: 'lb-rate',
      style: 'font-family:ui-monospace,monospace;font-size:0.78rem;color:rgba(224,231,255,0.75);white-space:nowrap;',
      text: '— files/s',
    });
    etaEl = makeSpan({
      cls: 'lb-eta',
      style: 'font-family:ui-monospace,monospace;font-size:0.78rem;color:rgba(224,231,255,0.85);white-space:nowrap;',
      text: 'ETA —',
    });

    var closeBtn = document.createElement('button');
    closeBtn.className = 'lb-close';
    closeBtn.type = 'button';
    closeBtn.title = 'Hide banner (operation continues)';
    closeBtn.textContent = '×';  // ×
    closeBtn.style.cssText = 'background:transparent;border:0;color:rgba(224,231,255,0.7);font-size:1.1rem;cursor:pointer;padding:0 0.25rem;line-height:1;';
    closeBtn.addEventListener('click', function () {
      el.style.display = 'none';
      bannerDismissed = true;
    });

    el.appendChild(iconEl);
    el.appendChild(labelEl);
    el.appendChild(progressWrap);
    el.appendChild(counterEl);
    el.appendChild(rateEl);
    el.appendChild(etaEl);
    el.appendChild(closeBtn);

    document.body.appendChild(el);
    bannerEl = el;
    return el;
  }

  function showBanner(state) {
    var el = ensureBanner();
    el.style.display = 'flex';
    iconEl.textContent = state.icon || '⏳';
    labelEl.textContent = state.label || 'Working';
    var pct = state.total > 0
      ? Math.min(100, Math.round((state.done / state.total) * 100))
      : 0;
    barFillEl.style.width = pct + '%';
    counterEl.textContent =
      fmtNum(state.done) + ' / ' + fmtNum(state.total) + ' ' + (state.noun || '') +
      (state.errors ? ' (' + state.errors + ' errors)' : '');
    rateEl.textContent =
      (state.rate ? state.rate.toFixed(1) : '—') + ' ' + (state.noun || 'items') + '/s';
    etaEl.textContent = 'ETA ' + (state.eta != null ? fmtDuration(state.eta) : '—');

    if (state.finished) {
      el.style.background = 'linear-gradient(90deg, rgba(34,197,94,0.18), rgba(22,163,74,0.18))';
      el.style.borderBottomColor = 'rgba(34,197,94,0.45)';
      etaEl.textContent = 'Done';
    } else {
      el.style.background = 'linear-gradient(90deg, rgba(99,102,241,0.18), rgba(96,165,250,0.18))';
      el.style.borderBottomColor = 'rgba(96,165,250,0.45)';
    }
  }

  function hideBanner() {
    if (bannerEl) bannerEl.style.display = 'none';
  }

  var bannerDismissed = false;
  var lastShownKey = null;
  var finishedAt = null;

  // ── Polling ─────────────────────────────────────────────────────
  async function fetchOne(ep) {
    try {
      var res = await fetch(ep.url, { credentials: 'same-origin' });
      if (!res.ok) return null;
      var data = await res.json();
      return data || null;
    } catch (e) {
      return null;
    }
  }

  async function tick() {
    if (document.visibilityState !== 'visible') return;

    // Fetch all endpoints in parallel — typically only one is live
    // at any time, but the cost of polling 2-3 status endpoints in
    // parallel is negligible (<5ms each on local backend).
    var results = await Promise.all(endpoints.map(fetchOne));

    // Pick the first running one; fall through to the last-shown
    // one if it's now finished (so we display the green "Done"
    // state for FINISHED_GRACE_MS before hiding the banner).
    var active = null;
    for (var i = 0; i < endpoints.length; i++) {
      if (results[i] && results[i].running) {
        active = { ep: endpoints[i], data: results[i] };
        break;
      }
    }

    if (active) {
      // A new operation started — clear any prior dismissal.
      if (active.ep.key !== lastShownKey) {
        bannerDismissed = false;
        lastShownKey = active.ep.key;
        finishedAt = null;
      }
      if (bannerDismissed) return;

      var rate = updateRate(active.ep.key, active.data.done || 0);
      var remaining = Math.max(0, (active.data.total || 0) - (active.data.done || 0));
      var eta = (rate > 0) ? remaining / rate : null;

      showBanner({
        icon: active.ep.icon,
        label: active.ep.label,
        noun: active.ep.noun,
        done: active.data.done || 0,
        total: active.data.total || 0,
        errors: active.data.errors || 0,
        rate: rate,
        eta: eta,
        finished: false,
      });
      return;
    }

    // Nothing running. If we were just showing one, freeze it on
    // "Done" for a few seconds before hiding.
    if (lastShownKey) {
      var lastEp = null, lastData = null;
      for (var j = 0; j < endpoints.length; j++) {
        if (endpoints[j].key === lastShownKey) {
          lastEp = endpoints[j];
          lastData = results[j];
          break;
        }
      }
      if (lastEp && lastData) {
        if (!finishedAt) finishedAt = Date.now();
        if (Date.now() - finishedAt < FINISHED_GRACE_MS && !bannerDismissed) {
          showBanner({
            icon: lastEp.icon,
            label: lastEp.label,
            noun: lastEp.noun,
            done: lastData.done || 0,
            total: lastData.total || 0,
            errors: lastData.errors || 0,
            rate: 0,
            eta: 0,
            finished: true,
          });
          return;
        }
      }
      lastShownKey = null;
      finishedAt = null;
      rateState = {};
      bannerDismissed = false;
    }
    hideBanner();
  }

  function startPolling() {
    tick();
    setInterval(tick, POLL_MS);
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') tick();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startPolling);
  } else {
    startPolling();
  }

  // Public hook — pages can register additional long-running
  // endpoints. Banner picks them up on the next tick.
  window.LiveBanner = {
    register: function (def) {
      if (!def || !def.key || !def.url) return;
      for (var i = 0; i < endpoints.length; i++) {
        if (endpoints[i].key === def.key) return;
      }
      endpoints.push(def);
    },
    refresh: tick,
  };

})();
