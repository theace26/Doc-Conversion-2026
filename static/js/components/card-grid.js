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
  }

  global.MFCardGrid = { mount: mount, DENSITIES: Object.keys(DENSITIES) };
})(window);
