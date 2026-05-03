/* Layout-mode popover. Three options + current-mode checkmark.
 * Spec §3, §6.
 *
 * Usage:
 *   var pop = MFLayoutPopover.create({
 *     current: 'minimal',
 *     onChoose: function(mode) { ... }   // mode in {'maximal','recent','minimal'}
 *   });
 *   pop.openAt(layoutIconButton);
 *   pop.setCurrent('recent');             // re-renders checkmark + footer
 *   pop.close();
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var MODES = [
    { id: 'maximal', label: 'Maximal', desc: 'Search + browse rows' },
    { id: 'recent',  label: 'Recent',  desc: 'Search + history only' },
    { id: 'minimal', label: 'Minimal', desc: 'Just the search box' }
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }
  function findMode(id) {
    for (var i = 0; i < MODES.length; i++) if (MODES[i].id === id) return MODES[i];
    return MODES[2];
  }

  function create(opts) {
    var current = (opts && opts.current) || 'minimal';
    var onChoose = (opts && opts.onChoose) || function () {};

    var root = el('div', 'mf-layout-pop');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    function buildHead() {
      var h = el('div', 'mf-layout-pop__head');
      var title = el('div', 'mf-layout-pop__title');
      title.textContent = 'Home layout';
      h.appendChild(title);
      var kbd = el('div', 'mf-layout-pop__kbd');
      var k = el('kbd');
      k.textContent = (navigator.platform.toUpperCase().indexOf('MAC') >= 0 ? '⌘' : 'Ctrl+') + '\\';
      kbd.appendChild(k);
      kbd.appendChild(document.createTextNode(' to cycle'));
      h.appendChild(kbd);
      return h;
    }

    function buildOpt(mode) {
      var o = el('div', 'mf-layout-pop__opt' + (mode.id === current ? ' mf-layout-pop__opt--on' : ''));
      o.setAttribute('role', 'menuitem');
      o.setAttribute('data-mode', mode.id);
      var name = el('div', 'mf-layout-pop__name');
      name.textContent = mode.label;
      var desc = el('div', 'mf-layout-pop__desc');
      desc.textContent = mode.desc;
      var check = el('span', 'mf-layout-pop__check');
      if (mode.id === current) check.textContent = '✓';
      o.appendChild(name);
      o.appendChild(desc);
      o.appendChild(check);
      return o;
    }

    function buildFoot() {
      var f = el('div', 'mf-layout-pop__foot');
      f.appendChild(document.createTextNode('Layout: '));
      var b = el('strong');
      b.textContent = findMode(current).label;
      f.appendChild(b);
      return f;
    }

    function rerender() {
      while (root.firstChild) root.removeChild(root.firstChild);
      root.appendChild(buildHead());
      MODES.forEach(function (m) { root.appendChild(buildOpt(m)); });
      root.appendChild(buildFoot());
    }

    rerender();

    root.addEventListener('click', function (ev) {
      var t = ev.target;
      while (t && t !== root && !t.getAttribute('data-mode')) t = t.parentNode;
      if (!t || t === root) return;
      var mode = t.getAttribute('data-mode');
      if (mode !== current) {
        current = mode;
        onChoose(mode);
      }
      close();
    });

    var anchor = null;
    var onOutside = null;
    var onEsc = null;

    function openAt(triggerBtn) {
      anchor = triggerBtn;
      anchor.setAttribute('aria-expanded', 'true');
      var r = anchor.getBoundingClientRect();
      root.style.position = 'absolute';
      root.style.top = (window.scrollY + r.bottom + 8) + 'px';
      root.style.right = (document.documentElement.clientWidth - (window.scrollX + r.right)) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);
      requestAnimationFrame(function () {
        onOutside = function (ev) {
          if (!root.contains(ev.target) && ev.target !== anchor) close();
        };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }
    function close() {
      if (!anchor) return;
      anchor.setAttribute('aria-expanded', 'false');
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener('click', onOutside);
      document.removeEventListener('keydown', onEsc);
      anchor = null;
    }
    function setCurrent(mode) { current = mode; rerender(); }

    return { openAt: openAt, close: close, setCurrent: setCurrent, getCurrent: function () { return current; } };
  }

  global.MFLayoutPopover = { create: create, MODES: MODES };
})(window);
