/* Operations page component (new-UX).
 *
 * Consolidates the Active Jobs (/status) and Trends (/activity) surfaces
 * under a single tabbed page. Each sub-component is defer-mounted on first
 * tab click and cached so switching tabs does not re-poll.
 *
 * Usage:
 *   MFOperations.mount(root, { role });
 *
 * Requires MFStatus and MFActivity to be loaded before this script.
 *
 * Safe DOM throughout — no innerHTML with template strings.
 */
(function (global) {
  'use strict';

  /* ── Helpers ──────────────────────────────────────────────────────────── */

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  /* ── Mount ──────────────────────────────────────────────────────────────── */

  function mount(root, opts) {
    if (!root) throw new Error('MFOperations.mount: root element is required');

    var role        = (opts && opts.role) || 'operator';
    var activeTab   = 'active';

    /* Cache for mounted sub-components. Keyed by tab id.
     * Stores { container: Element, instance: Object|null } */
    var cache = {};

    /* ── Outer wrapper ──────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-operations');

    /* ── Tab strip ──────────────────────────────────────────────────────── */

    var tabStrip = el('div', 'mf-operations__tabs');

    var TAB_DEFS = [
      { id: 'active', label: 'Active now' },
      { id: 'trends', label: 'Trends'     },
    ];

    var tabButtons = {};

    TAB_DEFS.forEach(function (def) {
      var btn = el('button', 'mf-operations__tab');
      btn.textContent = def.label;
      btn.setAttribute('type', 'button');
      btn.setAttribute('data-tab', def.id);
      if (def.id === activeTab) btn.classList.add('mf-operations__tab--active');
      btn.addEventListener('click', function () { switchTab(def.id); });
      tabStrip.appendChild(btn);
      tabButtons[def.id] = btn;
    });

    wrapper.appendChild(tabStrip);

    /* ── Tab body ───────────────────────────────────────────────────────── */

    var body = el('div', 'mf-operations__body');
    wrapper.appendChild(body);

    root.appendChild(wrapper);

    /* ── Tab mounting helpers ───────────────────────────────────────────── */

    function mountActive(container) {
      /* MFStatus.mount polls internally — just hand it the container. */
      var instance = MFStatus.mount(container, { role: role });
      return instance || null;
    }

    function mountTrends(container) {
      /* MFActivity needs /api/activity/summary. Fetch it, then mount.
       * Re-fetch and refresh on a 30-second interval so the tab stays live
       * even when it is not the default. */
      fetch('/api/activity/summary', { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('activity summary: ' + r.status);
          return r.json();
        })
        .then(function (summary) {
          MFActivity.mount(container, { summary: summary, role: role });

          /* Store poll timer reference so destroy() can clear it. */
          var timer = setInterval(function () {
            fetch('/api/activity/summary', { credentials: 'same-origin' })
              .then(function (r) {
                if (!r.ok) throw new Error('activity summary poll: ' + r.status);
                return r.json();
              })
              .then(function (s) { MFActivity.refresh(container, s); })
              .catch(function (e) { console.warn('mf-operations: activity poll failed', e); });
          }, 30000);

          /* Stash timer for cleanup. */
          var entry = cache['trends'];
          if (entry) entry.pollTimer = timer;
        })
        .catch(function (e) {
          console.error('mf-operations: activity summary fetch failed', e);
          var msg = el('div');
          msg.style.cssText = 'padding:2rem;text-align:center;color:var(--mf-color-text-muted);font-family:var(--mf-font-family)';
          msg.textContent = 'Trends unavailable. Check console.';
          container.appendChild(msg);
        });

      return null; /* instance created asynchronously */
    }

    /* ── switchTab ──────────────────────────────────────────────────────── */

    function switchTab(tabId) {
      if (tabId === activeTab) return;

      /* Update button states. */
      Object.keys(tabButtons).forEach(function (id) {
        if (id === tabId) {
          tabButtons[id].classList.add('mf-operations__tab--active');
        } else {
          tabButtons[id].classList.remove('mf-operations__tab--active');
        }
      });

      activeTab = tabId;

      /* Hide all cached containers. */
      Object.keys(cache).forEach(function (id) {
        cache[id].container.style.display = 'none';
      });

      /* Show or create the target container. */
      if (cache[tabId]) {
        cache[tabId].container.style.display = '';
        return;
      }

      /* First visit — create container and mount sub-component. */
      var container = el('div', 'mf-operations__tab-panel');
      container.setAttribute('data-tab-panel', tabId);
      body.appendChild(container);

      var entry = { container: container, instance: null, pollTimer: null };
      cache[tabId] = entry;

      if (tabId === 'active') {
        entry.instance = mountActive(container);
      } else if (tabId === 'trends') {
        mountTrends(container);
      }
    }

    /* ── Mount the default tab immediately ─────────────────────────────── */

    (function mountDefault() {
      var container = el('div', 'mf-operations__tab-panel');
      container.setAttribute('data-tab-panel', activeTab);
      body.appendChild(container);

      var entry = { container: container, instance: null, pollTimer: null };
      cache[activeTab] = entry;

      entry.instance = mountActive(container);
    })();

    /* ── Return instance ─────────────────────────────────────────────────── */

    return {
      destroy: function () {
        Object.keys(cache).forEach(function (id) {
          var entry = cache[id];
          if (entry.pollTimer) clearInterval(entry.pollTimer);
          if (entry.instance && typeof entry.instance.destroy === 'function') {
            entry.instance.destroy();
          }
        });
      },
    };
  }

  /* ── Export ─────────────────────────────────────────────────────────────── */

  global.MFOperations = { mount: mount };

})(window);
