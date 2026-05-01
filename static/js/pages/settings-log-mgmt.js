/* MFLogMgmtDetail -- Log management settings detail page (Plan 6 Task 6).
 *
 * Usage:
 *   MFLogMgmtDetail.mount(slot, { files, settings });
 *
 * Admin only. Safe DOM throughout -- no innerHTML.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    { id: 'levels',      label: 'Levels per subsystem' },
    { id: 'retention',   label: 'Retention & rotation' },
    { id: 'live-viewer', label: 'Live viewer' },
    { id: 'export',      label: 'Export & archive' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function _makeSaveBar(onSave, onDiscard) {
    var bar = el('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-top:1.4rem;';

    var saveBtn = el('button', 'mf-btn mf-btn--primary');
    saveBtn.textContent = 'Save changes';
    bar.appendChild(saveBtn);

    var discardBtn = el('button', 'mf-btn mf-btn--ghost');
    discardBtn.textContent = 'Discard';
    bar.appendChild(discardBtn);

    var savedMsg = el('span');
    savedMsg.style.cssText = 'font-size:0.85rem;color:var(--mf-color-success);opacity:0;transition:opacity 0.2s;';
    savedMsg.textContent = 'Saved';
    bar.appendChild(savedMsg);

    saveBtn.addEventListener('click', function () {
      saveBtn.disabled = true;
      onSave(saveBtn, savedMsg);
    });

    discardBtn.addEventListener('click', function () {
      onDiscard();
    });

    return { bar: bar, saveBtn: saveBtn, savedMsg: savedMsg };
  }

  function _showSaved(saveBtn, savedMsg) {
    savedMsg.style.opacity = '1';
    setTimeout(function () { savedMsg.style.opacity = '0'; }, 2000);
    saveBtn.disabled = false;
  }

  function _formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    var n = bytes;
    while (n >= 1024 && i < units.length - 1) {
      n = n / 1024;
      i++;
    }
    return n.toFixed(1) + ' ' + units[i];
  }

  function _renderLevels() {
    var frag = document.createDocumentFragment();

    var notice = el('div', 'mf-log__stub-notice');
    notice.textContent = 'Per-subsystem log levels are not yet configurable. All subsystems log at the level set in the container environment.';
    frag.appendChild(notice);

    return frag;
  }

  function _renderRetention(settings, savedSettings) {
    var frag = document.createDocumentFragment();

    var fmtLabel = el('label', 'mf-stg__field-label');
    fmtLabel.textContent = 'Compression format';
    frag.appendChild(fmtLabel);

    var validFormats = (settings.valid_formats && settings.valid_formats.length)
      ? settings.valid_formats
      : ['gz', 'tar.gz', '7z'];

    var fmtSelect = el('select', 'mf-stg__field-input');
    fmtSelect.style.width = 'auto';
    validFormats.forEach(function (fmt) {
      var opt = document.createElement('option');
      opt.value = fmt;
      opt.textContent = fmt;
      if (fmt === (settings.compression_format || 'gz')) opt.selected = true;
      fmtSelect.appendChild(opt);
    });
    frag.appendChild(fmtSelect);

    var spacer1 = el('div');
    spacer1.style.marginTop = '1rem';
    frag.appendChild(spacer1);

    var retLabel = el('label', 'mf-stg__field-label');
    retLabel.textContent = 'Retention days';
    frag.appendChild(retLabel);

    var retInput = el('input', 'mf-stg__field-input');
    retInput.type = 'number';
    retInput.min = '1';
    retInput.value = settings.retention_days || 30;
    retInput.style.width = '8rem';
    frag.appendChild(retInput);

    var spacer2 = el('div');
    spacer2.style.marginTop = '1rem';
    frag.appendChild(spacer2);

    var rotLabel = el('label', 'mf-stg__field-label');
    rotLabel.textContent = 'Max rotation size (MB)';
    frag.appendChild(rotLabel);

    var rotInput = el('input', 'mf-stg__field-input');
    rotInput.type = 'number';
    rotInput.min = '1';
    rotInput.value = settings.rotation_max_size_mb || 100;
    rotInput.style.width = '8rem';
    frag.appendChild(rotInput);

    var barObj = _makeSaveBar(
      function (saveBtn, savedMsg) {
        var body = {
          compression_format: fmtSelect.value,
          retention_days: parseInt(retInput.value, 10) || 30,
          rotation_max_size_mb: parseInt(rotInput.value, 10) || 100,
        };
        fetch('/api/logs/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(body),
        })
          .then(function (r) {
            if (!r.ok) throw new Error('PUT /api/logs/settings failed: ' + r.status);
            savedSettings.compression_format = body.compression_format;
            savedSettings.retention_days = body.retention_days;
            savedSettings.rotation_max_size_mb = body.rotation_max_size_mb;
            _showSaved(saveBtn, savedMsg);
          })
          .catch(function (e) {
            console.error('mf: failed to save log retention settings', e);
            saveBtn.disabled = false;
          });
      },
      function () {
        var found = false;
        for (var i = 0; i < fmtSelect.options.length; i++) {
          if (fmtSelect.options[i].value === savedSettings.compression_format) {
            fmtSelect.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) fmtSelect.selectedIndex = 0;
        retInput.value = savedSettings.retention_days || 30;
        rotInput.value = savedSettings.rotation_max_size_mb || 100;
      }
    );

    frag.appendChild(barObj.bar);

    return frag;
  }

  function _renderLiveViewer() {
    var frag = document.createDocumentFragment();

    var desc = el('p');
    desc.textContent = 'Open the live log viewer to watch MarkFlow log output in real time.';
    desc.style.cssText = 'font-size:0.88rem;color:var(--mf-text-muted);margin-bottom:1rem;';
    frag.appendChild(desc);

    var btn = el('a', 'mf-btn mf-btn--primary');
    btn.href = '/logs';
    btn.textContent = 'Open live log viewer';
    frag.appendChild(btn);

    return frag;
  }

  function _renderExport(files) {
    var frag = document.createDocumentFragment();

    var bundleRow = el('div', 'mf-log__bundle-row');

    var bundleBtn = el('button', 'mf-btn mf-btn--primary');
    bundleBtn.textContent = 'Download bundle';
    bundleRow.appendChild(bundleBtn);

    var bundleNote = el('span', 'mf-log__bundle-note');
    bundleNote.textContent = 'Downloads all log files as a zip archive.';
    bundleRow.appendChild(bundleNote);

    frag.appendChild(bundleRow);

    bundleBtn.addEventListener('click', function () {
      bundleBtn.disabled = true;
      fetch('/api/logs/download-bundle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ names: [] }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error('bundle download failed: ' + r.status);
          return r.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'logs.zip';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          bundleBtn.disabled = false;
        })
        .catch(function (e) {
          console.error('mf: bundle download failed', e);
          bundleBtn.disabled = false;
        });
    });

    if (!files || files.length === 0) {
      var empty = el('p');
      empty.textContent = 'No log files found.';
      empty.style.cssText = 'font-size:0.88rem;color:var(--mf-text-muted);margin-top:1rem;';
      frag.appendChild(empty);
      return frag;
    }

    var table = el('table', 'mf-log__file-table');

    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    var headers = ['Name', 'Size', 'Modified', 'Compressed', ''];
    headers.forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    files.forEach(function (f) {
      var row = document.createElement('tr');

      var tdName = document.createElement('td');
      tdName.className = 'mf-log__file-name';
      tdName.textContent = f.name || '';
      row.appendChild(tdName);

      var tdSize = document.createElement('td');
      tdSize.textContent = _formatBytes(f.size_bytes || 0);
      row.appendChild(tdSize);

      var tdMod = document.createElement('td');
      var modDate = (f.modified && typeof window.parseUTC === 'function') ? window.parseUTC(f.modified) : null;
      tdMod.textContent = (modDate && !isNaN(modDate.getTime())) ? modDate.toLocaleString() : (f.modified || '');
      row.appendChild(tdMod);

      var tdComp = document.createElement('td');
      if (f.compression && f.compression !== '') {
        var badge = el('span', 'mf-log__compressed-badge');
        badge.textContent = f.compression;
        tdComp.appendChild(badge);
      }
      row.appendChild(tdComp);

      var tdAction = document.createElement('td');
      var dlBtn = el('button', 'mf-log__dl-btn');
      dlBtn.textContent = 'Download';
      dlBtn.addEventListener('click', function () {
        window.open('/api/logs/download/' + encodeURIComponent(f.name), '_blank');
      });
      tdAction.appendChild(dlBtn);
      row.appendChild(tdAction);

      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    frag.appendChild(table);

    return frag;
  }

  function _renderContent(contentSlot, activeSection, files, settings, savedSettings) {
    while (contentSlot.firstChild) contentSlot.removeChild(contentSlot.firstChild);

    var sectionDef = null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].id === activeSection) { sectionDef = SECTIONS[i]; break; }
    }

    var head = el('h2', 'mf-stg__section-head');
    head.textContent = sectionDef ? sectionDef.label : activeSection;
    contentSlot.appendChild(head);

    if (activeSection === 'levels') {
      contentSlot.appendChild(_renderLevels());
    } else if (activeSection === 'retention') {
      contentSlot.appendChild(_renderRetention(settings, savedSettings));
    } else if (activeSection === 'live-viewer') {
      contentSlot.appendChild(_renderLiveViewer());
    } else if (activeSection === 'export') {
      contentSlot.appendChild(_renderExport(files));
    }
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFLogMgmtDetail.mount: slot is required');
    opts = opts || {};

    var files = opts.files || [];
    var settings = opts.settings || {};

    var savedSettings = {
      compression_format: settings.compression_format,
      retention_days: settings.retention_days,
      rotation_max_size_mb: settings.rotation_max_size_mb,
    };

    var activeSection = 'levels';

    var body = el('div', 'mf-stg__body');

    var breadcrumb = el('a', 'mf-stg__breadcrumb');
    breadcrumb.href = '/settings';
    breadcrumb.textContent = '<- All settings';
    body.appendChild(breadcrumb);

    var headline = el('h1', 'mf-stg__headline');
    headline.textContent = 'Log management.';
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
        _renderContent(contentSlot, activeSection, files, settings, savedSettings);
      });
      sidebar.appendChild(link);
    });
    detail.appendChild(sidebar);

    var contentSlot = el('div', 'mf-stg__content');
    _renderContent(contentSlot, activeSection, files, settings, savedSettings);
    detail.appendChild(contentSlot);

    body.appendChild(detail);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFLogMgmtDetail = { mount: mount };
})(window);
