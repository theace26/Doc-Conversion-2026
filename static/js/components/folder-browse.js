/* Folder browse — breadcrumb + header + bulk bar + card grid.
 * Spec §4. Single-page mount that wires Plan 2A's grid + Plan 2B's
 * interactions together.
 *
 * Usage:
 *   MFFolderBrowse.mount(slot, {
 *     path: '/local-46/contracts',
 *     stats: { count: 428, addedToday: 3, lastScanned: '4 min ago' },
 *     docs: [...],
 *   });
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

  function buildBreadcrumb(path) {
    var crumb = el('div', 'mf-folder__crumb');
    var segs = path.split('/').filter(Boolean);
    var home = el('a', 'mf-folder__crumb-seg');
    home.textContent = 'Home';
    home.href = '/';
    crumb.appendChild(home);
    var acc = '';
    segs.forEach(function (s, i) {
      var sep = el('span', 'mf-folder__crumb-sep');
      sep.textContent = '/';
      crumb.appendChild(sep);
      acc += '/' + s;
      if (i === segs.length - 1) {
        var here = el('span', 'mf-folder__crumb-here');
        here.textContent = s;
        crumb.appendChild(here);
      } else {
        var seg = el('a', 'mf-folder__crumb-seg');
        seg.href = '/folder' + acc;
        seg.textContent = s;
        crumb.appendChild(seg);
      }
    });
    return crumb;
  }

  function buildHeader(path, stats) {
    var h = el('div', 'mf-folder__header');
    var leftCol = el('div');
    var icon = el('div', 'mf-folder__icon-lg');
    icon.textContent = '⛬';   // dingbat folder-ish glyph
    leftCol.appendChild(icon);
    var title = el('h1', 'mf-folder__title');
    title.textContent = path;
    leftCol.appendChild(title);
    var s = el('div', 'mf-folder__stats');
    var parts = [];
    if (stats && typeof stats.count === 'number') parts.push(stats.count.toLocaleString() + ' documents');
    if (stats && typeof stats.addedToday === 'number') parts.push(stats.addedToday + ' added today');
    if (stats && stats.lastScanned) parts.push('last scanned ' + stats.lastScanned);
    s.textContent = parts.join(' · ');
    leftCol.appendChild(s);
    h.appendChild(leftCol);

    var right = el('div', 'mf-folder__header-actions');
    var densitySlot = el('div'); densitySlot.setAttribute('data-mf-slot', 'density-toggle');
    right.appendChild(densitySlot);
    var pin = el('button', 'mf-pill mf-pill--outline mf-pill--sm');
    pin.type = 'button'; pin.textContent = 'Pin folder';
    right.appendChild(pin);
    var dl = el('button', 'mf-pill mf-pill--outline mf-pill--sm');
    dl.type = 'button'; dl.textContent = 'Download all (zip)';
    right.appendChild(dl);
    h.appendChild(right);

    return h;
  }

  function mount(slot, opts) {
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.classList.add('mf-folder');

    var path = (opts && opts.path) || '/';
    var stats = (opts && opts.stats) || {};
    var docs = (opts && opts.docs) || [];

    slot.appendChild(buildBreadcrumb(path));
    slot.appendChild(buildHeader(path, stats));

    // Bulk action bar (hidden until selection)
    var bbSlot = el('div');
    slot.appendChild(bbSlot);

    // Card grid container
    var gridSlot = el('div');
    slot.appendChild(gridSlot);

    // Mount density toggle into header slot
    var densitySlot = slot.querySelector('[data-mf-slot="density-toggle"]');
    if (typeof MFDensityToggle !== 'undefined') MFDensityToggle.mount(densitySlot);

    // Mount bulk bar (auto-hides when empty)
    var bb = MFBulkBar.create({
      onAction: function (action, ids) {
        console.log('bulk:', action, ids);
      },
    });
    bb.mount(bbSlot);

    // Render grid in current density; resubscribe to density changes
    function render() {
      var density = MFPrefs.get('density') || 'cards';
      MFCardGrid.mount(gridSlot, docs, density);
    }
    render();
    var unsub = MFPrefs.subscribe('density', render);

    return function unmount() {
      unsub();
      bb.unmount();
      while (slot.firstChild) slot.removeChild(slot.firstChild);
    };
  }

  global.MFFolderBrowse = { mount: mount };
})(window);
