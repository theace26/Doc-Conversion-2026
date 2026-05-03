/* MFLogViewer — new-UX live log tail + history search.
 *
 * Usage:
 *   MFLogViewer.mount(slot)
 *
 * Endpoints used (same as original log-viewer.html):
 *   GET /api/logs                — file inventory
 *   GET /api/logs/tail/{name}    — SSE live tail
 *   GET /api/logs/search         — history search with filters
 *   GET /api/logs/eta            — search ETA estimate (optional)
 *
 * Features:
 *   - Multi-tab: each tab owns its own EventSource / history offset
 *   - Mode selector: Live tail | Search history
 *   - Level chips: DEBUG / INFO / WARNING / ERROR
 *   - Search input with optional regex
 *   - Time-range pickers + presets for history mode
 *   - Pause / Resume for live tail
 *   - Clear button
 *   - DOM cap: 2000 lines per tab (oldest removed from head)
 *   - Tab state persisted to localStorage
 *
 * Admin-only page (boot script guards).
 * Safe DOM throughout — no innerHTML for chrome.
 */
(function (global) {
  'use strict';

  var TAB_BODY_LINE_CAP = 2000;
  var HISTORY_LIMIT = 200;
  var STORAGE_KEY = 'mf.logviewer.tabs.v2';

  // ── CSS (injected once) ────────────────────────────────────────────────────
  var _cssInjected = false;
  function injectCss() {
    if (_cssInjected) return;
    _cssInjected = true;
    var style = document.createElement('style');
    style.textContent = [
      '.mf-lv { display:flex; flex-direction:column; height:calc(100vh - var(--mf-nav-height, 56px)); }',
      '.mf-lv__tabs { flex:0 0 auto; display:flex; align-items:center; gap:0.25rem; padding:0.4rem 0.75rem; background:var(--mf-surface-soft,#1a1a2e); border-bottom:1px solid var(--mf-border,#2a2a4a); overflow-x:auto; }',
      '.mf-lv__tab { display:inline-flex; align-items:center; gap:0.4rem; padding:0.3rem 0.65rem; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font-size:0.82rem; cursor:pointer; user-select:none; white-space:nowrap; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lv__tab--active { border-color:var(--mf-color-accent,#6366f1); background:rgba(99,102,241,0.12); }',
      '.mf-lv__tab-dot { width:0.55rem; height:0.55rem; border-radius:50%; background:#6b7280; flex-shrink:0; }',
      '.mf-lv__tab-dot--connected { background:#22c55e; }',
      '.mf-lv__tab-dot--disconnected { background:#ef4444; }',
      '.mf-lv__tab-close { background:none; border:none; color:var(--mf-color-text-muted,#8892a4); font-size:1rem; cursor:pointer; padding:0 0.1rem; line-height:1; }',
      '.mf-lv__tab-close:hover { color:#fca5a5; }',
      '.mf-lv__add-btn { background:none; border:1px dashed var(--mf-border,#2a2a4a); color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-lv__controls { flex:0 0 auto; display:flex; flex-wrap:wrap; align-items:center; gap:0.5rem; padding:0.6rem 0.75rem; background:var(--mf-surface-soft,#1a1a2e); border-bottom:1px solid var(--mf-border,#2a2a4a); }',
      '.mf-lv__controls label { font-size:0.82rem; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-lv__controls select, .mf-lv__controls input[type="text"] { padding:0.25rem 0.5rem; background:var(--mf-surface,#16213e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.85rem; }',
      '.mf-lv__controls input[type="text"] { min-width:200px; }',
      '.mf-lv__controls input[type="datetime-local"] { padding:0.25rem 0.5rem; background:var(--mf-surface,#16213e); color:var(--mf-color-text,#e2e8f0); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); font:inherit; font-size:0.85rem; color-scheme:dark; }',
      '.mf-lv__chip { display:inline-flex; align-items:center; gap:0.3rem; padding:0.2rem 0.55rem; border-radius:999px; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); font-size:0.8rem; cursor:pointer; user-select:none; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lv__chip input { margin:0; cursor:pointer; }',
      '.mf-lv__preset { background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); color:var(--mf-color-text-muted,#8892a4); font-size:0.8rem; cursor:pointer; border-radius:999px; padding:0.2rem 0.6rem; }',
      '.mf-lv__preset:hover { background:rgba(255,255,255,0.06); }',
      '.mf-lv__spacer { flex:1; }',
      '.mf-lv__status { font-size:0.78rem; color:var(--mf-color-text-muted,#8892a4); font-family:ui-monospace,monospace; }',
      '.mf-lv__time-row { flex:0 0 auto; display:none; flex-wrap:wrap; align-items:center; gap:0.5rem; padding:0.5rem 0.75rem; background:var(--mf-surface-soft,#1a1a2e); border-bottom:1px solid var(--mf-border,#2a2a4a); }',
      '.mf-lv__time-row--active { display:flex; }',
      '.mf-lv__bodies { flex:1; position:relative; overflow:hidden; }',
      '.mf-lv__body { position:absolute; inset:0; overflow:auto; background:#0b0b14; padding:0.5rem 0; font-family:ui-monospace,monospace; font-size:0.82rem; display:none; }',
      '.mf-lv__body--active { display:block; }',
      '.mf-lv__line { padding:0.15rem 1rem; white-space:pre-wrap; word-break:break-word; border-left:3px solid transparent; }',
      '.mf-lv__line:hover { background:rgba(255,255,255,0.04); }',
      '.mf-lv__line--DEBUG { color:#9ca3af; }',
      '.mf-lv__line--INFO { color:#e2e8f0; }',
      '.mf-lv__line--WARNING { color:#fcd34d; border-left-color:rgba(217,119,6,.5); }',
      '.mf-lv__line--ERROR { color:#fca5a5; border-left-color:rgba(220,38,38,.5); }',
      '.mf-lv__line--CRITICAL { color:#fecaca; background:rgba(220,38,38,.08); border-left-color:rgba(220,38,38,.8); }',
      '.mf-lv__line--hidden { display:none; }',
      '.mf-lv__ts { color:#7dd3fc; margin-right:0.75rem; }',
      '.mf-lv__lvl { display:inline-block; min-width:5rem; font-weight:600; margin-right:0.5rem; }',
      '.mf-lv__logger { color:#c4b5fd; margin-right:0.75rem; }',
      '.mf-lv__kv { color:#86efac; margin-left:0.5rem; }',
      '.mf-lv__empty { padding:2rem; text-align:center; color:var(--mf-color-text-muted,#8892a4); }',
      '.mf-lv__add-menu { position:fixed; z-index:50; background:var(--mf-surface,#16213e); border:1px solid var(--mf-border,#2a2a4a); border-radius:var(--mf-radius-sm,4px); max-height:60vh; overflow:auto; padding:0.3rem; min-width:280px; box-shadow:0 6px 20px rgba(0,0,0,.4); }',
      '.mf-lv__add-item { padding:0.35rem 0.6rem; cursor:pointer; border-radius:3px; font-size:0.82rem; color:var(--mf-color-text,#e2e8f0); }',
      '.mf-lv__add-item:hover { background:rgba(99,102,241,.12); }',
      '.mf-lv__add-item--disabled { opacity:.5; cursor:default; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function clearEl(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function safeRegex(q) {
    try { return new RegExp(q, 'i'); } catch (e) { return null; }
  }

  function localInputToUtcIso(value) {
    if (!value) return null;
    try {
      var d = new Date(value);
      return isNaN(d.getTime()) ? null : d.toISOString();
    } catch (e) { return null; }
  }

  function dateToLocalInput(d) {
    var pad = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function clientMatches(parsed, raw, levels, qRegex, qLower) {
    if (parsed && parsed.level) {
      if (!levels.has(String(parsed.level).toUpperCase())) return false;
    }
    if (qRegex) return qRegex.test(raw);
    if (qLower) return raw.toLowerCase().indexOf(qLower) !== -1;
    return true;
  }

  function renderLineEl(raw) {
    var div = el('div', 'mf-lv__line');
    var parsed = null;
    try {
      var obj = JSON.parse(raw);
      if (obj && typeof obj === 'object') parsed = obj;
    } catch (e) { /* not JSON */ }

    if (parsed) {
      var lvl = String(parsed.level || '').toUpperCase();
      if (lvl) div.classList.add('mf-lv__line--' + lvl);

      var ts = el('span', 'mf-lv__ts');
      ts.textContent = parsed.timestamp || parsed.ts || '';
      div.appendChild(ts);

      var lv = el('span', 'mf-lv__lvl');
      lv.textContent = lvl;
      div.appendChild(lv);

      if (parsed.logger) {
        var lg = el('span', 'mf-lv__logger');
        lg.textContent = parsed.logger;
        div.appendChild(lg);
      }

      var msg = el('span', 'mf-lv__msg');
      msg.textContent = parsed.event || parsed.msg || parsed.message || '';
      div.appendChild(msg);

      var known = new Set(['level', 'timestamp', 'ts', 'logger', 'event', 'msg', 'message']);
      var parts = [];
      for (var k in parsed) {
        if (known.has(k)) continue;
        var v = parsed[k];
        if (v === null || v === undefined) continue;
        parts.push(k + '=' + (typeof v === 'object' ? JSON.stringify(v) : v));
      }
      if (parts.length) {
        var kv = el('span', 'mf-lv__kv');
        kv.textContent = ' ' + parts.join(' ');
        div.appendChild(kv);
      }
    } else {
      div.textContent = raw;
    }
    div.dataset.raw = raw;
    div.dataset.parsed = parsed ? JSON.stringify(parsed) : '';
    return div;
  }

  // ── LogTab class ──────────────────────────────────────────────────────────

  function LogTab(name, bodiesEl) {
    this.name = name;
    this.mode = 'live';
    this.paused = false;
    this.evtSource = null;
    this.connected = false;
    this.totalLines = 0;
    this.filteredLines = 0;
    this.historyOffset = 0;
    this.q = '';
    this.regex = false;
    this.levels = new Set(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']);
    this.fromLocal = '';
    this.toLocal = '';
    this.fromIso = null;
    this.toIso = null;

    this.bodyEl = el('div', 'mf-lv__body');
    bodiesEl.appendChild(this.bodyEl);

    this.tabEl = el('div', 'mf-lv__tab');
    this.tabEl.title = name;
    this.dotEl = el('span', 'mf-lv__tab-dot');
    var labelEl = el('span');
    labelEl.textContent = name;
    this.closeEl = el('button', 'mf-lv__tab-close');
    this.closeEl.type = 'button';
    this.closeEl.textContent = '×';
    this.closeEl.setAttribute('aria-label', 'Close tab');
    this.tabEl.appendChild(this.dotEl);
    this.tabEl.appendChild(labelEl);
    this.tabEl.appendChild(this.closeEl);
  }

  LogTab.prototype.setConnectionState = function (state) {
    this.connected = (state === 'connected');
    this.dotEl.classList.toggle('mf-lv__tab-dot--connected', state === 'connected');
    this.dotEl.classList.toggle('mf-lv__tab-dot--disconnected', state === 'disconnected');
  };

  LogTab.prototype.appendLine = function (raw, levels, qRegex, qLower, autoScroll) {
    var lineEl = renderLineEl(raw);
    this.bodyEl.appendChild(lineEl);
    this.totalLines++;
    var parsed = null;
    try { if (lineEl.dataset.parsed) parsed = JSON.parse(lineEl.dataset.parsed); } catch (e) { /* */ }
    var match = clientMatches(parsed, raw, levels || this.levels, qRegex || null, qLower || '');
    lineEl.classList.toggle('mf-lv__line--hidden', !match);
    if (match) this.filteredLines++;
    while (this.bodyEl.childElementCount > TAB_BODY_LINE_CAP) {
      var head = this.bodyEl.firstElementChild;
      if (!head) break;
      if (!head.classList.contains('mf-lv__line--hidden')) this.filteredLines--;
      this.totalLines--;
      this.bodyEl.removeChild(head);
    }
    if (autoScroll && !this.paused) {
      this.bodyEl.scrollTop = this.bodyEl.scrollHeight;
    }
  };

  LogTab.prototype.clearBody = function () {
    clearEl(this.bodyEl);
    this.totalLines = 0;
    this.filteredLines = 0;
  };

  LogTab.prototype.applyClientFilter = function () {
    var qRegex = (this.q && this.regex) ? safeRegex(this.q) : null;
    var qLower = (this.q && !this.regex) ? this.q.toLowerCase() : '';
    var shown = 0;
    this.bodyEl.querySelectorAll('.mf-lv__line').forEach(function (n) {
      var parsed = null;
      try { if (n.dataset.parsed) parsed = JSON.parse(n.dataset.parsed); } catch (e) { /* */ }
      var match = clientMatches(parsed, n.dataset.raw || n.textContent, this.levels, qRegex, qLower);
      n.classList.toggle('mf-lv__line--hidden', !match);
      if (match) shown++;
    }.bind(this));
    this.filteredLines = shown;
  };

  LogTab.prototype.startLiveTail = function (onStatus) {
    this.closeSse();
    this.clearBody();
    this.historyOffset = 0;
    var url = '/api/logs/tail/' + encodeURIComponent(this.name);
    this.evtSource = new EventSource(url, { withCredentials: true });
    this.setConnectionState('connecting');
    this.evtSource.onopen = function () { this.setConnectionState('connected'); if (onStatus) onStatus(); }.bind(this);
    this.evtSource.onmessage = function (ev) {
      if (this.paused) return;
      var qRegex = (this.q && this.regex) ? safeRegex(this.q) : null;
      var qLower = (this.q && !this.regex) ? this.q.toLowerCase() : '';
      this.appendLine(ev.data, this.levels, qRegex, qLower, true);
      if (onStatus) onStatus();
    }.bind(this);
    this.evtSource.onerror = function () {
      this.setConnectionState('disconnected');
      var msgEl = el('div', 'mf-lv__empty');
      msgEl.textContent = 'Tail stream disconnected. Switch back to this tab to reconnect.';
      this.bodyEl.appendChild(msgEl);
      this.closeSse();
      if (onStatus) onStatus();
    }.bind(this);
  };

  LogTab.prototype.runHistorySearch = function (resetOffset, onStatus, onLoadMore) {
    this.closeSse();
    this.setConnectionState('disconnected');
    if (resetOffset) { this.clearBody(); this.historyOffset = 0; }
    var params = new URLSearchParams();
    params.set('name', this.name);
    if (this.q) params.set('q', this.q);
    if (this.regex) params.set('regex', 'true');
    var levelsCsv = Array.from(this.levels).join(',');
    if (levelsCsv) params.set('levels', levelsCsv);
    if (this.fromIso) params.set('from_iso', this.fromIso);
    if (this.toIso) params.set('to_iso', this.toIso);
    params.set('limit', String(HISTORY_LIMIT));
    params.set('offset', String(this.historyOffset));
    if (onStatus) onStatus('Searching ' + this.name + '…');
    fetch('/api/logs/search?' + params.toString(), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var lines = data.lines || [];
        if (lines.length === 0 && this.historyOffset === 0) {
          var empty = el('div', 'mf-lv__empty');
          empty.textContent = 'No matches.';
          this.bodyEl.appendChild(empty);
        }
        lines.forEach(function (e) { this.appendLine(e.raw, this.levels, null, '', false); }.bind(this));
        if (lines.length >= HISTORY_LIMIT) {
          this.historyOffset += lines.length;
          if (onLoadMore) onLoadMore(true);
        } else {
          if (onLoadMore) onLoadMore(false);
        }
        var parts = [(data.returned || 0) + ' returned', 'scanned ' + (data.scanned_lines || 0)];
        if (data.scan_truncated) parts.push('line cap hit');
        if (data.wall_truncated) parts.push('time cap hit');
        if (typeof data.wall_seconds === 'number') parts.push(data.wall_seconds + 's');
        if (onStatus) onStatus(parts.join(' · '));
      }.bind(this))
      .catch(function (e) {
        if (onStatus) onStatus('Search error: ' + e);
      });
  };

  LogTab.prototype.closeSse = function () {
    if (this.evtSource) { this.evtSource.close(); this.evtSource = null; }
  };

  LogTab.prototype.start = function (onStatus, onLoadMore) {
    if (this.mode === 'live') this.startLiveTail(onStatus);
    else this.runHistorySearch(true, onStatus, onLoadMore);
  };

  // ── Mount ─────────────────────────────────────────────────────────────────

  function mount(slot) {
    if (!slot) throw new Error('MFLogViewer.mount: slot is required');
    injectCss();
    clearEl(slot);

    var wrap = el('div', 'mf-lv');
    var tabsBar = el('div', 'mf-lv__tabs');
    var controlsRow = el('div', 'mf-lv__controls');
    var timeRow = el('div', 'mf-lv__time-row');
    var bodiesEl = el('div', 'mf-lv__bodies');
    wrap.appendChild(tabsBar);
    wrap.appendChild(controlsRow);
    wrap.appendChild(timeRow);
    wrap.appendChild(bodiesEl);
    slot.appendChild(wrap);

    // ── Controls ────────────────────────────────────────────────────
    var modeLabel = el('label');
    modeLabel.textContent = 'Mode';
    var modeSel = el('select');
    var optLive = el('option'); optLive.value = 'live'; optLive.textContent = 'Live tail';
    var optHist = el('option'); optHist.value = 'history'; optHist.textContent = 'Search history';
    modeSel.appendChild(optLive);
    modeSel.appendChild(optHist);

    var cbAutoScroll = document.createElement('input'); cbAutoScroll.type = 'checkbox'; cbAutoScroll.checked = true;
    var autoScrollChip = el('label', 'mf-lv__chip'); autoScrollChip.appendChild(cbAutoScroll); autoScrollChip.appendChild(document.createTextNode(' Auto-scroll'));

    var cbDebug = document.createElement('input'); cbDebug.type = 'checkbox'; cbDebug.checked = true;
    var chipDebug = el('label', 'mf-lv__chip'); chipDebug.appendChild(cbDebug); chipDebug.appendChild(document.createTextNode(' DEBUG'));

    var cbInfo = document.createElement('input'); cbInfo.type = 'checkbox'; cbInfo.checked = true;
    var chipInfo = el('label', 'mf-lv__chip'); chipInfo.appendChild(cbInfo); chipInfo.appendChild(document.createTextNode(' INFO'));

    var cbWarn = document.createElement('input'); cbWarn.type = 'checkbox'; cbWarn.checked = true;
    var chipWarn = el('label', 'mf-lv__chip'); chipWarn.appendChild(cbWarn); chipWarn.appendChild(document.createTextNode(' WARNING'));

    var cbErr = document.createElement('input'); cbErr.type = 'checkbox'; cbErr.checked = true;
    var chipErr = el('label', 'mf-lv__chip'); chipErr.appendChild(cbErr); chipErr.appendChild(document.createTextNode(' ERROR'));

    var searchLabel = el('label'); searchLabel.textContent = 'Search';
    var searchInp = el('input'); searchInp.type = 'text'; searchInp.placeholder = 'substring or regex';

    var cbRegex = document.createElement('input'); cbRegex.type = 'checkbox';
    var chipRegex = el('label', 'mf-lv__chip'); chipRegex.appendChild(cbRegex); chipRegex.appendChild(document.createTextNode(' Regex'));

    var applyBtn = el('button', 'mf-pill mf-pill--primary mf-pill--sm'); applyBtn.type = 'button'; applyBtn.textContent = 'Apply';
    var clearBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm'); clearBtn.type = 'button'; clearBtn.textContent = 'Clear';
    var pauseBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm'); pauseBtn.type = 'button'; pauseBtn.textContent = 'Pause';
    var loadMoreBtn = el('button', 'mf-pill mf-pill--ghost mf-pill--sm'); loadMoreBtn.type = 'button'; loadMoreBtn.textContent = 'Load older'; loadMoreBtn.hidden = true;

    var spacer = el('span', 'mf-lv__spacer');
    var statusEl = el('span', 'mf-lv__status'); statusEl.textContent = '-';

    [modeLabel, modeSel, autoScrollChip, chipDebug, chipInfo, chipWarn, chipErr,
     searchLabel, searchInp, chipRegex, applyBtn, clearBtn, pauseBtn, loadMoreBtn,
     spacer, statusEl].forEach(function (n) { controlsRow.appendChild(n); });

    // ── Time row ────────────────────────────────────────────────────
    var fromLabel = el('label'); fromLabel.textContent = 'From';
    var fromInp = el('input'); fromInp.type = 'datetime-local';
    var toLabel = el('label'); toLabel.textContent = 'To';
    var toInp = el('input'); toInp.type = 'datetime-local';

    function makePreset(label, preset) {
      var btn = el('button', 'mf-lv__preset'); btn.type = 'button'; btn.textContent = label;
      btn.addEventListener('click', function () { applyPreset(preset); });
      return btn;
    }
    [fromLabel, fromInp, toLabel, toInp,
     makePreset('Last hour', '1h'), makePreset('Last 24h', '24h'),
     makePreset('Last 7d', '7d'), makePreset('Clear range', 'clear')
    ].forEach(function (n) { timeRow.appendChild(n); });

    // ── State ────────────────────────────────────────────────────────
    var availableLogs = [];
    var tabs = [];
    var activeTab = null;

    function updateStatus(msg) {
      if (msg !== undefined) { statusEl.textContent = msg; return; }
      if (!activeTab) { statusEl.textContent = '-'; return; }
      var parts = [activeTab.totalLines + ' lines'];
      if (activeTab.filteredLines !== activeTab.totalLines) parts.push(activeTab.filteredLines + ' visible');
      parts.push(activeTab.mode === 'live' ? (activeTab.paused ? 'paused' : 'live') : 'history');
      statusEl.textContent = parts.join(' · ');
    }

    function syncControlsFromTab(t) {
      modeSel.value = t.mode;
      cbDebug.checked = t.levels.has('DEBUG');
      cbInfo.checked = t.levels.has('INFO');
      cbWarn.checked = t.levels.has('WARNING');
      cbErr.checked = t.levels.has('ERROR') || t.levels.has('CRITICAL');
      searchInp.value = t.q || '';
      cbRegex.checked = !!t.regex;
      fromInp.value = t.fromLocal || '';
      toInp.value = t.toLocal || '';
      pauseBtn.textContent = t.paused ? 'Resume' : 'Pause';
      timeRow.classList.toggle('mf-lv__time-row--active', t.mode === 'history');
      updateStatus();
    }

    function activateTab(t) {
      if (activeTab) {
        activeTab.tabEl.classList.remove('mf-lv__tab--active');
        activeTab.bodyEl.classList.remove('mf-lv__body--active');
      }
      activeTab = t;
      if (!t) { updateStatus(); return; }
      t.tabEl.classList.add('mf-lv__tab--active');
      t.bodyEl.classList.add('mf-lv__body--active');
      syncControlsFromTab(t);
      if (t.mode === 'live' && !t.evtSource) t.startLiveTail(updateStatus);
    }

    function readControlsIntoTab(t) {
      t.mode = modeSel.value;
      t.levels = new Set();
      if (cbDebug.checked) t.levels.add('DEBUG');
      if (cbInfo.checked) t.levels.add('INFO');
      if (cbWarn.checked) t.levels.add('WARNING');
      if (cbErr.checked) { t.levels.add('ERROR'); t.levels.add('CRITICAL'); }
      t.q = searchInp.value || '';
      t.regex = cbRegex.checked;
      t.fromLocal = fromInp.value || '';
      t.toLocal = toInp.value || '';
      t.fromIso = localInputToUtcIso(t.fromLocal);
      t.toIso = localInputToUtcIso(t.toLocal);
    }

    function applyPreset(preset) {
      if (preset === 'clear') { fromInp.value = ''; toInp.value = ''; return; }
      var now = new Date();
      var ms = preset === '1h' ? 3600000 : preset === '24h' ? 86400000 : 7 * 86400000;
      fromInp.value = dateToLocalInput(new Date(now - ms));
      toInp.value = dateToLocalInput(now);
    }

    function persistTabs() {
      try {
        var payload = tabs.map(function (t) {
          return { name: t.name, mode: t.mode, q: t.q, regex: t.regex,
                   levels: Array.from(t.levels), fromLocal: t.fromLocal, toLocal: t.toLocal };
        });
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          tabs: payload,
          activeName: activeTab ? activeTab.name : null,
        }));
      } catch (e) { /* ignore */ }
    }

    function closeTab(t) {
      t.closeSse();
      var idx = tabs.indexOf(t);
      if (idx >= 0) tabs.splice(idx, 1);
      if (t.tabEl.parentNode) t.tabEl.parentNode.removeChild(t.tabEl);
      if (t.bodyEl.parentNode) t.bodyEl.parentNode.removeChild(t.bodyEl);
      if (activeTab === t) {
        activeTab = null;
        if (tabs.length > 0) activateTab(tabs[Math.min(idx, tabs.length - 1)]);
        else updateStatus();
      }
      persistTabs();
    }

    function addTab(name, opts) {
      var existing = tabs.find(function (t) { return t.name === name; });
      if (existing) { activateTab(existing); return existing; }
      var t = new LogTab(name, bodiesEl);
      var lower = name.toLowerCase();
      var isCompressed = lower.endsWith('.gz') || lower.endsWith('.tgz') || lower.endsWith('.7z');
      if (isCompressed) t.mode = 'history';
      if (opts) {
        if (opts.mode && !isCompressed) t.mode = opts.mode;
        if (typeof opts.q === 'string') t.q = opts.q;
        if (typeof opts.regex === 'boolean') t.regex = opts.regex;
        if (Array.isArray(opts.levels) && opts.levels.length) t.levels = new Set(opts.levels);
        if (opts.fromLocal) { t.fromLocal = opts.fromLocal; t.fromIso = localInputToUtcIso(opts.fromLocal); }
        if (opts.toLocal) { t.toLocal = opts.toLocal; t.toIso = localInputToUtcIso(opts.toLocal); }
      }
      tabs.push(t);
      tabsBar.insertBefore(t.tabEl, addTabBtn);
      t.closeEl.addEventListener('click', function (ev) { ev.stopPropagation(); closeTab(t); });
      t.tabEl.addEventListener('click', function () { activateTab(t); });
      activateTab(t);
      t.start(updateStatus, function (more) { loadMoreBtn.hidden = !more; });
      persistTabs();
      return t;
    }

    // ── Add-tab button ──────────────────────────────────────────────
    var addTabBtn = el('button', 'mf-lv__tab mf-lv__add-btn');
    addTabBtn.type = 'button';
    addTabBtn.textContent = '+ Add tab';
    tabsBar.appendChild(addTabBtn);
    var addMenu = null;

    function closeAddMenu() {
      if (addMenu && addMenu.parentNode) addMenu.parentNode.removeChild(addMenu);
      addMenu = null;
    }

    addTabBtn.addEventListener('click', function () {
      if (addMenu) { closeAddMenu(); return; }
      addMenu = el('div', 'mf-lv__add-menu');
      if (availableLogs.length === 0) {
        var empty = el('div', 'mf-lv__add-item mf-lv__add-item--disabled');
        empty.textContent = 'No logs available';
        addMenu.appendChild(empty);
      } else {
        availableLogs.forEach(function (l) {
          var item = el('div', 'mf-lv__add-item');
          var sizeKb = Math.round((l.size_bytes || 0) / 1024);
          item.textContent = l.name + ' (' + sizeKb + ' KB, ' + l.status + ')';
          var isOpen = tabs.some(function (t) { return t.name === l.name; });
          if (isOpen) {
            item.classList.add('mf-lv__add-item--disabled');
            item.textContent += '  ✓';
          } else {
            item.addEventListener('click', function () { addTab(l.name); closeAddMenu(); });
          }
          addMenu.appendChild(item);
        });
      }
      var rect = addTabBtn.getBoundingClientRect();
      addMenu.style.top = (rect.bottom + 4) + 'px';
      addMenu.style.left = rect.left + 'px';
      document.body.appendChild(addMenu);
      setTimeout(function () {
        document.addEventListener('click', function once(ev) {
          if (addMenu && !addMenu.contains(ev.target) && ev.target !== addTabBtn) {
            closeAddMenu();
            document.removeEventListener('click', once);
          }
        });
      }, 0);
    });

    // ── Control bar wiring ───────────────────────────────────────────
    modeSel.addEventListener('change', function () {
      if (!activeTab) return;
      readControlsIntoTab(activeTab);
      timeRow.classList.toggle('mf-lv__time-row--active', activeTab.mode === 'history');
      activeTab.start(updateStatus, function (more) { loadMoreBtn.hidden = !more; });
      persistTabs();
    });

    applyBtn.addEventListener('click', function () {
      if (!activeTab) return;
      readControlsIntoTab(activeTab);
      if (activeTab.mode === 'history') {
        activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
      } else {
        activeTab.applyClientFilter();
        updateStatus();
      }
      persistTabs();
    });

    clearBtn.addEventListener('click', function () {
      if (!activeTab) return;
      searchInp.value = ''; cbRegex.checked = false;
      cbDebug.checked = cbInfo.checked = cbWarn.checked = cbErr.checked = true;
      fromInp.value = ''; toInp.value = '';
      readControlsIntoTab(activeTab);
      if (activeTab.mode === 'history') {
        activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
      } else {
        activeTab.applyClientFilter();
        updateStatus();
      }
      persistTabs();
    });

    pauseBtn.addEventListener('click', function () {
      if (!activeTab) return;
      activeTab.paused = !activeTab.paused;
      pauseBtn.textContent = activeTab.paused ? 'Resume' : 'Pause';
      updateStatus();
    });

    loadMoreBtn.addEventListener('click', function () {
      if (!activeTab) return;
      activeTab.runHistorySearch(false, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
    });

    [cbDebug, cbInfo, cbWarn, cbErr].forEach(function (cb) {
      cb.addEventListener('change', function () {
        if (!activeTab) return;
        readControlsIntoTab(activeTab);
        if (activeTab.mode === 'live') { activeTab.applyClientFilter(); updateStatus(); }
        else activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
        persistTabs();
      });
    });

    searchInp.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' || !activeTab) return;
      readControlsIntoTab(activeTab);
      if (activeTab.mode === 'history') {
        activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
      } else {
        activeTab.applyClientFilter();
        updateStatus();
      }
      persistTabs();
    });

    [fromInp, toInp].forEach(function (inp) {
      inp.addEventListener('change', function () {
        if (!activeTab) return;
        readControlsIntoTab(activeTab);
        if (activeTab.mode === 'history') {
          activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
        }
        persistTabs();
      });
    });

    window.addEventListener('beforeunload', function () {
      tabs.forEach(function (t) { t.closeSse(); });
    });

    // ── Bootstrap ────────────────────────────────────────────────────
    fetch('/api/logs', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        availableLogs = data.logs || [];
        var saved = null;
        try {
          var raw = localStorage.getItem(STORAGE_KEY);
          if (raw) { var d = JSON.parse(raw); if (d && Array.isArray(d.tabs)) saved = d; }
        } catch (e) { /* ignore */ }

        var params = new URLSearchParams(window.location.search);
        var initialFile = params.get('file') || '';
        var initialQuery = params.get('q') || '';
        var initialMode = params.get('mode') || '';

        if (saved && saved.tabs.length > 0) {
          var valid = saved.tabs.filter(function (tt) {
            return availableLogs.some(function (l) { return l.name === tt.name; });
          });
          valid.forEach(function (tt) { addTab(tt.name, tt); });
          if (saved.activeName) {
            var a = tabs.find(function (t) { return t.name === saved.activeName; });
            if (a) activateTab(a);
          }
        }

        if (initialFile && availableLogs.some(function (l) { return l.name === initialFile; })) {
          addTab(initialFile);
        }

        if (tabs.length === 0 && availableLogs.length > 0) {
          addTab(availableLogs[0].name);
        }

        if (initialQuery && activeTab) {
          activeTab.q = initialQuery;
          searchInp.value = initialQuery;
          if (initialMode === 'history') {
            activeTab.mode = 'history';
            modeSel.value = 'history';
            timeRow.classList.add('mf-lv__time-row--active');
            activeTab.runHistorySearch(true, updateStatus, function (more) { loadMoreBtn.hidden = !more; });
          }
        }
      })
      .catch(function (e) {
        var msgEl = el('div', 'mf-lv__empty');
        msgEl.textContent = 'Failed to load log list: ' + e;
        bodiesEl.appendChild(msgEl);
      });
  }

  global.MFLogViewer = { mount: mount };
})(window);
