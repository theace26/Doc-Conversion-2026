/* Card grid orchestrator. Renders a list of docs in the chosen density.
 * Spec §4 (densities), §10 (density preference).
 *
 * Usage:
 *   MFCardGrid.mount(slot, docs, 'cards');     // 6 per row
 *   MFCardGrid.mount(slot, docs, 'compact');   // 8 per row
 *   MFCardGrid.mount(slot, docs, 'list');      // linear rows
 *
 * Re-rendering replaces children — the grid is stateless about its docs.
 */
(function (global) {
  'use strict';

  var DENSITIES = { cards: 1, compact: 1, list: 1 };

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function applySelection(slot, selectedSet) {
    slot.querySelectorAll('.mf-doc-card').forEach(function (card) {
      var id = card.getAttribute('data-doc-id');
      if (id && selectedSet.has(id)) card.classList.add('mf-doc-card--selected');
      else card.classList.remove('mf-doc-card--selected');
    });
    slot.querySelectorAll('.mf-doc-list-row').forEach(function (row) {
      var id = row.getAttribute('data-doc-id');
      if (id && selectedSet.has(id)) row.classList.add('mf-doc-list-row--selected');
      else row.classList.remove('mf-doc-list-row--selected');
    });
    // Keep select-all checkbox in sync.
    var selectAllCb = slot.querySelector('[data-mf-select-all]');
    if (selectAllCb) {
      var allRows = Array.from(slot.querySelectorAll('.mf-doc-list-row[data-doc-id]'));
      var allSelected = allRows.length > 0 && allRows.every(function (r) {
        return selectedSet.has(r.getAttribute('data-doc-id'));
      });
      selectAllCb.setAttribute('data-mf-checked', allSelected ? '1' : '0');
    }
  }

  function buildListHeader(docs) {
    var header = document.createElement('div');
    header.className = 'mf-list-header';

    var cb = document.createElement('span');
    cb.className = 'mf-list-header__checkbox';
    cb.setAttribute('data-mf-select-all', '1');
    cb.setAttribute('data-mf-checked', '0');
    cb.setAttribute('title', 'Select all');
    cb.addEventListener('click', function () {
      if (typeof MFCardSelection === 'undefined') return;
      var allSelected = cb.getAttribute('data-mf-checked') === '1';
      if (allSelected) {
        MFCardSelection.clear();
      } else {
        MFCardSelection.set(docs.map(function (d) { return d.id; }));
      }
    });
    header.appendChild(cb);

    ['', 'Name', 'Path', 'Size', 'Modified', ''].forEach(function (label) {
      var s = document.createElement('span');
      s.className = 'mf-list-header__col';
      s.textContent = label;
      header.appendChild(s);
    });
    return header;
  }

  function mount(slot, docs, density) {
    if (!slot) throw new Error('MFCardGrid.mount: slot is required');
    if (!Array.isArray(docs)) docs = [];
    if (!DENSITIES[density]) density = 'cards';

    clear(slot);
    slot.classList.remove(
      'mf-card-grid--cards',
      'mf-card-grid--compact',
      'mf-card-grid--list'
    );
    slot.classList.add('mf-card-grid');
    slot.classList.add('mf-card-grid--' + density);

    if (density === 'list') {
      slot.appendChild(buildListHeader(docs));
      for (var i = 0; i < docs.length; i++) {
        slot.appendChild(MFDocCard.createListRow(docs[i]));
      }
    } else {
      for (var j = 0; j < docs.length; j++) {
        slot.appendChild(MFDocCard.create(docs[j]));
      }
    }

    // Re-apply current selection after re-render.
    // unsub is stored on the slot element so multiple simultaneous grids
    // do not stomp each other's subscriptions.
    if (typeof MFCardSelection !== 'undefined') {
      applySelection(slot, new Set(MFCardSelection.list()));
      if (slot._mfGridUnsub) slot._mfGridUnsub();
      slot._mfGridUnsub = MFCardSelection.subscribe(function (selectedSet) {
        applySelection(slot, selectedSet);
      });
    }
  }

  global.MFCardGrid = { mount: mount, DENSITIES: Object.keys(DENSITIES) };
})(window);
