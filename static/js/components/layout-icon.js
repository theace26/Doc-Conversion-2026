/* Layout-mode switcher button. Static. Click calls opts.onClick.
 * Spec §3 (layout modes), §6 (nav placement).
 *
 * Plan 1C wires onClick to the layout popover with three modes.
 *
 * Usage:
 *   MFLayoutIcon.mount(slot, {
 *     onClick: function(buttonEl) { ... }
 *   });
 */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  function makeRect(x, y) {
    var r = document.createElementNS(SVG_NS, 'rect');
    r.setAttribute('x', String(x));
    r.setAttribute('y', String(y));
    r.setAttribute('width', '6');
    r.setAttribute('height', '6');
    r.setAttribute('rx', '1.2');
    return r;
  }

  function buildSvg() {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 18 18');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.appendChild(makeRect(2, 2));
    svg.appendChild(makeRect(10, 2));
    svg.appendChild(makeRect(2, 10));
    svg.appendChild(makeRect(10, 10));
    return svg;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFLayoutIcon.mount: slot is required');
    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mf-layout-icon';
    btn.title = 'Home layout (' + (navigator.platform.toUpperCase().indexOf('MAC') >= 0 ? 'Cmd' : 'Ctrl') + '+\\)';
    btn.setAttribute('aria-label', 'Home layout');
    btn.setAttribute('aria-haspopup', 'menu');
    btn.setAttribute('aria-expanded', 'false');
    btn.appendChild(buildSvg());

    if (opts && typeof opts.onClick === 'function') {
      btn.addEventListener('click', function () {
        opts.onClick(btn);
      });
    }

    slot.appendChild(btn);
  }

  global.MFLayoutIcon = { mount: mount };
})(window);
