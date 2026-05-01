/* Bulk-action bar that surfaces when MFCardSelection has any items.
 * Spec §4 (folder browse + bulk).
 *
 * Usage:
 *   var bb = MFBulkBar.create({
 *     onAction: function(action, ids) { ... }   // 'download' | 'preview' | 'copy-paths' | 'tag' | 'flag' | 'clear'
 *   });
 *   bb.mount(slot);     // attaches listeners + initial render (hidden if empty)
 *   bb.unmount();
 *
 * Hidden by display:none when selection is empty; renders + slides in
 * when at least one item is selected.
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var ACTIONS = [
    { id: 'download',   label: 'Download selected', solid: true },
    { id: 'preview',    label: 'Preview' },
    { id: 'copy-paths', label: 'Copy paths' },
    { id: 'tag',        label: 'Tag …' },
    { id: 'flag',       label: 'Flag for review' },
    { id: 'clear',      label: 'Clear' },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var root = el('div', 'mf-bulk-bar');
    root.style.display = 'none';

    var left = el('div', 'mf-bulk-bar__left');
    var check = el('div', 'mf-bulk-bar__check');
    check.textContent = '0';
    left.appendChild(check);
    var text = el('span'); text.textContent = '0 files selected';
    left.appendChild(text);
    root.appendChild(left);

    var right = el('div', 'mf-bulk-bar__right');
    ACTIONS.forEach(function (a) {
      var b = el('button', 'mf-bulk-bar__btn' + (a.solid ? ' mf-bulk-bar__btn--solid' : ''));
      b.type = 'button';
      b.textContent = a.label;
      b.setAttribute('data-action', a.id);
      b.addEventListener('click', function () {
        var ids = MFCardSelection.list();
        if (a.id === 'clear') {
          MFCardSelection.clear();
        } else {
          try { onAction(a.id, ids); } catch (e) { console.error(e); }
        }
      });
      right.appendChild(b);
    });
    root.appendChild(right);

    var unsub = null;

    function update(selectedSet) {
      var n = selectedSet.size;
      if (n === 0) {
        root.style.display = 'none';
      } else {
        root.style.display = 'flex';
        check.textContent = String(n);
        text.textContent = n + (n === 1 ? ' file selected' : ' files selected');
      }
    }

    function mount(slot) {
      slot.appendChild(root);
      unsub = MFCardSelection.subscribe(update);
      update(new Set(MFCardSelection.list()));
    }

    function unmount() {
      if (unsub) { unsub(); unsub = null; }
      if (root.parentNode) root.parentNode.removeChild(root);
    }

    return { mount: mount, unmount: unmount };
  }

  global.MFBulkBar = { create: create };
})(window);
