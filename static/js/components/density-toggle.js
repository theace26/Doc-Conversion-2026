/* Density toggle — segmented control bound to MFPrefs.density.
 * Spec §4, §10, §13.
 *
 * Usage:
 *   var unsub = MFDensityToggle.mount(slot, {
 *     onChange: function(density) { ... }   // optional, before-prefs hook
 *   });
 *
 * Reads/writes MFPrefs.density. Returns an unmount function that
 * unsubscribes from prefs changes.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var OPTIONS = [
    { id: 'cards',   label: 'Cards' },
    { id: 'compact', label: 'Compact' },
    { id: 'list',    label: 'List' }
  ];

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function buildBtn(opt, current) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'mf-seg__opt' + (opt.id === current ? ' mf-seg__opt--on' : '');
    b.setAttribute('data-density', opt.id);
    b.textContent = opt.label;
    return b;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFDensityToggle.mount: slot is required');
    var onChange = (opts && opts.onChange) || null;

    function render() {
      clear(slot);
      slot.classList.add('mf-seg');
      var current = MFPrefs.get('density') || 'cards';
      OPTIONS.forEach(function (o) {
        slot.appendChild(buildBtn(o, current));
      });
    }

    function onClick(ev) {
      var t = ev.target;
      while (t && t !== slot && !t.getAttribute('data-density')) t = t.parentNode;
      if (!t || t === slot) return;
      var next = t.getAttribute('data-density');
      var current = MFPrefs.get('density') || 'cards';
      if (next === current) return;
      if (onChange) {
        try { onChange(next); } catch (e) { console.error(e); }
      }
      MFPrefs.set('density', next);
      MFTelemetry.emit('ui.density_toggle', { from: current, to: next });
    }

    slot.addEventListener('click', onClick);
    var unsub = MFPrefs.subscribe('density', render);
    render();

    return function unmount() {
      slot.removeEventListener('click', onClick);
      unsub();
      clear(slot);
    };
  }

  global.MFDensityToggle = { mount: mount, OPTIONS: OPTIONS };
})(window);
