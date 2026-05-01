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

  function _renderStub() {
    var frag = document.createDocumentFragment();
    var stub = el('div', 'mf-stg__stub');
    var p = document.createElement('p');
    p.textContent = 'Coming soon — configure in the ';
    var link = document.createElement('a');
    link.href = '/storage';
    link.textContent = 'Storage page';
    p.appendChild(link);
    p.appendChild(document.createTextNode('.'));
    stub.appendChild(p);
    frag.appendChild(stub);
    return frag;
  }

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
    } else {
      contentSlot.appendChild(_renderStub());
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
