/* MFAvatarMenuWiring — single source of truth for avatar menu mounting and
 * ID -> URL routing across both UX modes. Used by static/app.js (original UX,
 * pageSet='original') and every static/js/*-boot.js (new UX, pageSet='new').
 *
 * Owns: the click->URL map, the "coming soon" toast for items without
 * destination pages, the sign-out flow, and the avatar mount.
 *
 * Usage:
 *   MFAvatarMenuWiring.mount(slot, {
 *     user:    { name: 'Xerxes', role: 'admin', scope: 'IBEW Local 46' },
 *     build:   { version: 'v0.37.0', branch: 'main', sha: 'd15ddb3', date: '2026-05-01' },
 *     pageSet: 'original' | 'new',
 *   });
 *
 * Requires MFAvatar, MFAvatarMenu loaded first. MFDisplayPrefsDrawer is
 * required only if the user clicks Display preferences.
 */
(function (global) {
  'use strict';

  // ID -> URL for original UX (bare-named pages). Items not in the map fall
  // through to the "coming soon" toast.
  var URLS_ORIGINAL = {
    'storage':      '/storage.html',
    'pipeline':     '/pipeline-files.html',
    'ai':           '/providers.html',
    'db':           '/db-health.html',
    'logs':         '/log-management.html',
    'all-settings': '/settings.html',
    'help':         '/help.html'
  };

  // ID -> URL for new UX (settings-* pages).
  var URLS_NEW = {
    'notifications': '/settings-notifications.html',
    'storage':       '/settings-storage.html',
    'pipeline':      '/settings-pipeline.html',
    'ai':            '/settings-ai-providers.html',
    'auth':          '/settings-auth.html',
    'db':            '/settings-db-health.html',
    'logs':          '/log-mgmt-new.html',
    'log-viewer':    '/log-viewer-new.html',
    'log-levels':    '/log-levels-new.html',
    'all-settings':  '/settings-new.html',
    'help':          '/help-new.html'
  };

  // Friendly labels for items that fall through to the toast.
  var COMING_SOON = {
    'profile':       'Profile page',
    'pinned':        'Pinned folders & topics',
    'notifications': 'Notifications',
    'api-keys':      'API keys',
    'auth':          'Account & auth',
    'shortcuts':     'Keyboard shortcuts',
    'bug':           'Bug reporting'
  };

  function showToast(message) {
    var t = document.createElement('div');
    t.className = 'mf-toast mf-toast--info';
    t.textContent = message;
    document.body.appendChild(t);
    requestAnimationFrame(function () {
      t.classList.add('mf-toast--visible');
    });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () {
        if (t.parentNode) t.parentNode.removeChild(t);
      }, 250);
    }, 2400);
  }

  function openDisplayDrawer() {
    if (typeof MFDisplayPrefsDrawer !== 'undefined') {
      MFDisplayPrefsDrawer.create().open();
      return;
    }
    var src = '/static/js/components/display-prefs-drawer.js';
    var existing = document.querySelector('script[src="' + src + '"]');
    if (existing) {
      existing.addEventListener('load', function () { MFDisplayPrefsDrawer.create().open(); });
      return;
    }
    var s = document.createElement('script');
    s.src = src;
    s.onload  = function () { MFDisplayPrefsDrawer.create().open(); };
    s.onerror = function () { showToast('Display preferences unavailable'); };
    document.head.appendChild(s);
  }

  function handleSelect(id, pageSet) {
    if (id === 'display') {
      openDisplayDrawer();
      return;
    }

    var urls = pageSet === 'new' ? URLS_NEW : URLS_ORIGINAL;
    if (urls[id]) {
      window.location.href = urls[id];
      return;
    }

    var label = COMING_SOON[id] || id;
    showToast(label + ' — coming soon');
  }

  function handleSignOut() {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
      .finally(function () { window.location.href = '/'; });
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFAvatarMenuWiring.mount: slot is required');
    if (typeof MFAvatarMenu === 'undefined' || typeof MFAvatar === 'undefined') {
      throw new Error('MFAvatarMenuWiring.mount: MFAvatarMenu and MFAvatar must be loaded first');
    }

    var user    = (opts && opts.user)    || { name: '', role: 'member' };
    var build   = (opts && opts.build)   || null;
    var pageSet = (opts && opts.pageSet) || 'new';

    var menu = MFAvatarMenu.create({
      user:  user,
      build: build,
      onSelectItem: function (id) { handleSelect(id, pageSet); },
      onSignOut:    handleSignOut
    });

    MFAvatar.mount(slot, {
      user: user,
      onClick: function (btn) { menu.openAt(btn); }
    });

    return { menu: menu };
  }

  global.MFAvatarMenuWiring = { mount: mount };
})(window);
