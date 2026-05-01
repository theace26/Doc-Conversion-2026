/* Avatar — gradient circle button in the nav. Click calls opts.onClick.
 * Spec §6. Plan 1C connects this to the avatar menu popover.
 *
 * Usage:
 *   MFAvatar.mount(slot, {
 *     user: { name: 'Xerxes', role: 'admin' },
 *     onClick: function(buttonEl) { ... }
 *   });
 */
(function (global) {
  'use strict';

  function mount(slot, opts) {
    if (!slot) throw new Error('MFAvatar.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mf-avatar';
    btn.setAttribute('aria-label', 'Account menu');
    btn.setAttribute('aria-haspopup', 'menu');
    btn.setAttribute('aria-expanded', 'false');

    if (opts && typeof opts.onClick === 'function') {
      btn.addEventListener('click', function () {
        opts.onClick(btn);
      });
    }

    slot.appendChild(btn);
  }

  global.MFAvatar = { mount: mount };
})(window);
