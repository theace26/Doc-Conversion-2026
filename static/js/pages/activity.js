/* Activity dashboard page mount. Spec §5.
 *
 * Usage:
 *   MFActivity.mount(slot, { summary, role });
 *   MFActivity.refresh(slot, summary);   // re-render with fresh data
 *
 * The boot script polls /api/activity/summary every 30s and calls
 * refresh(); the component itself is purely presentational.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildPulse(pulse) {
    var p = el('div', 'mf-pulse');
    p.appendChild(el('span', 'mf-pulse__dot'));
    p.appendChild(document.createTextNode(' ' + (pulse.label || 'All systems running')));
    return p;
  }

  function buildHeader() {
    var head = el('h1', 'mf-act__headline');
    head.textContent = 'Activity.';
    var sub = el('p', 'mf-act__subtitle');
    sub.textContent = "What's running, what's queued, what came in, what broke. The conversion engine for the K Drive at a glance.";
    var wrap = el('div');
    wrap.appendChild(head);
    wrap.appendChild(sub);
    return wrap;
  }

  function buildTiles(tiles) {
    var wrap = el('div', 'mf-act__tiles');
    var defs = [
      { lab: 'Files processed today', val: (tiles.files_processed_today || 0).toLocaleString() },
      { lab: 'In queue', val: (tiles.in_queue || 0).toLocaleString() },
      { lab: 'Active jobs', val: String(tiles.active_jobs || 0) },
      { lab: 'Last error', val: tiles.last_error_at ? formatRelative(tiles.last_error_at) : 'Never' },
    ];
    defs.forEach(function (d) {
      var t = el('div', 'mf-act__tile');
      var l = el('div', 'mf-act__tile-lab'); l.textContent = d.lab;
      var v = el('div', 'mf-act__tile-val'); v.textContent = d.val;
      t.appendChild(l); t.appendChild(v);
      wrap.appendChild(t);
    });
    return wrap;
  }

  function buildSparkline(throughput) {
    var wrap = el('div', 'mf-act__spark');
    var lab = el('div', 'mf-act__sec-label'); lab.textContent = 'Throughput · last 24h';
    wrap.appendChild(lab);
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 800 80');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'mf-act__spark-svg');
    var max = Math.max.apply(null, (throughput || []).map(function (b) { return b.count; })) || 1;
    var points = (throughput || []).map(function (b, i) {
      var x = (i / 23) * 800;
      var y = 80 - (b.count / max) * 70 - 5;
      return x + ',' + y;
    }).join(' ');
    if (points) {
      var line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      line.setAttribute('points', points);
      line.setAttribute('fill', 'none');
      line.setAttribute('stroke', '#5b3df5');
      line.setAttribute('stroke-width', '2');
      svg.appendChild(line);
      var fill = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      fill.setAttribute('points', '0,80 ' + points + ' 800,80');
      fill.setAttribute('fill', 'rgba(91,61,245,0.08)');
      fill.setAttribute('stroke', 'none');
      svg.appendChild(fill);
    }
    wrap.appendChild(svg);
    return wrap;
  }

  function buildRunningJobs(jobs) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Running now';
    wrap.appendChild(lab);
    if (!jobs || !jobs.length) {
      var empty = el('div', 'mf-act__empty');
      empty.textContent = 'No active jobs.';
      wrap.appendChild(empty);
      return wrap;
    }
    jobs.forEach(function (j) {
      var card = el('div', 'mf-act__job');
      var name = el('div', 'mf-act__job-name');
      name.textContent = j.source_path || '(unknown source)';
      card.appendChild(name);
      var pct = j.total ? Math.round((j.converted / j.total) * 100) : 0;
      var bar = el('div', 'mf-act__job-bar');
      var fill = el('div', 'mf-act__job-bar-fill');
      fill.style.width = pct + '%';
      bar.appendChild(fill);
      card.appendChild(bar);
      var stats = el('div', 'mf-act__job-stats');
      stats.textContent =
        (j.converted || 0).toLocaleString() + ' of ' + (j.total || 0).toLocaleString() +
        ' files · started ' + (formatRelative(j.started_at) || 'unknown') +
        (j.eta_seconds ? ' · ETA ~' + Math.round(j.eta_seconds / 60) + ' min' : '');
      card.appendChild(stats);
      wrap.appendChild(card);
    });
    return wrap;
  }

  function buildQueues(q) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Queues & recent activity';
    wrap.appendChild(lab);
    var grid = el('div', 'mf-act__queues');
    [
      { id: 'recently_converted',  label: 'Recently converted',  tone: 'good', meta: 'last 24h' },
      { id: 'needs_ocr',           label: 'Needs OCR',           tone: 'warn', meta: 'queued' },
      { id: 'awaiting_ai_summary', label: 'Awaiting AI summary', tone: 'neut', meta: 'queued' },
      { id: 'recently_failed',     label: 'Recently failed',     tone: 'bad',  meta: 'last 24h' },
    ].forEach(function (def) {
      var c = el('div', 'mf-act__queue-card');
      var head = el('div', 'mf-act__queue-head');
      var t = el('span', 'mf-act__queue-title'); t.textContent = def.label;
      var b = el('span', 'mf-act__queue-badge mf-act__queue-badge--' + def.tone);
      b.textContent = def.meta;
      head.appendChild(t); head.appendChild(b);
      c.appendChild(head);
      var stat = el('div', 'mf-act__queue-stat');
      stat.textContent = ((q && q[def.id]) || 0).toLocaleString();
      c.appendChild(stat);
      grid.appendChild(c);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function buildRecentJobs(jobs) {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Recent jobs';
    wrap.appendChild(lab);
    if (!jobs || !jobs.length) {
      var empty = el('div', 'mf-act__empty');
      empty.textContent = 'No jobs yet.';
      wrap.appendChild(empty);
      return wrap;
    }
    var table = el('div', 'mf-act__table');
    jobs.forEach(function (j) {
      var row = el('div', 'mf-act__table-row');
      var name = el('span', 'mf-act__table-name');
      name.textContent = j.source_path || '(unknown)';
      var status = el('span', 'mf-act__table-status mf-act__table-status--' + (j.status || ''));
      status.textContent = j.status;
      var counts = el('span', 'mf-act__table-counts');
      counts.textContent = (j.converted || 0).toLocaleString() + '/' + (j.total || 0).toLocaleString();
      var ts = el('span', 'mf-act__table-ts');
      ts.textContent = formatRelative(j.started_at) || '';
      row.appendChild(name); row.appendChild(status);
      row.appendChild(counts); row.appendChild(ts);
      table.appendChild(row);
    });
    wrap.appendChild(table);
    return wrap;
  }

  // Inline toast helper. Mirrors avatar-menu-wiring's pattern.
  function showToast(message, tone) {
    var t = document.createElement('div');
    t.className = 'mf-toast mf-toast--' + (tone || 'info');
    t.textContent = message;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 250);
    }, 2400);
  }

  function setBusy(card, busy) {
    if (busy) card.classList.add('mf-act__ctrl--busy');
    else card.classList.remove('mf-act__ctrl--busy');
    card.style.pointerEvents = busy ? 'none' : '';
    card.style.opacity = busy ? '0.7' : '';
  }

  function handleControlAction(card, actionId) {
    if (actionId === 'logs') {
      window.location.href = '/settings-log-mgmt.html';
      return;
    }
    if (actionId === 'db-health') {
      window.location.href = '/settings-db-health.html';
      return;
    }
    if (actionId === 'run-scan-now') {
      setBusy(card, true);
      fetch('/api/scanner/run-now', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) {
          setBusy(card, false);
          if (!r.ok) {
            showToast('Scan trigger failed (' + r.status + ')', 'error');
            return;
          }
          showToast('Scan started', 'success');
        })
        .catch(function (e) {
          setBusy(card, false);
          showToast('Scan trigger error', 'error');
          console.warn('mf-activity: run-scan-now failed', e);
        });
      return;
    }
    if (actionId === 'pipeline-toggle') {
      showToast('Pipeline toggle — coming soon', 'info');
      return;
    }
    showToast(actionId + ' — coming soon', 'info');
  }

  function buildControls() {
    var wrap = el('div', 'mf-act__section');
    var lab = el('h3', 'mf-act__sec-h'); lab.textContent = 'Pipeline controls';
    wrap.appendChild(lab);
    var grid = el('div', 'mf-act__controls');
    [
      { id: 'pipeline-toggle', label: 'Pipeline running', sub: 'Auto-scan + auto-convert' },
      { id: 'run-scan-now',    label: 'Run scan now',     sub: 'Triggers an immediate scan' },
      { id: 'logs',            label: 'Logs & diagnostics', sub: 'Live viewer + error history' },
      { id: 'db-health',       label: 'Database health',  sub: 'Schema + integrity + maintenance' },
    ].forEach(function (def) {
      var card = el('div', 'mf-act__ctrl');
      card.setAttribute('data-action', def.id);
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.style.cursor = 'pointer';
      var nm = el('div', 'mf-act__ctrl-name'); nm.textContent = def.label;
      var sub = el('div', 'mf-act__ctrl-sub'); sub.textContent = def.sub;
      card.appendChild(nm); card.appendChild(sub);
      card.addEventListener('click', function () { handleControlAction(card, def.id); });
      card.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          handleControlAction(card, def.id);
        }
      });
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  function formatRelative(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      var diff = (Date.now() - d) / 1000;
      if (diff < 60) return Math.floor(diff) + ' sec ago';
      if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
      if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
      if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' d ago';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  function render(slot, summary) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var body = el('div', 'mf-act__body');
    body.appendChild(buildPulse(summary.pulse || {}));
    body.appendChild(buildHeader());
    body.appendChild(buildTiles(summary.tiles || {}));
    body.appendChild(buildSparkline(summary.throughput || []));
    body.appendChild(buildRunningJobs(summary.running_jobs || []));
    body.appendChild(buildQueues(summary.queues || {}));
    body.appendChild(buildRecentJobs(summary.recent_jobs || []));
    body.appendChild(buildControls());
    slot.appendChild(body);
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFActivity.mount: slot is required');
    var summary = (opts && opts.summary) || {};
    render(slot, summary);
  }

  function refresh(slot, summary) {
    render(slot, summary);
  }

  global.MFActivity = { mount: mount, refresh: refresh };
})(window);
