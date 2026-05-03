/* Boot script for the Activity dashboard (new-UX shell).
 * Fetches /api/me; mounts chrome. Then fetches /api/activity/summary
 * and mounts MFActivity. Polls summary every 30s for live updates.
 *
 * Chrome (nav) is mounted before summary data arrives so the page is
 * never blank while waiting on the activity API.
 *
 * Safe DOM throughout. */
(function () {
  'use strict';

  /* ── Mount-point references ─────────────────────────────────────────────── */

  var navRoot  = document.getElementById('mf-top-nav');
  var pageRoot = document.getElementById('mf-activity-page');

  var POLL_INTERVAL = 30000;


  /* ── /api/me helper ─────────────────────────────────────────────────────── */

  function fetchMe() {
    return fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('me fetch failed: ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        /* Dev / offline fallback. Real auth returns a 401 via get_current_user;
         * this fires only when /api/me is reachable but errors unexpectedly. */
        console.warn('mf: /api/me failed; falling back to operator', e);
        return {
          user_id: 'dev', name: 'dev', role: 'operator', scope: '',
          build: { version: 'unknown', branch: 'unknown', sha: 'unknown', date: 'dev' },
        };
      });
  }


  /* ── /api/activity/summary helper ──────────────────────────────────────── */

  function fetchSummary() {
    return fetch('/api/activity/summary', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('summary fetch failed: ' + r.status);
        return r.json();
      });
  }


  /* ── Boot ───────────────────────────────────────────────────────────────── */

  Promise.all([MFPrefs.load(), fetchMe()]).then(function (results) {
    var me    = results[1];
    var build = me.build;
    var user  = { name: me.name, role: me.role, scope: me.scope };

    if (me.role === 'member') {
      /* Member shouldn't see this page — redirect home. */
      window.location.href = '/';
      return;
    }

    /* Layout popover (density / card size) */
    var layoutPop = MFLayoutPopover.create({
      current: MFPrefs.get('layout') || 'minimal',
      onChoose: function (mode) {
        MFPrefs.set('layout', mode);
        MFTelemetry.emit('ui.layout_mode_selected', { mode: mode, source: 'activity_popover' });
      },
    });

    /* Mount chrome immediately — before summary data arrives. */
    MFTopNav.mount(navRoot, { role: me.role, activePage: 'activity' });

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

    /* Fetch summary data separately so a slow/failing activity API does not
     * prevent the nav chrome from rendering. */
    fetchSummary()
      .then(function (summary) {
        MFActivity.mount(pageRoot, { summary: summary, role: me.role });

        /* Poll for fresh data every 30s. */
        setInterval(function () {
          fetchSummary()
            .then(function (s) { MFActivity.refresh(pageRoot, s); })
            .catch(function (e) { console.warn('mf: activity poll failed', e); });
        }, POLL_INTERVAL);
      })
      .catch(function (e) {
        console.error('mf: activity summary fetch failed', e);
        var msg = document.createElement('div');
        msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
        msg.textContent = 'Activity dashboard unavailable. Check console.';
        if (pageRoot) pageRoot.appendChild(msg);
      });

  }).catch(function (e) {
    console.error('mf: activity boot failed', e);
    var msg = document.createElement('div');
    msg.style.cssText = 'padding:2rem;text-align:center;color:#888;font-family:sans-serif';
    msg.textContent = 'Activity dashboard unavailable. Check console.';
    if (pageRoot) pageRoot.appendChild(msg);
  });
})();
