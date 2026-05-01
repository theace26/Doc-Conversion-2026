/* Settings overview card grid. Spec §7.
 *
 * Usage:
 *   MFSettingsOverview.mount(slot, { role });
 *
 * Cards are role-gated: members see Display, Pinned folders, Profile only.
 * Operators/admins see all cards. Safe DOM throughout.
 */
(function (global) {
  'use strict';

  var ALL_CARDS = [
    {
      id: 'storage',
      icon: '\u{1F5C4}',
      label: 'Storage',
      desc: 'Where files come from and go to. SMB / NFS mounts, output paths, cloud prefetch, credentials.',
      href: '/settings/storage',
      adminOnly: true,
    },
    {
      id: 'pipeline',
      icon: '\u{2699}',
      label: 'Pipeline',
      desc: 'Scan windows, lifecycle timing, scheduler behavior, write guard.',
      href: '/settings/pipeline',
      adminOnly: true,
    },
    {
      id: 'appearance',
      icon: '\u{1F3A8}',
      label: 'Appearance',
      desc: 'Default theme, UX mode, and whether users can customize their own display.',
      href: '/settings/appearance',
      adminOnly: true,
    },
    {
      id: 'ai-providers',
      icon: '\u{1F9E0}',
      label: 'AI Providers',
      desc: 'Anthropic key, image-analysis routing, cost ceiling, vector indexing.',
      href: '/settings/ai-providers',
      adminOnly: true,
    },
    {
      id: 'auth',
      icon: '\u{1F512}',
      label: 'Account & Auth',
      desc: 'JWT, sign-in, role hierarchy, API keys.',
      href: '/settings/auth',
      adminOnly: true,
    },
    {
      id: 'notifications',
      icon: '\u{1F514}',
      label: 'Notifications',
      desc: 'What pages a job to oncall. Slack / email / silence.',
      href: '/settings/notifications',
      adminOnly: false,
    },
    {
      id: 'advanced',
      icon: '\u{1F527}',
      label: 'Advanced',
      desc: 'Database maintenance, log management, debug toggles.',
      href: '/settings/advanced',
      adminOnly: true,
    },
    {
      id: 'display',
      icon: '\u{1F5A5}',
      label: 'Display',
      desc: 'Layout mode, density, power-user gate, show thumbnails.',
      href: '/settings/display',
      adminOnly: false,
    },
    {
      id: 'profile',
      icon: '\u{1F464}',
      label: 'Profile',
      desc: 'Your identity, recent searches, preferences.',
      href: '/settings/profile',
      adminOnly: false,
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

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSettingsOverview.mount: slot is required');
    var role = (opts && opts.role) || 'member';
    var isOperator = role === 'operator' || role === 'admin';

    var body = el('div', 'mf-settings__body');

    var headline = el('h1', 'mf-settings__headline');
    headline.textContent = 'Settings.';
    body.appendChild(headline);

    var subtitle = el('p', 'mf-settings__subtitle');
    subtitle.textContent = 'Configure the things that matter. The rest is sensible defaults.';
    body.appendChild(subtitle);

    var grid = el('div', 'mf-settings__grid');
    ALL_CARDS.forEach(function (card) {
      if (card.adminOnly && !isOperator) return;
      grid.appendChild(buildCard(card));
    });
    body.appendChild(grid);

    while (slot.firstChild) slot.removeChild(slot.firstChild);
    slot.appendChild(body);
  }

  global.MFSettingsOverview = { mount: mount };
})(window);
