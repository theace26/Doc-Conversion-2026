/* MFStorageDetail — Storage settings detail page (Plan 5 Task 2).
 *
 * Usage:
 *   MFStorageDetail.mount(slot, { shares, output, sources });
 *
 * Operators/admins only — boot redirects members before calling mount.
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'mounts',      label: 'Mounts' },
    { id: 'output',      label: 'Output paths' },
    { id: 'cloud',       label: 'Cloud prefetch' },
    { id: 'credentials', label: 'Credentials' },
    { id: 'writeguard',  label: 'Write guard' },
    { id: 'sync',        label: 'Sync & verification' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _statusPill(ok) {
    var mod = ok === true ? 'ok' : ok === false ? 'bad' : 'unknown';
    var pill = el('span', 'mf-stg__pill mf-stg__pill--' + mod);
    pill.textContent = ok === true ? 'mounted' : ok === false ? 'error' : 'unknown';
    return pill;
  }

  function _renderMounts(shares) {
    var frag = document.createDocumentFragment();

    var table = el('table', 'mf-stg__table');
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['Name', 'Type', 'Path', 'Status'].forEach(function (col) {
      var th = document.createElement('th');
      th.textContent = col;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    if (!shares || !shares.length) {
      var emptyRow = document.createElement('tr');
      var emptyCell = document.createElement('td');
      emptyCell.colSpan = 4;
      emptyCell.className = 'mf-stg__table-empty';
      emptyCell.textContent = 'No network shares configured.';
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
    } else {
      shares.forEach(function (share) {
        var row = document.createElement('tr');

        var tdName = document.createElement('td');
        tdName.className = 'mf-stg__table-name';
        tdName.textContent = share.name;
        row.appendChild(tdName);

        var tdType = document.createElement('td');
        tdType.className = 'mf-stg__table-type';
        tdType.textContent = (share.protocol || '').toUpperCase();
        row.appendChild(tdType);

        var tdPath = document.createElement('td');
        tdPath.className = 'mf-stg__table-path';
        var srv = share.server || '';
        var sp = share.share_path || '';
        tdPath.textContent = sp ? srv + '/' + sp : srv;
        row.appendChild(tdPath);

        var tdStatus = document.createElement('td');
        var ok = share.status && typeof share.status.ok === 'boolean' ? share.status.ok : null;
        tdStatus.appendChild(_statusPill(ok));
        row.appendChild(tdStatus);

        tbody.appendChild(row);
      });
    }
    table.appendChild(tbody);
    frag.appendChild(table);

    var manageLink = el('a', 'mf-stg__manage-link');
    manageLink.href = '/storage';
    manageLink.textContent = 'Manage mounts in the Storage page →';
    frag.appendChild(manageLink);

    return frag;
  }

  function _renderOutput(output, sources) {
    var frag = document.createDocumentFragment();

    var label = el('label', 'mf-stg__field-label');
    label.textContent = 'Output path';
    frag.appendChild(label);

    var input = el('input', 'mf-stg__field-input');
    input.type = 'text';
    input.readOnly = true;
    input.value = (output && output.path) ? output.path : '(not set)';
    frag.appendChild(input);

    var sourcesHead = el('h4', 'mf-stg__section-subhead');
    sourcesHead.textContent = 'Source paths';
    frag.appendChild(sourcesHead);

    var list = el('ul', 'mf-stg__sources-list');
    if (!sources || !sources.length) {
      var empty = document.createElement('li');
      empty.className = 'mf-stg__sources-empty';
      empty.textContent = 'No source paths configured.';
      list.appendChild(empty);
    } else {
      sources.forEach(function (src) {
        var item = document.createElement('li');
        item.textContent = src.label || src.path;
        list.appendChild(item);
      });
    }
    frag.appendChild(list);

    return frag;
  }

  // ── Shared helpers (match settings-pipeline.js conventions) ────────────────

  function _putPref(key, value) {
    return fetch('/api/preferences/' + encodeURIComponent(key), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: value }),
    }).then(function (r) {
      if (!r.ok) throw new Error('PUT /api/preferences/' + key + ' failed: ' + r.status);
    });
  }

  function _makeToggle(isOn) {
    var toggle = el('div', 'mf-pip__toggle' + (isOn ? ' mf-pip__toggle--on' : ''));
    toggle.setAttribute('data-mf-on', isOn ? '1' : '0');
    toggle.appendChild(el('div', 'mf-pip__toggle-knob'));
    return toggle;
  }

  function _toggleOn(toggle) { return toggle.getAttribute('data-mf-on') === '1'; }

  function _setToggle(toggle, on) {
    toggle.setAttribute('data-mf-on', on ? '1' : '0');
    on ? toggle.classList.add('mf-pip__toggle--on') : toggle.classList.remove('mf-pip__toggle--on');
  }

  function _makeNumberInput(value, min, max) {
    var input = el('input', 'mf-stg__field-input');
    input.type = 'number';
    input.min = String(min);
    input.max = String(max);
    input.value = value || '';
    input.style.fontFamily = 'inherit';
    return input;
  }

  function _makeFieldLabel(text) {
    var label = el('label', 'mf-stg__field-label');
    label.textContent = text;
    return label;
  }

  function _makeSaveBar(onSave, onDiscard) {
    var bar = el('div', 'mf-pip__save-bar');
    var saveBtn = el('button', 'mf-pill mf-pill--primary');
    saveBtn.type = 'button';
    saveBtn.textContent = 'Save changes';
    var discardBtn = el('button', 'mf-pill mf-pill--ghost');
    discardBtn.type = 'button';
    discardBtn.textContent = 'Discard';
    var feedback = el('span', 'mf-pip__save-feedback');
    bar.appendChild(saveBtn);
    bar.appendChild(discardBtn);
    bar.appendChild(feedback);
    saveBtn.addEventListener('click', function () {
      feedback.textContent = '';
      feedback.classList.remove('mf-pip__save-feedback--error');
      onSave(feedback);
    });
    discardBtn.addEventListener('click', function () {
      feedback.textContent = '';
      feedback.classList.remove('mf-pip__save-feedback--error');
      onDiscard();
    });
    return bar;
  }

  // ── Cloud prefetch ───────────────────────────────────────────────────────────

  function _renderCloudPrefetch(contentSlot, opts) {
    var prefs = opts.prefs || {};
    var frag = document.createDocumentFragment();

    var isEnabled = prefs.cloud_prefetch_enabled === 'true';
    var toggleRow = el('div', 'mf-pip__toggle-row');
    var toggle = _makeToggle(isEnabled);
    var toggleLabel = el('span', 'mf-pip__toggle-label');
    toggleLabel.textContent = 'Enable cloud prefetch';
    toggleRow.appendChild(toggle);
    toggleRow.appendChild(toggleLabel);
    toggle.addEventListener('click', function () { _setToggle(toggle, !_toggleOn(toggle)); });
    frag.appendChild(toggleRow);

    frag.appendChild(_makeFieldLabel('Concurrency'));
    var concInput = _makeNumberInput(prefs.cloud_prefetch_concurrency || '5', 1, 50);
    frag.appendChild(concInput);

    frag.appendChild(_makeFieldLabel('Rate limit (files/min)'));
    var rateInput = _makeNumberInput(prefs.cloud_prefetch_rate_limit || '30', 1, 1000);
    frag.appendChild(rateInput);

    frag.appendChild(_makeFieldLabel('Per-file timeout (seconds)'));
    var timeoutInput = _makeNumberInput(prefs.cloud_prefetch_timeout_seconds || '120', 10, 3600);
    frag.appendChild(timeoutInput);

    frag.appendChild(_makeFieldLabel('Min file size (bytes)'));
    var minSizeInput = _makeNumberInput(prefs.cloud_prefetch_min_size_bytes || '0', 0, 1073741824);
    frag.appendChild(minSizeInput);

    var probeRow = el('div', 'mf-pip__toggle-row');
    probeRow.style.marginTop = '0.75rem';
    var probeToggle = _makeToggle(prefs.cloud_prefetch_probe_all === 'true');
    var probeLabel = el('span', 'mf-pip__toggle-label');
    probeLabel.textContent = 'Probe all files for cloud-only status';
    probeRow.appendChild(probeToggle);
    probeRow.appendChild(probeLabel);
    probeToggle.addEventListener('click', function () { _setToggle(probeToggle, !_toggleOn(probeToggle)); });
    frag.appendChild(probeRow);

    var saveBar = _makeSaveBar(
      function (feedback) {
        Promise.resolve()
          .then(function () { return _putPref('cloud_prefetch_enabled', _toggleOn(toggle) ? 'true' : 'false'); })
          .then(function () { return _putPref('cloud_prefetch_concurrency', concInput.value); })
          .then(function () { return _putPref('cloud_prefetch_rate_limit', rateInput.value); })
          .then(function () { return _putPref('cloud_prefetch_timeout_seconds', timeoutInput.value); })
          .then(function () { return _putPref('cloud_prefetch_min_size_bytes', minSizeInput.value); })
          .then(function () { return _putPref('cloud_prefetch_probe_all', _toggleOn(probeToggle) ? 'true' : 'false'); })
          .then(function () { feedback.textContent = 'Saved'; })
          .catch(function (e) {
            feedback.classList.add('mf-pip__save-feedback--error');
            feedback.textContent = 'Error: ' + e.message;
          });
      },
      function () {
        _setToggle(toggle, prefs.cloud_prefetch_enabled === 'true');
        concInput.value = prefs.cloud_prefetch_concurrency || '5';
        rateInput.value = prefs.cloud_prefetch_rate_limit || '30';
        timeoutInput.value = prefs.cloud_prefetch_timeout_seconds || '120';
        minSizeInput.value = prefs.cloud_prefetch_min_size_bytes || '0';
        _setToggle(probeToggle, prefs.cloud_prefetch_probe_all === 'true');
      }
    );
    frag.appendChild(saveBar);

    contentSlot.appendChild(frag);
  }

  // ── Credentials ──────────────────────────────────────────────────────────────

  function _renderCredentials(contentSlot, opts) {
    var shares = opts.shares || [];

    var note = el('p', 'mf-stg__field-note');
    note.textContent = 'Saved credentials are encrypted at rest. Passwords are masked here.';
    contentSlot.appendChild(note);

    var table = el('table', 'mf-stg__table');
    var thead = el('thead');
    var headRow = el('tr');
    ['Share name', 'Protocol', 'Server', 'Credentials'].forEach(function (col) {
      var th = el('th');
      th.textContent = col;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    if (!shares.length) {
      var emptyRow = el('tr');
      var emptyCell = el('td');
      emptyCell.colSpan = 4;
      emptyCell.className = 'mf-stg__table-empty';
      emptyCell.textContent = 'No network shares configured.';
      emptyRow.appendChild(emptyCell);
      tbody.appendChild(emptyRow);
    } else {
      shares.forEach(function (share) {
        var row = el('tr');

        var tdName = el('td', 'mf-stg__table-name');
        tdName.textContent = share.name || '';
        row.appendChild(tdName);

        var tdProto = el('td', 'mf-stg__table-type');
        tdProto.textContent = (share.protocol || '').toUpperCase();
        row.appendChild(tdProto);

        var tdServer = el('td', 'mf-stg__table-path');
        var srv = share.server || '';
        var sp = share.share_path || '';
        tdServer.textContent = sp ? srv + '/' + sp : srv;
        row.appendChild(tdServer);

        var tdCred = el('td');
        var hasCreds = share.username || share.password;
        var credSpan = el('span', 'mf-stg__pill mf-stg__pill--' + (hasCreds ? 'ok' : 'unknown'));
        credSpan.textContent = hasCreds ? 'Saved' : 'None';
        tdCred.appendChild(credSpan);
        row.appendChild(tdCred);

        tbody.appendChild(row);
      });
    }
    table.appendChild(tbody);
    contentSlot.appendChild(table);

    var manageLink = el('a', 'mf-stg__manage-link');
    manageLink.href = '/storage';
    manageLink.textContent = 'Add or edit credentials in the Storage page →';
    contentSlot.appendChild(manageLink);
  }

  // ── Write guard ───────────────────────────────────────────────────────────────

  function _renderWriteGuard(contentSlot, opts) {
    var outputPath = (opts.output && opts.output.path) ? opts.output.path : '';
    var isActive = outputPath.length > 0;

    var statusRow = el('div', 'mf-pip__toggle-row');
    statusRow.style.marginBottom = '1rem';
    var pill = el('span', 'mf-stg__pill mf-stg__pill--' + (isActive ? 'ok' : 'unknown'));
    pill.textContent = isActive ? 'Active' : 'Not configured';
    statusRow.appendChild(pill);
    contentSlot.appendChild(statusRow);

    contentSlot.appendChild(_makeFieldLabel('Protected output directory'));
    var pathInput = el('input', 'mf-stg__field-input');
    pathInput.type = 'text';
    pathInput.readOnly = true;
    pathInput.value = outputPath || '(no output path configured)';
    pathInput.style.fontFamily = 'var(--mf-font-mono, monospace)';
    contentSlot.appendChild(pathInput);

    var desc = el('p', 'mf-stg__field-note');
    desc.textContent = 'Every file write is checked against this path before proceeding. Writes outside this directory are rejected. This guard is always enforced and cannot be disabled.';
    contentSlot.appendChild(desc);

    if (!isActive) {
      var warn = el('p', 'mf-stg__field-note');
      warn.style.color = 'var(--mf-color-warning, #b45309)';
      warn.textContent = 'No output directory is configured. Bulk conversions will fail until an output path is set.';
      contentSlot.appendChild(warn);
    }

    var manageLink = el('a', 'mf-stg__manage-link');
    manageLink.href = '/storage';
    manageLink.textContent = 'Configure output path in the Storage page →';
    contentSlot.appendChild(manageLink);
  }

  // ── Sync & verification ───────────────────────────────────────────────────────

  function _renderSyncVerification(contentSlot) {
    var sections = [
      {
        heading: 'Content-hash keying',
        body: 'Every converted output is keyed by the SHA-256 hash of the source content (not the filename). Sidecar files — styles, metadata, custom headings — are matched to source documents by hash. Renaming or moving a source file does not trigger a re-conversion; only a content change does.',
      },
      {
        heading: 'Database integrity',
        body: 'The SQLite database runs a weekly PRAGMA integrity_check as part of scheduled maintenance, yielding to active bulk jobs before running. Results are written to the application log. No operator action is required unless errors appear in the log.',
      },
      {
        heading: 'Mount health',
        body: 'Network share mount points are probed on a 5-minute interval by the scheduler. Current mount status is shown on the Mounts tab. Unhealthy mounts are logged and surfaced in the Operations page.',
      },
    ];

    sections.forEach(function (s) {
      var heading = el('h4', 'mf-stg__section-subhead');
      heading.textContent = s.heading;
      contentSlot.appendChild(heading);

      var body = el('p', 'mf-stg__field-note');
      body.style.marginBottom = '1.25rem';
      body.textContent = s.body;
      contentSlot.appendChild(body);
    });

    var note = el('p', 'mf-stg__field-note');
    note.style.fontStyle = 'italic';
    note.textContent = 'These checks run automatically. No configuration options are available.';
    contentSlot.appendChild(note);
  }

  // ── Content routing ──────────────────────────────────────────────────────────

  function _renderContent(contentSlot, activeSection, opts) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { sectionDef = SECTIONS[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'mounts') {
      contentSlot.appendChild(_renderMounts(opts.shares));
    } else if (activeSection === 'output') {
      contentSlot.appendChild(_renderOutput(opts.output, opts.sources));
    } else if (activeSection === 'cloud') {
      _renderCloudPrefetch(contentSlot, opts);
    } else if (activeSection === 'credentials') {
      _renderCredentials(contentSlot, opts);
    } else if (activeSection === 'writeguard') {
      _renderWriteGuard(contentSlot, opts);
    } else if (activeSection === 'sync') {
      _renderSyncVerification(contentSlot);
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFStorageDetail.mount: slot is required');
    opts = opts || {};

    var activeSection = opts.activeSection || 'mounts';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '← All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Storage.';
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
        _renderContent(contentSlot, activeSection, opts);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, opts);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFStorageDetail = { mount: mount };
})(window);
