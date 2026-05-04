/* Boot script for the AI Providers settings detail page (Plan 6 Task 2).
 * Fetches /api/me + provider list + registry; mounts chrome + MFAIProvidersDetail.
 *
 * Members are redirected to /. Provider APIs return 403 for non-admins;
 * fetchOrEmpty handles that gracefully with empty fallbacks.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var aiRoot = document.getElementById('mf-ai-providers');

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        console.warn('mf: /api/me failed; falling back to member', e);
        return {
          user_id: 'dev', name: 'dev', role: 'member', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }

  function fetchOrEmpty(url, fallback) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) {
          console.warn('mf: ' + url + ' returned 403 (insufficient role)');
          return fallback;
        }
        if (!r.ok) throw new Error(url + ' failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        console.warn('mf: ' + url + ' fetch error, using fallback', e);
        return fallback;
      });
  }

  Promise.all([
    MFPrefs.load(),
    fetchMe(),
    fetchOrEmpty('/api/llm-providers', { providers: [] }),
    fetchOrEmpty('/api/llm-providers/registry', { registry: [] }),
    fetchOrEmpty('/api/preferences', {}),
  ]).then(function (results) {
    var me = results[1];
    var providersData = results[2];
    var registryData = results[3];
    var prefsData = results[4];

    if (me.role === 'member') {
      window.location.href = '/';
      return;
    }

    var build = me.build;
    var user = { name: me.name, role: me.role, scope: me.scope };

    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'popover' });
      },
    });

    MFTopNav.mount(navRoot, { role: me.role, activePage: 'settings' });
    MFVersionChip.mount(
      navRoot.querySelector('[data-mf-slot="version-chip"]'),
      { version: build.version }
    );
    MFAvatarMenuWiring.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, build: build, pageSet: 'new' }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    var providers = providersData.providers || providersData.items || providersData || [];
    // API returns registry as a dict keyed by type; convert to array expected by component
    var rawRegistry = registryData.registry || registryData || {};
    var registry = Array.isArray(rawRegistry)
      ? rawRegistry
      : Object.keys(rawRegistry).map(function (type) {
          return Object.assign({ type: type }, rawRegistry[type]);
        });

    var prefs = prefsData.preferences || prefsData || {};
    MFAIProvidersDetail.mount(aiRoot, { providers: providers, registry: registry, prefs: prefs });

  }).catch(function (e) {
    console.error('mf: ai-providers-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'AI provider settings unavailable. Check console.';
    if (aiRoot) aiRoot.appendChild(msg);
  });
})();
