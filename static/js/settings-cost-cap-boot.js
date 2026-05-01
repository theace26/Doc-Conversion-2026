/* Boot script for the Cost & Spend settings detail page (Plan 7 Task 1).
 * Fetches /api/me + rate table + 7d period + 30d period + staleness + preferences
 * in parallel. Members are redirected to /. Operators+ see the full page.
 * fetchOrEmpty handles 403 gracefully with empty fallbacks.
 * Safe DOM throughout. */
(function () {
  'use strict';

  var navRoot = document.getElementById('mf-top-nav');
  var costRoot = document.getElementById('mf-cost-cap');

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
    fetchOrEmpty('/api/admin/llm-costs', { rates: [] }),
    fetchOrEmpty('/api/analysis/cost/period', { total_usd: 0, by_provider: {}, by_model: [], daily: [] }),
    fetchOrEmpty('/api/analysis/cost/period?days=30', { total_usd: 0, by_provider: {}, by_model: [], daily: [] }),
    fetchOrEmpty('/api/analysis/cost/staleness', { is_stale: false, age_days: 0 }),
    fetchOrEmpty('/api/preferences', {}),
  ]).then(function (results) {
    var me = results[1];
    var rateData = results[2];
    var period = results[3];
    var period30 = results[4];
    var staleness = results[5];
    var prefsData = results[6];

    if (me.role === 'member') {
      window.location.href = '/';
      return;
    }

    var build = me.build;
    var user = { name: me.name, role: me.role, scope: me.scope };

    var avatarMenu = MFAvatarMenu.create({
      user: user,
      build: build,
      onSelectItem: function (id) { console.log('avatar item:', id); },
      onSignOut: function () {
        fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
          .finally(function () { window.location.href = '/'; });
      },
    });

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
    MFAvatar.mount(
      navRoot.querySelector('[data-mf-slot="avatar"]'),
      { user: user, onClick: function (btn) { avatarMenu.openAt(btn); } }
    );
    MFLayoutIcon.mount(
      navRoot.querySelector('[data-mf-slot="layout-icon"]'),
      { onClick: function (btn) { layoutPop.openAt(btn); } }
    );

    var rateTable = rateData.rates || [];

    var providerSet = {};
    var providers = [];
    rateTable.forEach(function (row) {
      if (row.provider && !providerSet[row.provider]) {
        providerSet[row.provider] = true;
        providers.push(row.provider);
      }
    });
    providers.sort();

    var prefs = prefsData.preferences || prefsData || {};

    MFCostCapDetail.mount(costRoot, {
      rateTable: rateTable,
      period: period,
      period30: period30,
      staleness: staleness,
      providers: providers,
      prefs: prefs,
    });

  }).catch(function (e) {
    console.error('mf: cost-cap-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Cost settings unavailable. Check console.';
    if (costRoot) costRoot.appendChild(msg);
  });
})();
