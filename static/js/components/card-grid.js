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
    var cards = slot.querySelectorAll('.mf-doc-card');
    cards.forEach(function (card) {
      var id = card.getAttribute('data-doc-id');
      if (id && selectedSet.has(id)) card.classList.add('mf-doc-card--selected');
      else card.classList.remove('mf-doc-card--selected');
    });
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
