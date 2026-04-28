/**
 * Pipeline card — shared module (v0.33.0).
 *
 * Renders MarkFlow's pipeline status as a self-contained card. Both
 * /static/status.html (rich version, primary surface) and
 * /static/bulk.html (compact version) mount this module on a
 * placeholder div instead of carrying their own copies of the markup
 * + polling JS.
 *
 * Public surface:
 *   const handle = mountPipelineCard(containerEl, opts);
 *   handle.refresh();   // force an immediate poll
 *   handle.destroy();   // tear down + stop polling (for SPA-style nav)
 *
 * Options:
 *   compact: boolean   — render the 1-2 line summary version (default: false)
 *   pollMs:  number    — polling cadence (default: 30000)
 *   showActions: boolean — render Pause / Rebuild Index / Run Now buttons
 *                          (default: true; set false for read-only mounts)
 *
 * Backend contract: GET /api/pipeline/status returns
 *   {
 *     pipeline_enabled, paused, auto_convert_mode,
 *     scanner_interval_minutes, is_scan_running, scheduler_running,
 *     next_scan, last_scan: {id, started_at, finished_at, status,
 *                            files_scanned, files_new, files_modified},
 *     total_source_files, pending_conversion,
 *     last_auto_conversion: {scan_run_id, mode, status, files_discovered,
 *                            workers_chosen, batch_size_chosen, reason},
 *     disabled_info
 *   }
 *
 * Security note: every value is bound via textContent / setAttribute,
 * never innerHTML / template-literal injection. Backend strings can
 * contain operator-supplied paths but are never rendered as HTML.
 */
(function (window) {
  'use strict';

  // Shared formatters --------------------------------------------------------

  function fmtNum(n) {
    return n == null ? '—' : Number(n).toLocaleString();
  }

  function fmtRel(d, now) {
    if (!d) return '';
    const ms = d.getTime() - now.getTime();
    const past = ms < 0;
    let sec = Math.abs(Math.round(ms / 1000));
    if (sec < 60) return past ? `${sec}s ago` : `in ${sec}s`;
    const min = Math.floor(sec / 60);
    sec = sec % 60;
    if (min < 60) return past ? `${min}m ${sec}s ago` : `in ${min}m ${sec}s`;
    const hr = Math.floor(min / 60);
    const m2 = min % 60;
    return past ? `${hr}h ${m2}m ago` : `in ${hr}h ${m2}m`;
  }

  // Use parseUTC if app.js has it; otherwise fall back to new Date().
  function parseTimestamp(iso) {
    if (!iso) return null;
    try {
      if (typeof window.parseUTC === 'function') return window.parseUTC(iso);
      return new Date(iso);
    } catch (e) { return null; }
  }

  // DOM helpers --------------------------------------------------------------

  function el(tag, opts, kids) {
    const node = document.createElement(tag);
    if (opts) {
      if (opts.text != null) node.textContent = String(opts.text);
      if (opts.cls) node.className = opts.cls;
      if (opts.id) node.id = opts.id;
      if (opts.title) node.title = opts.title;
      if (opts.href) node.href = opts.href;
      if (opts.style) node.style.cssText = opts.style;
      if (opts.attrs) {
        for (const k in opts.attrs) node.setAttribute(k, opts.attrs[k]);
      }
      if (opts.onClick) node.addEventListener('click', opts.onClick);
    }
    if (kids) {
      for (const k of kids) {
        if (k != null) node.appendChild(k);
      }
    }
    return node;
  }

  function clearChildren(n) {
    while (n.firstChild) n.removeChild(n.firstChild);
  }

  // API client ---------------------------------------------------------------

  async function fetchPipelineStatus() {
    const res = await fetch('/api/pipeline/status', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function postAction(url) {
    const res = await fetch(url, { method: 'POST', credentials: 'same-origin' });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status} ${detail.slice(0, 200)}`);
    }
    return res.json().catch(() => ({}));
  }

  // Status pill --------------------------------------------------------------

  function statusPillFromData(data) {
    if (!data.pipeline_enabled) {
      return { text: 'Disabled', cls: 'job-status cancelled' };
    }
    if (data.paused) {
      return { text: 'Paused', cls: 'job-status paused' };
    }
    if (data.is_scan_running) {
      return { text: 'Scanning', cls: 'job-status scanning' };
    }
    return { text: 'Active', cls: 'job-status completed' };
  }

  // Cell builders (rich mode) ------------------------------------------------

  function buildModeCell(data) {
    const modeLabels = { off: 'Off', immediate: 'Immediate', queued: 'Queued', scheduled: 'Scheduled' };
    const modeSubMap = {
      off: 'Manual triggers only',
      immediate: 'Convert on every new-file detection',
      queued: 'Hold scan results for next tick',
      scheduled: 'Convert at scheduler intervals',
    };
    const cell = el('div', { cls: 'pl-cell' });
    let title = 'Auto-convert scheduler mode. Off = manual only. Immediate = trigger conversion as soon as a scan finds new files. Queued = wait for the next scheduler tick. Scheduled = run at the configured interval.';
    if (data.last_auto_conversion && data.last_auto_conversion.reason) {
      title += '\n\nLast decision (' + (data.last_auto_conversion.status || 'unknown') + '): ' + data.last_auto_conversion.reason;
    }
    cell.title = title;
    cell.appendChild(el('span', { cls: 'text-muted', text: 'Mode' }));
    cell.appendChild(el('br'));
    cell.appendChild(el('strong', { text: modeLabels[data.auto_convert_mode] || data.auto_convert_mode || '--' }));
    cell.appendChild(el('div', { cls: 'pl-cell-sub', text: modeSubMap[data.auto_convert_mode] || '' }));
    return cell;
  }

  function buildLastScanCell(data, now) {
    const cell = el('div', {
      cls: 'pl-cell',
      title: 'The most recent pipeline scan that walked the source tree to find new/modified files. Interrupted = container restarted mid-scan. Completed = scan finished cleanly.',
    });
    cell.appendChild(el('span', { cls: 'text-muted', text: 'Last Scan' }));
    cell.appendChild(el('br'));

    const ls = data.last_scan;
    const valEl = el('strong');
    if (ls && ls.finished_at) {
      const d = parseTimestamp(ls.finished_at);
      valEl.textContent = d ? `${d.toLocaleTimeString()} (${fmtRel(d, now)})` : '';
    } else {
      valEl.textContent = 'Never';
    }
    cell.appendChild(valEl);

    const sub = el('div', { cls: 'pl-cell-sub' });
    if (ls && ls.finished_at) {
      const statusRaw = (ls.status || 'unknown').toLowerCase();
      const statusLabelMap = {
        completed: { text: '✓ Completed', cls: 'pl-status-ok' },
        running: { text: '⟳ Running', cls: 'pl-status-running' },
        interrupted: { text: '⚠ Interrupted', cls: 'pl-status-warn' },
        failed: { text: '✗ Failed', cls: 'pl-status-err' },
        cancelled: { text: '⊘ Cancelled', cls: 'pl-status-muted' },
      };
      const sl = statusLabelMap[statusRaw] || { text: statusRaw, cls: 'pl-status-muted' };
      sub.appendChild(el('span', { cls: 'pl-status-pill ' + sl.cls, text: sl.text }));
      const counts = fmtNum(ls.files_scanned || 0) + ' scanned';
      let extra = ' · ' + counts;
      if (ls.files_new) extra += ' · ' + fmtNum(ls.files_new) + ' new';
      if (ls.files_modified) extra += ' · ' + fmtNum(ls.files_modified) + ' modified';
      sub.appendChild(document.createTextNode(extra));
    } else {
      sub.textContent = 'No scan recorded yet';
    }
    cell.appendChild(sub);

    // v0.33.0 (Phase 4): fold the auto-conversion line into Last Scan.
    // The standalone Pending card on Status used to surface this;
    // now it lives here as a one-line sub-text under the scan stats.
    const lac = data.last_auto_conversion;
    if (lac && (lac.status || lac.workers_chosen)) {
      const acLine = el('div', { cls: 'pl-cell-sub' });
      acLine.style.marginTop = '0.2rem';
      const lacStatus = (lac.status || 'unknown').toLowerCase();
      const acIcon = lacStatus === 'running' ? '⚙' : lacStatus === 'completed' ? '✓' : '·';
      let acText = `${acIcon} Auto-conv: ${lacStatus}`;
      if (lac.workers_chosen) acText += ` · ${lac.workers_chosen} workers`;
      if (lac.batch_size_chosen) acText += ` · batch=${lac.batch_size_chosen}`;
      acLine.textContent = acText;
      acLine.title = lac.reason || '';  // full reason on hover
      cell.appendChild(acLine);
    }

    return cell;
  }

  function buildNextScanCell(data, now) {
    const cell = el('div', {
      cls: 'pl-cell',
      title: 'When the next scheduled pipeline scan will run. Click Run Now to trigger immediately instead of waiting.',
    });
    cell.appendChild(el('span', { cls: 'text-muted', text: 'Next Scan' }));
    cell.appendChild(el('br'));

    const valEl = el('strong');
    const sub = el('div', { cls: 'pl-cell-sub' });

    if (data.disabled_info) {
      valEl.textContent = '—';
      sub.textContent = 'Disabled — fix shown below';
    } else if (data.paused) {
      valEl.textContent = data.next_scan
        ? `${new Date(data.next_scan).toLocaleTimeString()} (paused)`
        : '— (paused)';
      sub.textContent = 'Pipeline paused — Resume to enable';
    } else if (data.auto_convert_mode === 'off') {
      valEl.textContent = '— (off)';
      sub.textContent = 'Mode is Off — use Run Now to scan manually';
    } else if (data.next_scan) {
      const d = new Date(data.next_scan);
      valEl.textContent = `${d.toLocaleTimeString()} (${fmtRel(d, now)})`;
      sub.textContent = `Pipeline scan · every ${data.scanner_interval_minutes || 0} min`;
    } else {
      valEl.textContent = '--';
      sub.textContent = 'Scheduler offline';
    }
    cell.appendChild(valEl);
    cell.appendChild(sub);
    return cell;
  }

  function buildSimpleCell(label, value, subText, titleText) {
    const cell = el('div', { cls: 'pl-cell', title: titleText || '' });
    cell.appendChild(el('span', { cls: 'text-muted', text: label }));
    cell.appendChild(el('br'));
    cell.appendChild(el('strong', { text: value }));
    if (subText) cell.appendChild(el('div', { cls: 'pl-cell-sub', text: subText }));
    return cell;
  }

  // Action buttons -----------------------------------------------------------

  function buildActions(data, opts, refreshFn) {
    const wrap = el('div', { style: 'display:flex;gap:0.5rem' });
    const pauseBtn = el('button', {
      cls: 'btn btn-ghost btn-sm',
      text: data.paused ? 'Resume' : 'Pause',
      attrs: { type: 'button' },
      onClick: async () => {
        const url = data.paused ? '/api/pipeline/resume' : '/api/pipeline/pause';
        try {
          await postAction(url);
          refreshFn();
        } catch (e) {
          if (typeof window.showToast === 'function') {
            window.showToast('Pipeline action failed: ' + e.message, 'error');
          }
        }
      },
    });
    wrap.appendChild(pauseBtn);

    if (!opts.compact) {
      const rebuildBtn = el('button', {
        cls: 'btn btn-ghost btn-sm',
        text: 'Rebuild Index',
        attrs: { type: 'button' },
        onClick: async () => {
          try {
            await postAction('/api/pipeline/rebuild-index');
            if (typeof window.showToast === 'function') {
              window.showToast('Search index rebuild started', 'info');
            }
          } catch (e) {
            if (typeof window.showToast === 'function') {
              window.showToast('Rebuild failed: ' + e.message, 'error');
            }
          }
        },
      });
      wrap.appendChild(rebuildBtn);
    }

    const runNowBtn = el('button', {
      cls: 'btn btn-primary btn-sm',
      text: 'Run Now',
      attrs: { type: 'button' },
      onClick: async () => {
        try {
          await postAction('/api/pipeline/run-now');
          if (typeof window.showToast === 'function') {
            window.showToast('Pipeline scan triggered', 'info');
          }
          refreshFn();
        } catch (e) {
          if (typeof window.showToast === 'function') {
            window.showToast('Run Now failed: ' + e.message, 'error');
          }
        }
      },
    });
    wrap.appendChild(runNowBtn);

    return wrap;
  }

  // Renderers ----------------------------------------------------------------

  function renderRich(container, data, opts, refreshFn) {
    clearChildren(container);
    const card = el('div', {
      cls: 'card mb-2',
      style: 'padding:1rem 1.25rem',
    });

    const now = new Date();
    const pillInfo = statusPillFromData(data);

    // Header row: title + status pill + actions
    const headerRow = el('div', {
      style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;flex-wrap:wrap;gap:0.5rem',
    });
    const titleWrap = el('div', { style: 'display:flex;align-items:center;gap:0.75rem' });
    titleWrap.appendChild(el('h3', { text: 'Pipeline', style: 'margin:0' }));
    titleWrap.appendChild(el('span', { cls: pillInfo.cls, text: pillInfo.text }));
    headerRow.appendChild(titleWrap);

    if (opts.showActions !== false) {
      headerRow.appendChild(buildActions(data, opts, refreshFn));
    }
    card.appendChild(headerRow);

    // Cell grid
    const grid = el('div', {
      style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0.5rem;font-size:0.85rem',
    });
    grid.appendChild(buildModeCell(data));
    grid.appendChild(buildLastScanCell(data, now));
    grid.appendChild(buildNextScanCell(data, now));
    grid.appendChild(buildSimpleCell(
      'Source Files',
      fmtNum(data.total_source_files || 0),
      'on disk',
      'Total source files MarkFlow knows about (anything ever scanned). Files that were trashed are NOT counted here.',
    ));
    grid.appendChild(buildSimpleCell(
      'Pending',
      fmtNum(data.pending_conversion || 0),
      'awaiting conversion',
      'Files awaiting conversion to Markdown. The auto-convert worker picks these up on the next scheduler tick (or immediately if Mode=Immediate).',
    ));
    grid.appendChild(buildSimpleCell(
      'Interval',
      (data.scanner_interval_minutes || 0) + ' min',
      'between scheduled scans',
      'Pipeline scheduler interval. Change in Settings → Auto-convert.',
    ));
    card.appendChild(grid);

    // Disabled warning
    if (data.disabled_info) {
      const warn = el('div', {
        style: 'margin-top:0.75rem;padding:0.75rem 1rem;background:rgba(220,38,38,0.08);border:1px solid var(--error);border-radius:var(--radius);color:var(--error);font-size:0.85rem',
      });
      warn.appendChild(el('strong', { text: 'Pipeline is disabled. ' }));
      warn.appendChild(document.createTextNode(data.disabled_info.message || ''));
      card.appendChild(warn);
    }

    container.appendChild(card);
  }

  function renderCompact(container, data, opts, refreshFn) {
    clearChildren(container);
    const card = el('div', {
      cls: 'card mb-2',
      style: 'padding:0.75rem 1rem',
    });

    const now = new Date();
    const pillInfo = statusPillFromData(data);
    const ls = data.last_scan;
    const lastScanRel = (ls && ls.finished_at)
      ? fmtRel(parseTimestamp(ls.finished_at), now)
      : 'never';
    const nextScanRel = data.next_scan
      ? fmtRel(new Date(data.next_scan), now)
      : '—';

    // One-line summary
    const row = el('div', {
      style: 'display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap',
    });
    row.appendChild(el('strong', { text: 'PIPELINE', style: 'font-size:0.78rem;letter-spacing:0.05em' }));
    row.appendChild(el('span', { cls: pillInfo.cls, text: pillInfo.text }));
    const summary = el('span', {
      cls: 'text-sm text-muted',
      style: 'flex:1;min-width:200px',
      text: 'Last scan ' + lastScanRel
        + ' · Next ' + nextScanRel
        + ' · ' + fmtNum(data.pending_conversion || 0) + ' pending',
    });
    row.appendChild(summary);

    if (opts.showActions !== false) {
      row.appendChild(buildActions(data, opts, refreshFn));
    }

    const viewLink = el('a', {
      cls: 'text-sm',
      href: '/static/status.html',
      text: 'view full status →',
      style: 'white-space:nowrap',
    });
    row.appendChild(viewLink);

    card.appendChild(row);
    container.appendChild(card);
  }

  function renderError(container, errorMsg) {
    clearChildren(container);
    const card = el('div', {
      cls: 'card mb-2',
      style: 'padding:0.75rem 1rem;border:1px solid var(--error);background:rgba(220,38,38,0.06)',
    });
    card.appendChild(el('strong', { text: 'Pipeline status unavailable' }));
    card.appendChild(el('div', {
      cls: 'text-sm text-muted',
      style: 'margin-top:0.25rem',
      text: errorMsg,
    }));
    container.appendChild(card);
  }

  // Mount entry point --------------------------------------------------------

  function mountPipelineCard(containerEl, opts) {
    if (!containerEl) {
      throw new Error('mountPipelineCard: containerEl is required');
    }
    opts = opts || {};
    const compact = !!opts.compact;
    const pollMs = typeof opts.pollMs === 'number' ? opts.pollMs : 30000;
    const renderer = compact ? renderCompact : renderRich;

    let pollId = null;
    let destroyed = false;

    async function refresh() {
      if (destroyed) return;
      try {
        const data = await fetchPipelineStatus();
        if (destroyed) return;
        renderer(containerEl, data, opts, refresh);
      } catch (e) {
        if (destroyed) return;
        renderError(containerEl, e.message);
      }
    }

    function start() {
      refresh();
      if (pollMs > 0) {
        pollId = setInterval(refresh, pollMs);
      }
    }

    function destroy() {
      destroyed = true;
      if (pollId) { clearInterval(pollId); pollId = null; }
      clearChildren(containerEl);
    }

    start();
    return { refresh, destroy };
  }

  window.mountPipelineCard = mountPipelineCard;
})(window);
