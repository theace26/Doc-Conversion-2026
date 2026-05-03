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
 * New prefs (v0.38.0):
 *   auto_dark   (bool)   — when true, theme auto-follows OS prefers-color-scheme
 *   light_theme (string) — user-chosen light theme for auto-dark mode
 *   dark_theme  (string) — user-chosen dark theme for auto-dark mode
 *
 * Safe DOM: this module touches no DOM except applySystemTheme() which sets
 * document.documentElement data-theme attribute only.
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

  // Same-family light↔dark pairs (bidirectional).
  var LIGHT_DARK_PAIR = {
    // Light → Dark
    'classic-light':   'classic-dark',
    'sage':            'forest',
    'slate':           'midnight-slate',
    'sandstone':       'dusk',
    'spring-orig':     'spring-new',
    'summer-orig':     'summer-new',
    'fall-orig':       'fall-new',
    'winter-orig':     'winter-new',
    'hc-light':        'hc-dark',
    'hc-light-new':    'hc-dark-new',
    // Dark → Light (reverse mapping)
    'classic-dark':    'classic-light',
    'forest':          'sage',
    'midnight-slate':  'slate',
    'dusk':            'sandstone',
    'spring-new':      'spring-orig',
    'summer-new':      'summer-orig',
    'fall-new':        'fall-orig',
    'winter-new':      'winter-orig',
    'hc-dark':         'hc-light',
    'hc-dark-new':     'hc-light-new'
  };

  var FALLBACK_LIGHT = 'classic-light';
  var FALLBACK_DARK  = 'classic-dark';

  var COUNTERPART = {
    'classic-light':'nebula','classic-dark':'nebula',
    'cobalt':'cobalt-new','sage':'forest','slate':'midnight-slate',
    'crimson':'rose-quartz','sandstone':'dusk','graphite':'obsidian',
    'nebula':'classic-dark','aurora':'classic-light',
    'cobalt-new':'cobalt','rose-quartz':'crimson','midnight-slate':'slate',
    'forest':'sage','obsidian':'graphite','dusk':'sandstone',
    'hc-light':'hc-light-new','hc-dark':'hc-dark-new',
    'hc-light-new':'hc-light','hc-dark-new':'hc-dark',
    'pastel-lavender':'pastel-lavender-new','pastel-mint':'pastel-mint-new',
    'pastel-lavender-new':'pastel-lavender','pastel-mint-new':'pastel-mint',
    'spring-orig':'spring-new','summer-orig':'summer-new',
    'fall-orig':'fall-new','winter-orig':'winter-new',
    'spring-new':'spring-orig','summer-new':'summer-orig',
    'fall-new':'fall-orig','winter-new':'winter-orig'
  };

  function syncAttrs(updates) {
    var h = document.documentElement;
    if (!h) return;
    if (updates.theme !== undefined)      h.setAttribute('data-theme',      updates.theme);
    if (updates.font  !== undefined)      h.setAttribute('data-font',       updates.font);
    if (updates.text_scale !== undefined) h.setAttribute('data-text-scale', updates.text_scale);
    if (updates.use_new_ux !== undefined) h.setAttribute('data-ux',         updates.use_new_ux ? 'new' : 'orig');
  }

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

  // Applies the correct theme based on OS prefers-color-scheme when auto_dark is on.
  // Does NOT persist to 'theme' pref — this is a runtime override only.
  function applySystemTheme() {
    if (!prefs.auto_dark) return;
    var isDark = !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var chosen;
    if (isDark) {
      chosen = prefs.dark_theme || FALLBACK_DARK;
    } else {
      chosen = prefs.light_theme || FALLBACK_LIGHT;
    }
    var h = document.documentElement;
    if (h) h.setAttribute('data-theme', chosen);
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
        syncAttrs(prefs);
        writeLocal();
        fireAll();
        // After server data lands, honour auto-dark if enabled.
        if (prefs.auto_dark) applySystemTheme();
      })
      .catch(function (e) {
        console.warn('mf-prefs: server load failed, using localStorage', e);
        // Still honour auto-dark from localStorage on error path.
        if (prefs.auto_dark) applySystemTheme();
      });
  }

  // Attach OS colour-scheme change listener once at module init.
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
      if (prefs.auto_dark) applySystemTheme();
    });
  }

  function get(key) { return prefs[key]; }

  function set(key, value) {
    // When auto_dark is on and the user manually picks a theme, persist into
    // light_theme or dark_theme (whichever matches the current OS mode) instead
    // of the bare 'theme' pref.  The runtime data-theme attribute is still
    // updated immediately so the preview is instant.
    if (key === 'theme' && prefs.auto_dark) {
      var isDark = !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
      var slotKey = isDark ? 'dark_theme' : 'light_theme';
      if (prefs[slotKey] === value) return Promise.resolve();
      prefs[slotKey] = value;
      var h = document.documentElement;
      if (h) h.setAttribute('data-theme', value);
      writeLocal();
      fire(slotKey);
      schedulePut(makeOne(slotKey, value));
      return Promise.resolve();
    }
    if (prefs[key] === value) return Promise.resolve();
    prefs[key] = value;
    var u = {}; u[key] = value; syncAttrs(u);
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
    // Auto-migrate theme when use_new_ux flips
    if (updates.use_new_ux !== undefined && updates.theme === undefined) {
      var cur = prefs['theme'] || 'nebula';
      var isNew = updates.use_new_ux;
      var partner = COUNTERPART[cur];
      if (partner) { prefs['theme'] = partner; }
    }
    syncAttrs(prefs);
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
    load: load, get: get, set: set, setMany: setMany, subscribe: subscribe,
    applySystemTheme: applySystemTheme,
    LIGHT_DARK_PAIR: LIGHT_DARK_PAIR,
    FALLBACK_LIGHT: FALLBACK_LIGHT,
    FALLBACK_DARK: FALLBACK_DARK
  };
})(window);
