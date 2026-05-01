/* Multi-select state manager for document cards.
 * Pub-sub store. Other components subscribe to render based on selection.
 *
 * Usage:
 *   MFCardSelection.toggle(docId);
 *   MFCardSelection.set([docId1, docId2]);
 *   MFCardSelection.clear();
 *   MFCardSelection.has(docId);
 *   MFCardSelection.size();
 *   MFCardSelection.list();           // array copy
 *   MFCardSelection.subscribe(fn);    // fn(selectedSet) on change
 *
 * No DOM. Pure state.
 */
(function (global) {
  'use strict';

  var selected = new Set();
  var subs = [];

  function fire() {
    var snapshot = new Set(selected);
    subs.forEach(function (fn) {
      try { fn(snapshot); } catch (e) { console.error(e); }
    });
  }

  function toggle(id) {
    if (!id) return;
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    fire();
  }
  function set(ids) {
    selected = new Set(ids || []);
    fire();
  }
  function clear() {
    if (selected.size === 0) return;
    selected.clear();
    fire();
  }
  function has(id) { return selected.has(id); }
  function size() { return selected.size; }
  function list() { return Array.from(selected); }
  function subscribe(fn) {
    subs.push(fn);
    return function unsubscribe() {
      var i = subs.indexOf(fn);
      if (i >= 0) subs.splice(i, 1);
    };
  }

  global.MFCardSelection = {
    toggle: toggle, set: set, clear: clear,
    has: has, size: size, list: list,
    subscribe: subscribe,
  };
})(window);
