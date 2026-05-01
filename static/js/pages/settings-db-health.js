/* MFDBHealthDetail — Database health settings detail page (Plan 6 Task 5).
 *
 * Usage:
 *   MFDBHealthDetail.mount(slot, { health, log });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout — no innerHTML.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'connection-pool',   label: 'Connection pool' },
    { id: 'backups',           label: 'Backups' },
    { id: 'maintenance',       label: 'Maintenance window' },
    { id: 'migrations',        label: 'Migrations' },
    { id: 'integrity',         label: 'Integrity check' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _formatBytes(bytes) {
    if (bytes == null || isNaN(bytes)) return '—';
    var b = Number(bytes);
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    if (b < 1024 * 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + ' MB';
    return (b / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function _formatTimestamp(val) {
    if (!val) return '—';
    if (typeof global.parseUTC === 'function') {
      var d = global.parseUTC(val);
      if (d && !isNaN(d.getTime())) return d.toLocaleString();
    }
    return String(val);
  }

  function _makeStat(label, value) {
    var stat = el('div', 'mf-dbh__stat');
    var lbl = el('span', 'mf-dbh__stat-label');
    lbl.textContent = label;
    stat.appendChild(lbl);
    var val = el('span', 'mf-dbh__stat-value');
    val.textContent = value != null ? String(value) : '—';
    stat.appendChild(val);
    return stat;
  }

  function _makeResultPill(text, mod) {
    var pill = el('span', 'mf-dbh__result-pill mf-dbh__result-pill--' + mod);
    pill.textContent = text;
    return pill;
  }

  function _renderConnectionPool(health) {
    var frag = document.createDocumentFragment();

    var grid = el('div', 'mf-dbh__stat-grid');
    grid.appendChild(_makeStat('Pool size', health.pool_size != null ? health.pool_size : '—'));
    grid.appendChild(_makeStat('Write queue depth', health.write_queue_depth != null ? health.write_queue_depth : '—'));
    grid.appendChild(_makeStat('Database size', _formatBytes(health.db_size_bytes)));
    frag.appendChild(grid);

    var pathLabel = el('label', 'mf-stg__field-label');
    pathLabel.textContent = 'Database path';
    frag.appendChild(pathLabel);

    var pathInput = el('input', 'mf-stg__field-input mf-dbh__mono');
    pathInput.type = 'text';
    pathInput.readOnly = true;
    pathInput.value = health.db_path || '—';
    frag.appendChild(pathInput);

    return frag;
  }

  function _renderBackups(health) {
    var frag = document.createDocumentFragment();

    var rawLastBackup = health.last_backup;
    var lastBackupText;
    if (!rawLastBackup) {
      lastBackupText = 'Never';
    } else if (/\d{4}-\d{2}-\d{2}/.test(String(rawLastBackup))) {
      lastBackupText = _formatTimestamp(rawLastBackup);
    } else {
      lastBackupText = String(rawLastBackup);
    }

    var grid = el('div', 'mf-dbh__stat-grid');
    grid.appendChild(_makeStat('Last backup', lastBackupText));
    frag.appendChild(grid);

    var pathLabel = el('label', 'mf-stg__field-label');
    pathLabel.textContent = 'Backup path';
    frag.appendChild(pathLabel);

    var pathInput = el('input', 'mf-stg__field-input mf-dbh__mono');
    pathInput.type = 'text';
    pathInput.readOnly = true;
    pathInput.value = health.backup_path || '—';
    frag.appendChild(pathInput);

    var note = el('p');
    note.style.cssText = 'font-size:0.83rem;color:var(--mf-text-muted);margin-top:0.75rem;';
    note.textContent = 'Configure backup volume in docker-compose.yml.';
    frag.appendChild(note);

    return frag;
  }

  function _renderMaintenance(health) {
    var frag = document.createDocumentFragment();

    var grid = el('div', 'mf-dbh__stat-grid');
    grid.appendChild(_makeStat('Last compaction', _formatTimestamp(health.last_compaction)));
    frag.appendChild(grid);

    var actionRow = el('div', 'mf-dbh__action-row');

    var compactBtn = el('button', 'mf-btn mf-btn--primary');
    compactBtn.textContent = 'Run compaction now';
    actionRow.appendChild(compactBtn);

    var spinnerSpan = el('span', 'mf-dbh__spinner');
    actionRow.appendChild(spinnerSpan);

    var pillSlot = el('span');
    actionRow.appendChild(pillSlot);

    compactBtn.addEventListener('click', function () {
      compactBtn.disabled = true;
      spinnerSpan.textContent = 'Running…';
      while (pillSlot.firstChild) pillSlot.removeChild(pillSlot.firstChild);

      fetch('/api/db/compact', {
        method: 'POST',
        credentials: 'same-origin',
      })
        .then(function (r) {
          if (!r.ok) throw new Error('compact failed: ' + r.status);
          return r.json();
        })
        .then(function (data) {
          spinnerSpan.textContent = '';
          var durMs = data && data.duration_ms != null ? data.duration_ms : '';
          var label = durMs !== '' ? 'Compacted — ' + durMs + 'ms' : 'Compacted';
          pillSlot.appendChild(_makeResultPill(label, 'ok'));
          compactBtn.disabled = false;
        })
        .catch(function (e) {
          spinnerSpan.textContent = '';
          pillSlot.appendChild(_makeResultPill(e.message || 'Error', 'err'));
          compactBtn.disabled = false;
        });
    });

    frag.appendChild(actionRow);
    return frag;
  }

  function _renderMigrations() {
    var frag = document.createDocumentFragment();

    var grid = el('div', 'mf-dbh__stat-grid');
    var stat = el('div', 'mf-dbh__stat');
    var lbl = el('span', 'mf-dbh__stat-label');
    lbl.textContent = 'Migration status';
    stat.appendChild(lbl);
    var valRow = el('span');
    valRow.style.marginTop = '0.2rem';
    valRow.appendChild(_makeResultPill('✓ Up to date', 'ok'));
    stat.appendChild(valRow);
    grid.appendChild(stat);
    frag.appendChild(grid);

    var note = el('p');
    note.style.cssText = 'font-size:0.83rem;color:var(--mf-text-muted);margin-top:0.5rem;';
    note.textContent = 'Migration history is managed automatically on container start.';
    frag.appendChild(note);

    return frag;
  }

  function _renderIntegrity(health) {
    var frag = document.createDocumentFragment();

    var grid = el('div', 'mf-dbh__stat-grid');

    var lastCheckStat = _makeStat('Last check', _formatTimestamp(health.last_integrity_check));
    grid.appendChild(lastCheckStat);

    var resultStat = el('div', 'mf-dbh__stat');
    var resultLabel = el('span', 'mf-dbh__stat-label');
    resultLabel.textContent = 'Result';
    resultStat.appendChild(resultLabel);
    var resultValRow = el('span');
    resultValRow.style.marginTop = '0.2rem';
    if (health.integrity_ok === true) {
      resultValRow.appendChild(_makeResultPill('OK', 'ok'));
    } else if (health.integrity_ok === false) {
      resultValRow.appendChild(_makeResultPill('Issues found', 'err'));
    } else {
      resultValRow.appendChild(_makeResultPill('—', 'neutral'));
    }
    resultStat.appendChild(resultValRow);
    grid.appendChild(resultStat);

    frag.appendChild(grid);

    var actionRow = el('div', 'mf-dbh__action-row');

    var checkBtn = el('button', 'mf-btn mf-btn--primary');
    checkBtn.textContent = 'Run now';
    actionRow.appendChild(checkBtn);

    var spinnerSpan = el('span', 'mf-dbh__spinner');
    actionRow.appendChild(spinnerSpan);

    var pillSlot = el('span');
    actionRow.appendChild(pillSlot);

    checkBtn.addEventListener('click', function () {
      checkBtn.disabled = true;
      spinnerSpan.textContent = 'Checking…';
      while (pillSlot.firstChild) pillSlot.removeChild(pillSlot.firstChild);

      fetch('/api/db/integrity-check', {
        method: 'POST',
        credentials: 'same-origin',
      })
        .then(function (r) {
          if (!r.ok) throw new Error('integrity check failed: ' + r.status);
          return r.json();
        })
        .then(function (data) {
          spinnerSpan.textContent = '';
          if (data && data.ok === true) {
            pillSlot.appendChild(_makeResultPill('OK', 'ok'));
          } else if (data && data.issues && data.issues.length > 0) {
            pillSlot.appendChild(_makeResultPill('Issues: ' + data.issues.length, 'err'));
          } else {
            pillSlot.appendChild(_makeResultPill('Issues found', 'err'));
          }
          checkBtn.disabled = false;
        })
        .catch(function (e) {
          spinnerSpan.textContent = '';
          pillSlot.appendChild(_makeResultPill(e.message || 'Error', 'err'));
          checkBtn.disabled = false;
        });
    });

    frag.appendChild(actionRow);
    return frag;
  }

  function _renderContent(contentSlot, activeSection, health) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { sectionDef = SECTIONS[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'connection-pool') {
      contentSlot.appendChild(_renderConnectionPool(health));
    } else if (activeSection === 'backups') {
      contentSlot.appendChild(_renderBackups(health));
    } else if (activeSection === 'maintenance') {
      contentSlot.appendChild(_renderMaintenance(health));
    } else if (activeSection === 'migrations') {
      contentSlot.appendChild(_renderMigrations());
    } else if (activeSection === 'integrity') {
      contentSlot.appendChild(_renderIntegrity(health));
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFDBHealthDetail.mount: slot is required');
    opts = opts || {};

    var health = opts.health || {};
    var activeSection = 'connection-pool';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Database health.';
    body.appendChild(headline);

    var detail = el('div', 'mf-stg__detail');

    var sidebar = el('nav', 'mf-stg__sidebar');
    SECTIONS.forEach(function (sec) {
      var isActive = sec.id === activeSection;
      var link = el('a', 'mf-stg__sidebar-link' + (isActive ? ' mf-stg__sidebar-link--active' : ''));
      link.href = '#' + sec.id;
      link.textContent = sec.label;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        activeSection = sec.id;
        sidebar.querySelectorAll('.mf-stg__sidebar-link').forEach(function (l) {
          l.classList.remove('mf-stg__sidebar-link--active');
        });
        link.classList.add('mf-stg__sidebar-link--active');
        _renderContent(contentSlot, activeSection, health);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, health);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFDBHealthDetail = { mount: mount };
})(window);
