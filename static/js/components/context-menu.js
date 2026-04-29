/* Right-click context menu for document cards.
 * Spec §4 (menu items), §9 (power-user gate via Advanced expander).
 *
 * Usage:
 *   var cm = MFContextMenu.create({
 *     onAction: function(action, doc) { ... }
 *   });
 *   cm.openAt(clientX, clientY, doc);
 *   cm.close();
 *
 * Reads MFPrefs.advanced_actions_inline (Plan 1C) to decide whether
 * Markdown / AI integration items render inline or behind an
 * Advanced expander row.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var SECTIONS = [
    {
      label: 'View',
      items: [
        { id: 'preview',     label: 'Preview file',           kbd: 'Space' },
        { id: 'open',        label: 'Open original',          kbd: '⌘O' },
        { id: 'goto-folder', label: 'Go to containing folder', kbd: '⌘↑' },
      ],
    },
    {
      label: 'Export',
      items: [
        { id: 'download',  label: 'Download original' },
        { id: 'copy-path', label: 'Copy file path' },
      ],
    },
    {
      label: 'AI',
      items: [
        { id: 'summarize', label: 'Summarize with AI' },
        { id: 'ask',       label: 'Ask a question about this file' },
      ],
    },
  ];

  // Power-user-gated items (the Advanced section).
  var ADVANCED_ITEMS = [
    { id: 'download-md',     label: 'Download as Markdown', kbd: '⌘D' },
    { id: 'copy-md',         label: 'Copy Markdown to clipboard' },
    { id: 'view-md-source',  label: 'View raw Markdown source' },
  ];

  var TRAILING_ITEMS = [
    { id: 'pin',  label: 'Pin to favorites' },
    { id: 'flag', label: 'Flag for review', danger: true },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildSectionLabel(text) {
    var l = el('div', 'mf-ctx__sec-label');
    l.textContent = text;
    return l;
  }

  function buildItem(item, opts) {
    var a = el('a', 'mf-ctx__item');
    if (item.danger) a.className += ' mf-ctx__item--danger';
    if (opts && opts.adv) a.className += ' mf-ctx__item--adv';
    a.setAttribute('role', 'menuitem');
    a.setAttribute('data-action', item.id);
    var label = el('span', 'mf-ctx__grow');
    label.textContent = item.label;
    a.appendChild(label);
    if (item.kbd) {
      var kbd = el('span', 'mf-ctx__kbd');
      kbd.textContent = item.kbd;
      a.appendChild(kbd);
    }
    return a;
  }

  function buildAdvExpander(open) {
    var row = el('div', 'mf-ctx__exp' + (open ? ' mf-ctx__exp--open' : ''));
    row.setAttribute('data-mf-exp', '1');
    var lab = el('span'); lab.textContent = 'Advanced · Markdown & AI integrations';
    var chev = el('span', 'mf-ctx__exp-chev');
    chev.textContent = '▾';
    row.appendChild(lab);
    row.appendChild(chev);
    return row;
  }

  function buildSep(heavy) {
    var s = el('div', heavy ? 'mf-ctx__sep mf-ctx__sep--heavy' : 'mf-ctx__sep');
    return s;
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var root = el('div', 'mf-ctx');
    root.setAttribute('role', 'menu');
    root.style.display = 'none';

    var current = null;       // { doc, x, y }
    var advExpanded = false;

    function rerender() {
      while (root.firstChild) root.removeChild(root.firstChild);
      SECTIONS.forEach(function (sec) {
        root.appendChild(buildSectionLabel(sec.label));
        sec.items.forEach(function (item) {
          root.appendChild(buildItem(item));
        });
        root.appendChild(buildSep());
      });
      // Trailing items (pin / flag)
      TRAILING_ITEMS.forEach(function (item) {
        root.appendChild(buildItem(item));
      });

      // Advanced section — depends on prefs
      var inlineDefault = MFPrefs && MFPrefs.get && MFPrefs.get('advanced_actions_inline');
      root.appendChild(buildSep(true));
      if (inlineDefault === true) {
        // Pref says always show inline — label, no expander toggle.
        root.appendChild(buildSectionLabel('Advanced · Markdown & AI integrations'));
        ADVANCED_ITEMS.forEach(function (item) {
          root.appendChild(buildItem(item, { adv: true }));
        });
      } else if (advExpanded) {
        // User expanded — show open expander (click to collapse) + items.
        root.appendChild(buildAdvExpander(true));
        ADVANCED_ITEMS.forEach(function (item) {
          root.appendChild(buildItem(item, { adv: true }));
        });
      } else {
        root.appendChild(buildAdvExpander(false));
      }
    }

    root.addEventListener('click', function (ev) {
      // Expander toggle
      var exp = ev.target.closest && ev.target.closest('[data-mf-exp]');
      if (exp) {
        advExpanded = !advExpanded;
        rerender();
        return;
      }
      // Item click
      var item = ev.target.closest && ev.target.closest('[data-action]');
      if (!item) return;
      var action = item.getAttribute('data-action');
      if (current && current.doc) {
        try { onAction(action, current.doc); } catch (e) { console.error(e); }
        MFTelemetry && MFTelemetry.emit && MFTelemetry.emit(
          'ui.context_menu_action', { action: action, doc_id: current.doc.id || '' }
        );
      }
      close();
    });

    var onOutside = null, onEsc = null, listenerRafId = null;

    function openAt(x, y, doc) {
      current = { doc: doc, x: x, y: y };
      advExpanded = false;
      rerender();
      root.style.position = 'absolute';
      root.style.left = (window.scrollX + x) + 'px';
      root.style.top = (window.scrollY + y) + 'px';
      root.style.display = 'block';
      document.body.appendChild(root);

      // Keep menu inside viewport
      var r = root.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var vh = document.documentElement.clientHeight;
      if (r.right > vw - 8) {
        root.style.left = (window.scrollX + Math.max(8, x - r.width)) + 'px';
      }
      if (r.bottom > vh - 8) {
        root.style.top = (window.scrollY + Math.max(8, y - r.height)) + 'px';
      }

      if (listenerRafId) cancelAnimationFrame(listenerRafId);
      listenerRafId = requestAnimationFrame(function () {
        listenerRafId = null;
        onOutside = function (ev) { if (!root.contains(ev.target)) close(); };
        onEsc = function (ev) { if (ev.key === 'Escape') close(); };
        document.addEventListener('click', onOutside);
        document.addEventListener('keydown', onEsc);
      });
    }

    function close() {
      if (listenerRafId) { cancelAnimationFrame(listenerRafId); listenerRafId = null; }
      root.style.display = 'none';
      if (root.parentNode) root.parentNode.removeChild(root);
      if (onOutside) { document.removeEventListener('click', onOutside); onOutside = null; }
      if (onEsc) { document.removeEventListener('keydown', onEsc); onEsc = null; }
      current = null;
    }

    return { openAt: openAt, close: close };
  }

  global.MFContextMenu = { create: create };
})(window);
