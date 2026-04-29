/* Client per-user preferences. localStorage-backed cache + debounced server sync.
 * Spec §10. Server endpoints: GET/PUT /api/user-prefs (Plan 1A Task 8).
 * NOTE: /api/user-prefs is the per-user store (UnionCore sub-keyed). Distinct
 * from /api/preferences which is system-level singleton prefs — do not conflate.
 *
 * Usage:
 *   await MFPrefs.load();                      // hydrates from server, falls back to LS
 *   MFPrefs.get('layout');                      // sync after load()
 *   await MFPrefs.set('layout', 'recent');      // local + queued PUT
 *   await MFPrefs.setMany({layout:'recent', density:'compact'});
 *   var unsub = MFPrefs.subscribe('layout', function(v) { ... });
 *
 * Safe DOM: this module touches no DOM.
 */
(function (global) {
  'use strict';

  var LS_KEY = 'mf:preferences:v1';
  var ENDPOINT = '/api/user-prefs';
  var DEBOUNCE_MS = 500;

  var prefs = {};
  var pending = null;
  var saveTimer = null;
  var subs = {};   // key -> array of callbacks

  function readLocal() {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); }
    catch (e) { return {}; }
  }
  function writeLocal() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(prefs)); } catch (e) {}
  }

  function fire(key) {
    var arr = subs[key];
    if (!arr) return;
    for (var i = 0; i < arr.length; i++) {
      try { arr[i](prefs[key]); } catch (e) { console.error(e); }
    }
  }
  function fireAll() {
    for (var k in subs) if (Object.prototype.hasOwnProperty.call(subs, k)) fire(k);
  }

  function schedulePut(updates) {
    pending = Object.assign(pending || {}, updates);
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, DEBOUNCE_MS);
  }

  function flush() {
    if (!pending) return;
    var body = pending;
    pending = null;
    saveTimer = null;
    fetch(ENDPOINT, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) {
        console.warn('mf-prefs: PUT failed', r.status);
        // re-queue for next set() to retry
        pending = Object.assign(body, pending || {});
        return null;
      }
      return r.json();
    }).then(function (fresh) {
      if (fresh) { prefs = fresh; writeLocal(); fireAll(); }
    }).catch(function (e) {
      console.warn('mf-prefs: PUT error', e);
      pending = Object.assign(body, pending || {});
    });
  }

  function load() {
    // Optimistic: localStorage first so first paint is fast.
    prefs = readLocal();
    fireAll();
    return fetch(ENDPOINT, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('preferences load failed: ' + r.status);
        return r.json();
      })
      .then(function (server) {
        prefs = server;     // server wins on conflict
        writeLocal();
        fireAll();
      })
      .catch(function (e) {
        console.warn('mf-prefs: server load failed, using localStorage', e);
      });
  }

  function get(key) { return prefs[key]; }

  function set(key, value) {
    if (prefs[key] === value) return Promise.resolve();
    prefs[key] = value;
    writeLocal();
    fire(key);
    schedulePut(makeOne(key, value));
    return Promise.resolve();
  }
  function makeOne(k, v) { var o = {}; o[k] = v; return o; }

  function setMany(updates) {
    var changed = false;
    var keys = Object.keys(updates);
    for (var i = 0; i < keys.length; i++) {
      if (prefs[keys[i]] !== updates[keys[i]]) {
        prefs[keys[i]] = updates[keys[i]];
        changed = true;
      }
    }
    if (!changed) return Promise.resolve();
    writeLocal();
    for (var j = 0; j < keys.length; j++) fire(keys[j]);
    schedulePut(updates);
    return Promise.resolve();
  }

  function subscribe(key, cb) {
    if (!subs[key]) subs[key] = [];
    subs[key].push(cb);
    return function unsubscribe() {
      var arr = subs[key];
      if (!arr) return;
      var i = arr.indexOf(cb);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  global.MFPrefs = {
    load: load, get: get, set: set, setMany: setMany, subscribe: subscribe
  };
})(window);
