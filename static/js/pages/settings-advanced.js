/* Advanced Settings hub. Links admin tools: log viewer, log mgmt, log levels, db health.
 *
 * Usage:
 *   MFSettingsAdvanced.mount(slot);
 *
 * Safe DOM throughout. */
(function (global) {
  'use strict';

  var CARDS = [
    {
      icon: '\u{1F4DC}',
      label: 'Log Viewer',
      desc: 'Live tail and historical search across all MarkFlow log files.',
      href: '/log-viewer',
    },
    {
      icon: '\u{1F4E6}',
      label: 'Log Management',
      desc: 'File rotation, compression format, retention period, and manual triggers.',
      href: '/log-mgmt',
    },
    {
      icon: '\u{1F527}',
      label: 'Log Levels',
      desc: 'Per-logger debug level configuration. Changes take effect immediately.',
      href: '/log-levels',
    },
    {
      icon: '\u{1F489}',
      label: 'Database Health',
      desc: 'Integrity checks, WAL stats, compaction history, and orphan reaper status.',
      href: '/settings/db-health',
    },
  ];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function buildCard(card) {
    var a = document.createElement('a');
    a.className = 'mf-settings__card';
    a.href = card.href;

    var arrow = el('span', 'mf-settings__card-arrow');
    arrow.textContent = '→';
    a.appendChild(arrow);

    var icon = el('div', 'mf-settings__card-icon');
    icon.textContent = card.icon;
    a.appendChild(icon);

    var title = el('h4', 'mf-settings__card-title');
    title.textContent = card.label;
    a.appendChild(title);

    var desc = el('p', 'mf-settings__card-desc');
    desc.textContent = card.desc;
    a.appendChild(desc);

    return a;
  }

  function mount(slot) {
    if (!slot) throw new Error('MFSettingsAdvanced.mount: slot required');

    var body = el('div', 'mf-settings__body');

    var back = document.createElement('a');
    back.className = 'mf-settings__back-link';
    back.href = '/settings';
    back.textContent = '← Settings';
    body.appendChild(back);

    var headline = el('h1', 'mf-settings__headline');
    headline.textContent = 'Advanced.';
    body.appendChild(headline);

    var subtitle = el('p', 'mf-settings__subtitle');
    subtitle.textContent = 'System logs, debug controls, and database health.';
    body.appendChild(subtitle);

    var grid = el('div', 'mf-settings__grid');
    CARDS.forEach(function (card) { grid.appendChild(buildCard(card)); });
    body.appendChild(grid);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsAdvanced = { mount: mount };
})(window);
