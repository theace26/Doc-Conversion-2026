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

  function _normalizeRates(rateData) {
    var flat = [];
    var nested = rateData && rateData.rates;
    if (!nested || Array.isArray(nested)) return flat;
    var providers = Object.keys(nested);
    for (var pi = 0; pi < providers.length; pi++) {
      var provName = providers[pi];
      var models = nested[provName];
      if (!models || typeof models !== 'object') continue;
      var modelKeys = Object.keys(models);
      for (var mi = 0; mi < modelKeys.length; mi++) {
        var modelName = modelKeys[mi];
        var r = models[modelName];
        if (!r || typeof r !== 'object') continue;
        flat.push({
          provider: r.provider || provName,
          model: r.model || modelName,
          input_per_1m: r.input_per_million_usd != null ? r.input_per_million_usd : null,
          output_per_1m: r.output_per_million_usd != null ? r.output_per_million_usd : null,
          cache_write_per_1m: r.cache_write_per_million_usd != null ? r.cache_write_per_million_usd : null,
          cache_read_per_1m: r.cache_read_per_million_usd != null ? r.cache_read_per_million_usd : null,
          effective_date: r.effective_date || null,
        });
      }
    }
    return flat;
  }

  function _normalizePeriod(period) {
    var rawByModel = period.by_model || {};
    var byModelArr = [];
    if (!Array.isArray(rawByModel)) {
      var keys = Object.keys(rawByModel);
      for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        var usd = rawByModel[key];
        var parts = key.split('/');
        var prov = parts.length >= 2 ? parts[0] : '';
        var mod = parts.length >= 2 ? parts.slice(1).join('/') : parts[0];
        byModelArr.push({ provider: prov, model: mod, input_tokens: null, output_tokens: null, usd: usd });
      }
    } else {
      byModelArr = rawByModel;
    }
    return {
      total_usd: period.total_cost_usd != null ? period.total_cost_usd : (period.total_usd || 0),
      by_provider: period.by_provider || {},
      by_model: byModelArr,
      daily: [],
    };
  }

  Promise.all([
    MFPrefs.load(),
    fetchMe(),
    fetchOrEmpty('/api/admin/llm-costs', { rates: {} }),
    fetchOrEmpty('/api/analysis/cost/period', { total_cost_usd: 0, by_provider: {}, by_model: {} }),
    fetchOrEmpty('/api/analysis/cost/period?days=30', { total_cost_usd: 0, by_provider: {}, by_model: {} }),
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

    var rateTable = _normalizeRates(rateData);

    var providerSet = {};
    var providers = [];
    rateTable.forEach(function (row) {
      if (row.provider && !providerSet[row.provider]) {
        providerSet[row.provider] = true;
        providers.push(row.provider);
      }
    });
    providers.sort();

    var periodNorm = _normalizePeriod(period);
    var period30Norm = _normalizePeriod(period30);

    var prefs = prefsData.preferences || prefsData || {};

    MFCostCapDetail.mount(costRoot, {
      rateTable: rateTable,
      period: periodNorm,
      period30: period30Norm,
      staleness: staleness,
      providers: providers,
      prefs: prefs,
    });

  }).catch(function (e) {
    console.error('mf: cost-cap-settings boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:var(--mf-color-text-muted);font-family:sans-serif';
    msg.textContent = 'Cost settings unavailable. Check console.';
    if (costRoot) costRoot.appendChild(msg);
  });
})();
