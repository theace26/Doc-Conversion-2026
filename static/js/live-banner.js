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

  var FINISHED_GRACE_MS = 4000;

  // ── Banner DOM (CSS-vars only — spec §17 P8) ──────────────────────
  var bannerEl = null, iconEl = null, labelEl = null,
      barFillEl = null, counterEl = null, rateEl = null, etaEl = null;

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
      'top: 56px',
      'left: 0', 'right: 0', 'z-index: 90',
      'background: var(--surface-alt, var(--surface))',
      'border-bottom: 1px solid var(--border)',
      'color: var(--text)',
      'font-family: system-ui, sans-serif',
      'font-size: 0.85rem',
      'padding: 0.5rem 1rem',
      'display: none', 'gap: 1rem', 'align-items: center',
      'box-shadow: 0 2px 6px rgba(0,0,0,0.3)',
    ].join(';');

    iconEl = makeSpan({ style: 'font-size:1.05rem;', text: '⏳' });
    labelEl = makeSpan({ style: 'font-weight:600;', text: 'Working' });
    var progressWrap = makeSpan({ style: 'flex:1; min-width:8rem; max-width:24rem;' });
    var barTrack = document.createElement('div');
    barTrack.style.cssText = 'height:6px; background:var(--surface); border-radius:3px; overflow:hidden;';
    barFillEl = document.createElement('div');
    barFillEl.style.cssText = 'height:100%; background:var(--accent, var(--ok)); width:0%; transition:width 0.4s ease-out;';
    barTrack.appendChild(barFillEl);
    progressWrap.appendChild(barTrack);
    counterEl = makeSpan({ style: 'font-family:ui-monospace,monospace; font-size:0.78rem; white-space:nowrap;', text: '0 / 0' });
    rateEl = makeSpan({ style: 'font-family:ui-monospace,monospace; font-size:0.78rem; color:var(--text-muted); white-space:nowrap;', text: '— /s' });
    etaEl = makeSpan({ style: 'font-family:ui-monospace,monospace; font-size:0.78rem; color:var(--text-muted); white-space:nowrap;', text: 'ETA —' });
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.title = 'Hide banner (operation continues)';
    closeBtn.textContent = '×';
    closeBtn.style.cssText = 'background:transparent; border:0; color:var(--text-muted); font-size:1.1rem; cursor:pointer; padding:0 0.25rem; line-height:1;';
    closeBtn.addEventListener('click', function () { el.style.display = 'none'; bannerDismissed = true; });

    el.appendChild(iconEl); el.appendChild(labelEl);
    el.appendChild(progressWrap);
    el.appendChild(counterEl); el.appendChild(rateEl); el.appendChild(etaEl);
    el.appendChild(closeBtn);
    document.body.appendChild(el);
    bannerEl = el;
    return el;
  }

  // ── Rate / ETA ────────────────────────────────────────────────────
  function makeRateTracker() {
    var lastDone = null, lastT = null, rate = 0, ALPHA = 0.3;
    return function update(done) {
      var now = Date.now();
      if (lastDone != null && lastT != null) {
        var dt = (now - lastT) / 1000, dd = done - lastDone;
        if (dt > 0 && dd >= 0) {
          var instant = dd / dt;
          rate = (rate === 0) ? instant : ALPHA * instant + (1 - ALPHA) * rate;
        }
      }
      lastDone = done; lastT = now;
      return rate;
    };
  }
  var rateTrackers = {};
  function getRate(opId, done) {
    if (!rateTrackers[opId]) rateTrackers[opId] = makeRateTracker();
    return rateTrackers[opId](done);
  }
  function fmtDuration(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '?';
    seconds = Math.round(seconds);
    if (seconds < 60) return seconds + 's';
    var m = Math.floor(seconds / 60), s = seconds % 60;
    if (m < 60) return m + 'm ' + s + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }
  function fmtNum(n) { return n == null ? '?' : Number(n).toLocaleString(); }

  var bannerDismissed = false;
  var lastShownKey = null;
  var finishedAt = null;

  function showBanner(state) {
    var el = ensureBanner();
    el.style.display = 'flex';
    document.body.classList.add('live-banner-visible');
    if (!document.getElementById('live-banner-spacer-style')) {
      var s = document.createElement('style');
      s.id = 'live-banner-spacer-style';
      s.textContent = 'body.live-banner-visible { padding-top: 44px; }';
      document.head.appendChild(s);
    }
    iconEl.textContent = state.icon || '⏳';
    labelEl.textContent = state.label || 'Working';

    var enumerating = state.running && (!state.total || state.total <= 0) && !state.finished;
    var pct = state.total > 0 ? Math.min(100, Math.round((state.done / state.total) * 100)) : 0;
    barFillEl.style.width = pct + '%';
    if (enumerating) {
      counterEl.textContent = 'Starting…';
      rateEl.textContent = ''; etaEl.textContent = '';
    } else {
      counterEl.textContent = fmtNum(state.done) + ' / ' + fmtNum(state.total) +
        (state.errors ? ' (' + state.errors + ' errors)' : '');
      rateEl.textContent = (state.rate ? state.rate.toFixed(1) : '—') + ' /s';
      etaEl.textContent = 'ETA ' + (state.eta != null ? fmtDuration(state.eta) : '—');
    }
    if (state.finished) {
      barFillEl.style.background = state.error_msg ? 'var(--error)' : 'var(--ok)';
      etaEl.textContent = state.error_msg ? '✗' : 'Done';
    } else {
      barFillEl.style.background = 'var(--accent, var(--ok))';
    }
  }

  function hideBanner() {
    if (bannerEl) bannerEl.style.display = 'none';
    document.body.classList.remove('live-banner-visible');
  }

  // ── Subscribe to poller ──────────────────────────────────────────
  function onOps(ops) {
    var running = null;
    for (var i = 0; i < ops.length; i++) {
      if (!ops[i].finished_at_epoch) {
        if (!running || ops[i].started_at_epoch > running.started_at_epoch) {
          running = ops[i];
        }
      }
    }

    if (running) {
      if (running.op_id !== lastShownKey) {
        bannerDismissed = false;
        lastShownKey = running.op_id;
        finishedAt = null;
      }
      if (bannerDismissed) return;
      var rate = getRate(running.op_id, running.done || 0);
      var remaining = Math.max(0, (running.total || 0) - (running.done || 0));
      var eta = (rate > 0) ? remaining / rate : null;
      showBanner({
        icon: running.icon, label: running.label,
        done: running.done, total: running.total,
        errors: running.errors, rate: rate, eta: eta,
        running: true, finished: false,
      });
      return;
    }

    // Nothing running — was the last-shown op finished recently?
    if (lastShownKey) {
      var lastFinished = null;
      for (var j = 0; j < ops.length; j++) {
        if (ops[j].op_id === lastShownKey) { lastFinished = ops[j]; break; }
      }
      if (lastFinished && lastFinished.finished_at_epoch) {
        if (!finishedAt) finishedAt = Date.now();
        if (Date.now() - finishedAt < FINISHED_GRACE_MS && !bannerDismissed) {
          showBanner({
            icon: lastFinished.icon, label: lastFinished.label,
            done: lastFinished.done, total: lastFinished.total,
            errors: lastFinished.errors,
            error_msg: lastFinished.error_msg,
            rate: 0, eta: 0, finished: true,
          });
          return;
        }
      }
      lastShownKey = null; finishedAt = null;
      rateTrackers = {}; bannerDismissed = false;
    }
    hideBanner();
  }

  if (window.ActiveOpsPoller) {
    window.ActiveOpsPoller.subscribe(onOps);
  }

  // ── Deprecated legacy hook ───────────────────────────────────────
  window.LiveBanner = {
    register: function () {
      console.warn(
        'LiveBanner.register() is deprecated since v0.35.0. ' +
        'The /api/active-ops registry is the source of truth.'
      );
    },
    refresh: function () {
      if (window.ActiveOpsPoller) window.ActiveOpsPoller.refresh();
    },
  };
})();
