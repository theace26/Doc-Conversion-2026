/* MFLogLevels — per-subsystem log level configuration page component.
 *
 * Reads current levels from GET /api/log-levels
 * Writes changes via PUT /api/log-levels  (body: {logger, level})
 *
 * Groups loggers by namespace prefix (first dotted segment).
 * Provides a "Reset to defaults" button that reloads from the API.
 *
 * Admin-only (boot script guards). Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'NOTSET'];

  var LEVEL_COLORS = {
    DEBUG: '#9ca3af',
    INFO: '#60a5fa',
    WARNING: '#fbbf24',
    ERROR: '#f87171',
    CRITICAL: '#fecaca',
    NOTSET: '#6b7280',
  };

  // Default levels per well-known namespace (for "Reset" UX hint only —
  // actual reset reloads from the server which reflects Python defaults).
  var KNOWN_NAMESPACES = ['core', 'api', 'web_app', 'scripts', 'markflow', 'uvicorn', 'fastapi', 'root'];

  // ── CSS (injected once) ──────────────────────────────────────────────────
  var _cssInjected = false;
  function injectCss() {
    if (_cssInjected) return;
    _cssInjected = true;
    var style = document.createElement('style');
    style.textContent = [
      '.mf-ll { max-width:900px; margin:0 auto; padding:1.5rem 1rem 3rem; }',
      '.mf-ll__head { margin-bottom:1rem; }',
      '.mf-ll__head h1 { margin:0 0 0.35rem; font-size:1.65rem; font-weight:700; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-ll__head p { margin:0; font-size:0.88rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-ll__topbar { display:flex; flex-wrap:wrap; align-items:center; gap:0.65rem; margin-bottom:1rem; }',
      '.mf-ll__search { padding:0.35rem 0.65rem; background:var(--mf-surface,#16213e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.88rem; min-width:220px; }',
      '.mf-ll__ns-card { border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-thumb,8px); background:var(--mf-surface,#16213e); margin-bottom:0.75rem; overflow:hidden; }',
      '.mf-ll__ns-head { display:flex; align-items:center; gap:0.6rem; padding:0.6rem 1rem; background:var(--mf-surface-soft,#1a1a2e); cursor:pointer; user-select:none; }',
      '.mf-ll__ns-name { font-size:0.9rem; font-weight:600; color:var(--mf-color-text,#e2e8f0); font-family:ui-monospace,monospace; flex:1; }',
      '.mf-ll__ns-count { font-size:0.78rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-ll__ns-chevron { font-size:0.75rem; color:var(--mf-color-text-muted,#8892a4); transition:transform .15s; }',
      '.mf-ll__ns-card--open .mf-ll__ns-chevron { transform:rotate(90deg); }',
      '.mf-ll__ns-body { display:none; }',
      '.mf-ll__ns-card--open .mf-ll__ns-body { display:block; }',
      '.mf-ll__table { width:100%; border-collapse:collapse; font-size:0.86rem; }',
      '.mf-ll__table th { padding:0.4rem 1rem; text-align:left; font-size:0.73rem; color:var(--mf-color-text-muted,#8892a4); text-transform:uppercase; letter-spacing:0.03em; font-weight:600; border-bottom:1px solid var(--mf-border,#2a2a4a); }',
      '.mf-ll__table td { padding:0.4rem 1rem; border-bottom:1px solid rgba(42,42,74,.5); vertical-align:middle; }',
      '.mf-ll__logger-name { font-family:ui-monospace,monospace; font-size:0.84rem; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-ll__eff-level { font-size:0.8rem; font-family:ui-monospace,monospace; font-weight:600; }',
      '.mf-ll__level-sel { padding:0.25rem 0.45rem; background:var(--mf-surface-soft,#1a1a2e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.84rem; cursor:pointer; }',
      '.mf-ll__save-row { display:inline-flex; align-items:center; gap:0.5rem; }',
      '.mf-ll__saved-badge { font-size:0.78rem; color:var(--mf-color-success,#22c55e); opacity:0; transition:opacity .2s; }',
      '.mf-ll__err-badge { font-size:0.78rem; color:#f87171; opacity:0; transition:opacity .2s; }',
      '.mf-ll__info-box { padding:0.75rem 1rem; background:rgba(99,102,241,.08); border:1px solid rgba(99,102,241,.2); border-radius:var(--mf-radius-sm,4px); font-size:0.84rem; color:var(--mf-color-text-muted,#8892a4); margin-bottom:1rem; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  function el(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }
  function clearEl(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function levelColor(name) { return LEVEL_COLORS[name] || '#e2e8f0'; }

  // ── Mount ────────────────────────────────────────────────────────────────

  function mount(slot, opts) {
    if (!slot) throw new Error('MFLogLevels.mount: slot is required');
    injectCss();
    clearEl(slot);
    opts = opts || {};

    var loggers = opts.loggers || [];

    var wrap = el('div', 'mf-ll');

    // ── Head ─────────────────────────────────────────────────────────
    var head = el('div', 'mf-ll__head');
    var h1 = el('h1'); h1.textContent = 'Per-Subsystem Log Levels';
    var desc = el('p');
    desc.textContent = 'Set the Python logging level for each registered logger. Changes take effect immediately (in-memory; reverts on container restart). DEBUG adds significant noise — use only when diagnosing an issue.';
    head.appendChild(h1); head.appendChild(desc);
    wrap.appendChild(head);

    // ── Info box ─────────────────────────────────────────────────────
    var infoBox = el('div', 'mf-ll__info-box');
    infoBox.textContent = 'Levels are in-memory only. NOTSET means the logger inherits from its parent. The effective level (shown in parentheses) accounts for inheritance.';
    wrap.appendChild(infoBox);

    // ── Top bar: search + refresh + reset ────────────────────────────
    var topbar = el('div', 'mf-ll__topbar');
    var searchInp = el('input', 'mf-ll__search');
    searchInp.type = 'text'; searchInp.placeholder = 'Filter loggers…';

    var refreshBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    refreshBtn.type = 'button'; refreshBtn.textContent = 'Refresh';

    var resetBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm');
    resetBtn.type = 'button'; resetBtn.textContent = 'Reset All to NOTSET';
    resetBtn.title = 'Sets every logger level to NOTSET (revert to inherited / default). Does not restart the container.';

    topbar.appendChild(searchInp); topbar.appendChild(refreshBtn); topbar.appendChild(resetBtn);
    wrap.appendChild(topbar);

    // ── Content area ─────────────────────────────────────────────────
    var contentArea = el('div');
    wrap.appendChild(contentArea);
    slot.appendChild(wrap);

    // ── Group loggers by namespace ────────────────────────────────────
    function groupLoggers(list) {
      var groups = {};
      var order = [];
      list.forEach(function (lgr) {
        var ns = lgr.namespace || 'other';
        if (!groups[ns]) { groups[ns] = []; order.push(ns); }
        groups[ns].push(lgr);
      });
      // Sort: known namespaces first (in KNOWN_NAMESPACES order), then alpha
      order.sort(function (a, b) {
        var ia = KNOWN_NAMESPACES.indexOf(a);
        var ib = KNOWN_NAMESPACES.indexOf(b);
        if (ia >= 0 && ib >= 0) return ia - ib;
        if (ia >= 0) return -1;
        if (ib >= 0) return 1;
        return a.localeCompare(b);
      });
      return { groups: groups, order: order };
    }

    var allLoggers = loggers.slice();
    var filterVal = '';

    function setLevel(loggerName, level, onDone) {
      fetch('/api/log-levels', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ logger: loggerName, level: level }),
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) { if (onDone) onDone(null, data); })
        .catch(function (e) { if (onDone) onDone(e); });
    }

    function renderRow(lgr) {
      var tr = el('tr');

      var nameTd = el('td', 'mf-ll__logger-name');
      nameTd.textContent = lgr.name;
      tr.appendChild(nameTd);

      var effTd = el('td');
      var effSpan = el('span', 'mf-ll__eff-level');
      effSpan.textContent = lgr.effective_level;
      effSpan.style.color = levelColor(lgr.effective_level);
      effTd.appendChild(effSpan);
      tr.appendChild(effTd);

      var selTd = el('td');
      var saveRow = el('div', 'mf-ll__save-row');
      var sel = el('select', 'mf-ll__level-sel');
      LEVELS.forEach(function (lv) {
        var opt = el('option'); opt.value = lv; opt.textContent = lv;
        if (lv === lgr.own_level) opt.selected = true;
        sel.appendChild(opt);
      });
      var savedBadge = el('span', 'mf-ll__saved-badge'); savedBadge.textContent = 'Saved';
      var errBadge = el('span', 'mf-ll__err-badge'); errBadge.textContent = 'Error';
      saveRow.appendChild(sel); saveRow.appendChild(savedBadge); saveRow.appendChild(errBadge);
      selTd.appendChild(saveRow);
      tr.appendChild(selTd);

      sel.addEventListener('change', function () {
        setLevel(lgr.name, sel.value, function (err, data) {
          if (err) {
            errBadge.style.opacity = '1';
            setTimeout(function () { errBadge.style.opacity = '0'; }, 2500);
          } else {
            lgr.own_level = data.own_level;
            lgr.effective_level = data.effective_level;
            effSpan.textContent = data.effective_level;
            effSpan.style.color = levelColor(data.effective_level);
            savedBadge.style.opacity = '1';
            setTimeout(function () { savedBadge.style.opacity = '0'; }, 1800);
          }
        });
      });

      return tr;
    }

    function renderContent() {
      clearEl(contentArea);
      var q = filterVal.toLowerCase().trim();
      var filtered = q
        ? allLoggers.filter(function (l) { return l.name.toLowerCase().indexOf(q) !== -1; })
        : allLoggers;

      if (filtered.length === 0) {
        var empty = el('p'); empty.style.cssText = 'color:var(--mf-color-text-muted,#8892a4);padding:1rem 0';
        empty.textContent = q ? 'No loggers match "' + q + '".' : 'No loggers found.';
        contentArea.appendChild(empty); return;
      }

      var grouped = groupLoggers(filtered);

      grouped.order.forEach(function (ns) {
        var nsList = grouped.groups[ns];
        var card = el('div', 'mf-ll__ns-card mf-ll__ns-card--open');

        var nsHead = el('div', 'mf-ll__ns-head');
        var chevron = el('span', 'mf-ll__ns-chevron'); chevron.textContent = '▶';
        var nsName = el('span', 'mf-ll__ns-name'); nsName.textContent = ns;
        var nsCount = el('span', 'mf-ll__ns-count'); nsCount.textContent = nsList.length + ' logger' + (nsList.length !== 1 ? 's' : '');
        nsHead.appendChild(chevron); nsHead.appendChild(nsName); nsHead.appendChild(nsCount);
        card.appendChild(nsHead);

        var nsBody = el('div', 'mf-ll__ns-body');
        var table = el('table', 'mf-ll__table');
        var thead = el('thead'); var hrow = el('tr');
        ['Logger', 'Effective level', 'Set level'].forEach(function (txt, i) {
          var th = el('th'); th.textContent = txt;
          if (i === 0) th.style.width = '45%';
          hrow.appendChild(th);
        });
        thead.appendChild(hrow); table.appendChild(thead);
        var tbody = el('tbody');
        nsList.forEach(function (lgr) { tbody.appendChild(renderRow(lgr)); });
        table.appendChild(tbody);
        nsBody.appendChild(table);
        card.appendChild(nsBody);
        contentArea.appendChild(card);

        nsHead.addEventListener('click', function () {
          card.classList.toggle('mf-ll__ns-card--open');
        });
      });
    }

    searchInp.addEventListener('input', function () {
      filterVal = searchInp.value;
      renderContent();
    });

    refreshBtn.addEventListener('click', function () {
      refreshBtn.disabled = true;
      fetch('/api/log-levels', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (data) {
          allLoggers = data.loggers || [];
          renderContent();
        })
        .catch(function (e) { console.warn('mf: log-levels refresh failed', e); })
        .finally(function () { refreshBtn.disabled = false; });
    });

    resetBtn.addEventListener('click', function () {
      if (!confirm('Set ALL loggers to NOTSET (inherit from parent)? This reverts any custom levels set this session.')) return;
      resetBtn.disabled = true;
      var queue = allLoggers.map(function (l) { return l.name; });
      var done = 0;
      function next() {
        if (done >= queue.length) {
          refreshBtn.click();
          resetBtn.disabled = false;
          return;
        }
        var name = queue[done++];
        setLevel(name, 'NOTSET', function () { next(); });
      }
      next();
    });

    renderContent();
  }

  global.MFLogLevels = { mount: mount };
})(window);
