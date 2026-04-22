/**
 * storage-restart-banner.js — Amber "restart required" banner (v0.25.0)
 *
 * Polls /api/storage/restart-status once a minute. When a reason is set
 * and the dismiss window hasn't expired, injects an amber banner at the
 * top of <body>. "Remind me later" snoozes for 1 hour via POST
 * /api/storage/restart-dismiss.
 *
 * Included on every page via <script src="/static/js/storage-restart-banner.js" defer>.
 */
(function () {
  'use strict';

  const BANNER_ID = 'storage-restart-banner';
  const POLL_MS = 60000;

  function parseUTCSafe(iso) {
    if (!iso) return null;
    if (window.parseUTC) return window.parseUTC(iso);
    return new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
  }

  function relTime(d) {
    if (!d) return '';
    const diffSec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} h ago`;
    return `${Math.floor(diffSec / 86400)} d ago`;
  }

  function hideBanner() {
    const b = document.getElementById(BANNER_ID);
    if (b) b.remove();
  }

  function showBanner(reason, sinceISO) {
    let banner = document.getElementById(BANNER_ID);
    if (!banner) {
      banner = document.createElement('div');
      banner.id = BANNER_ID;
      banner.className = 'restart-banner';
      document.body.prepend(banner);
    }
    while (banner.firstChild) banner.removeChild(banner.firstChild);

    const title = document.createElement('strong');
    title.textContent = 'RESTART REQUIRED — ';
    const msg = document.createElement('span');
    msg.textContent = reason;
    const meta = document.createElement('span');
    meta.className = 'meta';
    const since = parseUTCSafe(sinceISO);
    meta.textContent = since ? ` (changed ${relTime(since)})` : '';

    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'btn btn-sm btn-ghost';
    dismiss.textContent = 'Remind me later';
    dismiss.addEventListener('click', async () => {
      try {
        await fetch('/api/storage/restart-dismiss', { method: 'POST' });
      } catch { /* ignore */ }
      hideBanner();
    });

    banner.appendChild(title);
    banner.appendChild(msg);
    banner.appendChild(meta);
    banner.appendChild(dismiss);
  }

  async function poll() {
    try {
      const r = await fetch('/api/storage/restart-status');
      if (r.status === 401 || r.status === 403) return;
      if (!r.ok) return;
      const { reason, since, dismissed_until } = await r.json();
      if (!reason) { hideBanner(); return; }
      if (dismissed_until) {
        const until = parseUTCSafe(dismissed_until);
        if (until && until.getTime() > Date.now()) { hideBanner(); return; }
      }
      showBanner(reason, since);
    } catch { /* ignore */ }
  }

  function start() {
    poll();
    setInterval(poll, POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
