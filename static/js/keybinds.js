/* Global keyboard shortcuts. Register handlers via MFKeybinds.on(combo, handler).
 * Spec §3 (Cmd+\ cycles layout modes).
 *
 * Combo strings: 'mod+x' where mod = Cmd on mac, Ctrl elsewhere.
 *
 * Usage:
 *   MFKeybinds.on('mod+\\', function(ev) { ... });
 */
(function (global) {
  'use strict';

  var handlers = {};   // combo -> array of fn

  function isMac() {
    return navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  }

  function eventCombo(ev) {
    var parts = [];
    if (ev.metaKey || (!isMac() && ev.ctrlKey)) parts.push('mod');
    if (ev.shiftKey) parts.push('shift');
    if (ev.altKey) parts.push('alt');
    parts.push(ev.key.toLowerCase());
    return parts.join('+');
  }

  document.addEventListener('keydown', function (ev) {
    var combo = eventCombo(ev);
    var arr = handlers[combo];
    if (!arr) return;
    var prevent = false;
    for (var i = 0; i < arr.length; i++) {
      try { if (arr[i](ev) === true) prevent = true; }
      catch (e) { console.error('mf-keybinds: handler error', e); }
    }
    if (prevent) ev.preventDefault();
  });

  function on(combo, fn) {
    if (!handlers[combo]) handlers[combo] = [];
    handlers[combo].push(fn);
    return function off() {
      var arr = handlers[combo];
      if (!arr) return;
      var i = arr.indexOf(fn);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  global.MFKeybinds = { on: on };
})(window);
