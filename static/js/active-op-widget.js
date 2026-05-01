/**
 * Active Op Widget — inline progress display (v0.35.0).
 *
 * Mounts a self-updating list of currently-running operations matching
 * a per-page filter. Used on origin pages (history.html, trash.html,
 * settings.html, batch-management.html, bulk.html).
 *
 * Public:
 *   window.mountActiveOpWidget(containerEl, opts);
 *
 * Options:
 *   filter:        (op) => bool  — page-specific predicate
 *   highlightOpId: string        — pulse-and-scroll this op on first render
 *
 * Styling: CSS variables only (var(--surface), var(--text), etc.).
 * No hardcoded colors. UX redesign can re-skin without touching JS
 * (spec §17 P8).
 *
 * Security: all rendered content via createElement + textContent.
 */
(function () {
  'use strict';

  function el(tag, opts, kids) {
    var n = document.createElement(tag);
    if (opts) {
      if (opts.text != null) n.textContent = String(opts.text);
      if (opts.cls) n.className = opts.cls;
      if (opts.style) n.style.cssText = opts.style;
      if (opts.attrs) {
        for (var k in opts.attrs) n.setAttribute(k, opts.attrs[k]);
      }
      if (opts.onClick) n.addEventListener('click', opts.onClick);
    }
    if (kids) {
      for (var i = 0; i < kids.length; i++) {
        if (kids[i] != null) n.appendChild(kids[i]);
      }
    }
    return n;
  }

  function fmtNum(x) {
    return x == null ? '?' : Number(x).toLocaleString();
  }

  function fmtDuration(seconds) {
    if (!isFinite(seconds) || seconds < 0) return '?';
    seconds = Math.round(seconds);
    if (seconds < 60) return seconds + 's';
    var m = Math.floor(seconds / 60), s = seconds % 60;
    if (m < 60) return m + 'm ' + s + 's';
    var h = Math.floor(m / 60);
    return h + 'h ' + (m % 60) + 'm';
  }

  // Per-op rate state (EWMA over done deltas) for client-side ETA.
  // Server doesn't ship ETA; we derive it.
  function makeRateTracker() {
    var lastDone = null, lastT = null, rate = 0, ALPHA = 0.3;
    return function update(done) {
      var now = Date.now();
      if (lastDone != null && lastT != null) {
        var dt = (now - lastT) / 1000;
        var dd = done - lastDone;
        if (dt > 0 && dd >= 0) {
          var instant = dd / dt;
          rate = (rate === 0) ? instant : ALPHA * instant + (1 - ALPHA) * rate;
        }
      }
      lastDone = done;
      lastT = now;
      return rate;
    };
  }

  function buildRow(op, rateTracker, opts) {
    var card = el('div', {
      cls: 'card active-op-row',
      attrs: { 'data-op-id': op.op_id },
      style: 'padding:0.75rem 1rem; margin-bottom:0.5rem;',
    });

    var header = el('div', {
      style: 'display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem;',
    });
    header.appendChild(el('span', { text: op.icon || '⏳', style: 'font-size:1.1rem;' }));
    header.appendChild(el('strong', { text: op.label }));

    if (op.cancellable && !op.finished_at_epoch) {
      var cancelBtn = el('button', {
        cls: 'btn btn-ghost btn-sm',
        text: 'Cancel',
        attrs: { type: 'button' },
        style: 'margin-left:auto;',
        onClick: async function () {
          cancelBtn.disabled = true;
          cancelBtn.textContent = 'Cancelling…';
          try {
            await fetch('/api/active-ops/' + encodeURIComponent(op.op_id) + '/cancel', {
              method: 'POST', credentials: 'same-origin',
            });
          } catch (e) {}
        },
      });
      header.appendChild(cancelBtn);
    }
    card.appendChild(header);

    // Progress bar
    var pct = (op.total > 0)
      ? Math.min(100, Math.round((op.done / op.total) * 100))
      : 0;
    var barTrack = el('div', {
      style: 'height:6px; background:var(--surface-alt, rgba(255,255,255,0.08)); '
           + 'border-radius:3px; overflow:hidden; margin-bottom:0.3rem;',
    });
    var barFill = el('div', {
      style: 'height:100%; width:' + pct + '%; '
           + 'background:var(--accent, var(--ok)); '
           + 'transition:width 0.4s ease-out;',
    });
    barTrack.appendChild(barFill);
    card.appendChild(barTrack);

    // Counter line
    var rate = rateTracker(op.done || 0);
    var remaining = Math.max(0, (op.total || 0) - (op.done || 0));
    var eta = (rate > 0) ? remaining / rate : null;
    var elapsed = (Date.now() / 1000) - op.started_at_epoch;

    var enumerating = !op.finished_at_epoch
      && (!op.total || op.total <= 0);
    var counterText;
    if (op.finished_at_epoch) {
      counterText = (op.error_msg
        ? '✗ ' + op.error_msg
        : '✓ Done · ' + fmtNum(op.done) + (op.total ? ' / ' + fmtNum(op.total) : '')
          + (op.errors ? ' (' + op.errors + ' errors)' : ''));
    } else if (enumerating) {
      counterText = 'Starting…';
    } else {
      counterText = fmtNum(op.done) + ' / ' + fmtNum(op.total)
        + (op.errors ? ' (' + op.errors + ' errors)' : '')
        + ' · ' + (rate ? rate.toFixed(1) : '—') + '/s'
        + ' · ETA ' + (eta != null ? fmtDuration(eta) : '—');
    }
    var counterLine = el('div', {
      cls: 'text-sm text-muted',
      style: 'font-family:ui-monospace,monospace;',
      text: counterText,
    });
    card.appendChild(counterLine);

    // Footer line: started + by
    var footer = el('div', {
      cls: 'text-sm text-muted',
      style: 'margin-top:0.2rem;',
      text: 'started ' + fmtDuration(elapsed) + ' ago by ' + (op.started_by || '?'),
    });
    card.appendChild(footer);

    if (op.finished_at_epoch) {
      card.style.opacity = '0.7';
      barFill.style.background = op.error_msg
        ? 'var(--error)'
        : 'var(--ok)';
    }

    return card;
  }

  function highlightCard(card) {
    card.style.transition = 'box-shadow 0.4s ease';
    card.style.boxShadow = '0 0 0 3px rgba(245, 158, 11, 0.55)';
    setTimeout(function () {
      card.style.boxShadow = 'none';
    }, 1800);
    try { card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) {}
  }

  window.mountActiveOpWidget = function (containerEl, opts) {
    if (!containerEl) return { destroy: function () {} };
    opts = opts || {};
    var filter = opts.filter || function () { return true; };
    var highlightOpId = opts.highlightOpId || null;

    // Per-op rate trackers, keyed by op_id (kept across renders so
    // EWMA isn't reset on every poll tick)
    var rateTrackers = Object.create(null);
    var didHighlight = false;

    function render(ops) {
      var matching = ops.filter(filter);
      while (containerEl.firstChild) containerEl.removeChild(containerEl.firstChild);
      if (matching.length === 0) {
        containerEl.style.display = 'none';
        return;
      }
      containerEl.style.display = 'block';
      for (var i = 0; i < matching.length; i++) {
        var op = matching[i];
        if (!rateTrackers[op.op_id]) rateTrackers[op.op_id] = makeRateTracker();
        var card = buildRow(op, rateTrackers[op.op_id], opts);
        containerEl.appendChild(card);
        if (highlightOpId && op.op_id === highlightOpId && !didHighlight) {
          didHighlight = true;
          setTimeout(highlightCard.bind(null, card), 50);
        }
      }
    }

    if (window.ActiveOpsPoller) {
      window.ActiveOpsPoller.subscribe(render);
      return {
        destroy: function () {
          if (window.ActiveOpsPoller) window.ActiveOpsPoller.unsubscribe(render);
        },
      };
    }
    return { destroy: function () {} };
  };
})();
