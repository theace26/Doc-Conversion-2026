/* Dev-only version chip. Renders inside the MarkFlow logo per mockup.
 * Spec §1.
 *
 * Hidden in production via body[data-env="prod"] .mf-ver-chip { display: none }
 * declared in design-tokens.css.
 *
 * Usage:
 *   MFVersionChip.mount(slot, { version: 'v0.34.2-dev' });
 *
 * The 'slot' is the data-mf-slot="version-chip" span produced by top-nav.
 */
(function (global) {
  'use strict';

  function mount(slot, opts) {
    if (!slot) throw new Error('MFVersionChip.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    if (!opts || !opts.version) return;  // silent no-op if no version provided
    var span = document.createElement('span');
    span.className = 'mf-ver-chip';
    span.textContent = opts.version;
    slot.appendChild(span);
  }

  global.MFVersionChip = { mount: mount };
})(window);
