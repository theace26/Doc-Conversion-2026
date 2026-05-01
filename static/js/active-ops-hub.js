/**
 * Active Operations Hub — Status page index section (v0.35.0).
 *
 * Renders one clickable row per running op + an expandable
 * "Operations terminated by restart" card when applicable.
 *
 * Click navigates to op.origin_url + ?op_id=<id> for in-page
 * highlight on arrival.
 *
 * Public: window.mountActiveOpsHub(containerEl).
 */
(function () {
  'use strict';

  function el(tag, opts, kids) {
    var n = document.createElement(tag);
    if (opts) {
      if (opts.text != null) n.textContent = String(opts.text);
      if (opts.cls) n.className = opts.cls;
      if (opts.style) n.style.cssText = opts.style;
      if (opts.href) n.href = opts.href;
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

  function isTerminatedByRestart(op) {
    return op.finished_at_epoch != null
      && op.error_msg
      && op.error_msg.toLowerCase().indexOf('restart') >= 0;
  }

  function buildOpRow(op) {
    // Origin URL with ?op_id deep-link for in-page highlight
    var url = op.origin_url || '#';
    if (url.indexOf('?') >= 0) url += '&op_id=' + encodeURIComponent(op.op_id);
    else url += '?op_id=' + encodeURIComponent(op.op_id);

    var pct = (op.total > 0)
      ? Math.round((op.done / op.total) * 100)
      : null;

    var row = el('a', {
      href: url,
      style: 'display:flex; align-items:center; gap:1rem; '
           + 'padding:0.5rem 0.75rem; border-bottom:1px solid var(--border); '
           + 'text-decoration:none; color:inherit;',
    });
    row.appendChild(el('span', { text: op.icon || '⏳', style: 'font-size:1.05rem;' }));
    row.appendChild(el('strong', { text: op.label, style: 'flex:1; min-width:0;' }));
    row.appendChild(el('span', {
      cls: 'text-sm text-muted',
      style: 'font-family:ui-monospace,monospace;',
      text: fmtNum(op.done) + ' / ' + fmtNum(op.total)
        + (pct != null ? ' (' + pct + '%)' : ''),
    }));
    row.appendChild(el('span', { text: '→', style: 'color:var(--text-muted);' }));
    row.title = (op.error_msg ? '✗ ' + op.error_msg + ' · ' : '')
      + 'Click to jump to ' + (op.origin_url || '/');

    if (op.finished_at_epoch && op.error_msg) {
      row.style.background = 'rgba(220, 38, 38, 0.06)';
    } else if (op.finished_at_epoch) {
      row.style.opacity = '0.7';
    }
    return row;
  }

  window.mountActiveOpsHub = function (containerEl) {
    if (!containerEl) return { destroy: function () {} };

    function render(ops) {
      while (containerEl.firstChild) containerEl.removeChild(containerEl.firstChild);

      var running = ops.filter(function (op) {
        return !op.finished_at_epoch && !isTerminatedByRestart(op);
      });
      var terminated = ops.filter(isTerminatedByRestart);

      // Active Operations card
      var activeCard = el('div', {
        cls: 'card mb-2',
        style: 'padding:1rem 1.25rem;',
      });
      activeCard.appendChild(el('h3', {
        text: 'Active Operations (' + running.length + ')',
        style: 'margin:0 0 0.5rem 0;',
      }));
      if (running.length === 0) {
        activeCard.appendChild(el('div', {
          cls: 'text-sm text-muted',
          text: 'Nothing running right now.',
        }));
      } else {
        var listWrap = el('div');
        for (var i = 0; i < running.length; i++) {
          listWrap.appendChild(buildOpRow(running[i]));
        }
        activeCard.appendChild(listWrap);
      }
      containerEl.appendChild(activeCard);

      // Terminated-by-restart card (if any)
      if (terminated.length > 0) {
        var termCard = el('div', {
          cls: 'card mb-2',
          style: 'padding:1rem 1.25rem; '
               + 'border:1px solid rgba(245, 158, 11, 0.4); '
               + 'background:rgba(245, 158, 11, 0.04);',
        });
        termCard.appendChild(el('h3', {
          text: 'Operations terminated by restart (' + terminated.length + ')',
          style: 'margin:0 0 0.5rem 0;',
        }));
        var maxShown = 20;
        var shown = terminated.slice(0, maxShown);
        var listWrap2 = el('div');
        for (var j = 0; j < shown.length; j++) {
          listWrap2.appendChild(buildOpRow(shown[j]));
        }
        termCard.appendChild(listWrap2);
        if (terminated.length > maxShown) {
          var more = el('button', {
            cls: 'btn btn-ghost btn-sm',
            text: 'Show all ' + terminated.length,
            attrs: { type: 'button' },
            style: 'margin-top:0.5rem;',
          });
          var expanded = false;
          more.addEventListener('click', function () {
            if (expanded) return;
            expanded = true;
            for (var k = maxShown; k < terminated.length; k++) {
              listWrap2.appendChild(buildOpRow(terminated[k]));
            }
            more.remove();
          });
          termCard.appendChild(more);
        }
        containerEl.appendChild(termCard);
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
