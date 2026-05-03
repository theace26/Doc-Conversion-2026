/* ============================================================
   NEW-UX PAGE COMPONENT TEMPLATE (vanilla JS, safe DOM)
   ============================================================
   How to use this file:
     1. Copy to static/js/pages/{{PAGE_ID}}.js
        (e.g. static/js/pages/history.js)
     2. Replace every {{PLACEHOLDER}} with a real value.
     3. The global name MF{{COMPONENT_NAME}} must match the call
        in your boot script (new-ux-page-boot.js).

   Conventions:
     - Safe DOM throughout: use document.createElement / textContent.
       Do NOT use innerHTML with template literals or user data.
     - All state lives in the closure; no global mutable state.
     - Poll loops use setInterval / clearInterval; clean up on unmount.
     - Errors surface inline (never alert/confirm).

   REPLACE THIS: all {{...}} markers below.
   ============================================================ */
(function (global) {
  'use strict';

  /* ── Helpers ───────────────────────────────────────────────────────────── */

  /* Create an element with an optional class name. */
  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  /* Show a brief toast (uses mf-toast CSS from components.css). */
  function showToast(msg, type) {
    var t = el('div', 'mf-toast mf-toast--' + (type || 'info'));
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('mf-toast--visible'); });
    setTimeout(function () {
      t.classList.remove('mf-toast--visible');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, 2500);
  }

  /* Clear all children from a node. */
  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }


  /* ── API helpers ────────────────────────────────────────────────────────── */

  /* REPLACE THIS: update the endpoint constants for your page. */
  var API_LIST    = '/api/{{PAGE_ID}}';         /* GET — main data list */
  var API_DETAIL  = '/api/{{PAGE_ID}}/';        /* GET /:id — item detail */


  /* ── State ──────────────────────────────────────────────────────────────── */

  /* State lives inside mount() so each mounted instance is independent. */


  /* ── Render helpers ─────────────────────────────────────────────────────── */

  /* REPLACE THIS: render a single item row (adapt to your data shape). */
  function renderItem(item) {
    var row = el('div', 'mf-card');

    var title = el('div', 'mf-card__title');
    /* REPLACE THIS: use the relevant field from your API response */
    title.textContent = item.name || item.id || '(unnamed)';
    row.appendChild(title);

    var meta = el('div', 'mf-card__meta');
    /* REPLACE THIS: show relevant metadata */
    meta.textContent = item.created_at || '';
    row.appendChild(meta);

    return row;
  }

  /* REPLACE THIS: render the empty state (no items). */
  function renderEmpty(container, msg) {
    clear(container);
    var empty = el('div', 'mf-empty-state');
    var text = el('p');
    text.textContent = msg || 'Nothing here yet.';
    empty.appendChild(text);
    container.appendChild(empty);
  }

  /* REPLACE THIS: render an error state. */
  function renderError(container, msg) {
    clear(container);
    var err = el('div', 'mf-empty-state');
    var text = el('p');
    text.style.color = 'var(--mf-color-error)';
    text.textContent = msg || 'Failed to load data. Check the console.';
    err.appendChild(text);
    container.appendChild(err);
  }


  /* ── Mount ───────────────────────────────────────────────────────────────── */

  /**
   * mount(root, opts)
   *
   * Renders the page inside `root`. Called once by the boot script.
   *
   * @param {HTMLElement} root - The div from the HTML file (e.g. #mf-history-page)
   * @param {object}      opts - { role: 'member' | 'operator' | 'admin' }
   */
  function mount(root, opts) {
    if (!root) throw new Error('MF{{COMPONENT_NAME}}.mount: root element is required');

    var role = (opts && opts.role) || 'member';

    /* ── Build skeleton ─────────────────────────────────────────────────── */

    var wrapper = el('div', 'mf-page-wrapper');

    /* Page header */
    var header = el('div', 'mf-page-header');
    var heading = el('h1', 'mf-page-title');
    /* REPLACE THIS: use your page title */
    heading.textContent = '{{PAGE_TITLE}}';
    header.appendChild(heading);

    /* REPLACE THIS: add action buttons to the header if needed (admin-gated example) */
    if (role === 'admin' || role === 'operator') {
      var actionsBar = el('div', 'mf-page-header__actions');
      var refreshBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      refreshBtn.textContent = 'Refresh';
      refreshBtn.addEventListener('click', function () { loadData(); });
      actionsBar.appendChild(refreshBtn);
      header.appendChild(actionsBar);
    }

    wrapper.appendChild(header);

    /* Content area */
    var content = el('div', 'mf-page-content');
    wrapper.appendChild(content);

    root.appendChild(wrapper);

    /* ── Poll / load ────────────────────────────────────────────────────── */

    var pollTimer = null;

    function loadData() {
      fetch(API_LIST, { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('API error: ' + r.status);
          return r.json();
        })
        .then(function (data) {
          renderList(data);
        })
        .catch(function (e) {
          console.error('MF{{COMPONENT_NAME}}: load failed', e);
          renderError(content, 'Could not load data — check the console.');
        });
    }

    function renderList(data) {
      clear(content);

      /* REPLACE THIS: adapt to your API response shape.
       * Common patterns:
       *   - data is an array         → use data directly
       *   - data.items is the array  → use data.items
       *   - data.results             → use data.results        */
      var items = Array.isArray(data) ? data : (data.items || data.results || []);

      if (!items.length) {
        renderEmpty(content, 'No {{PAGE_TITLE}} found.');
        return;
      }

      var list = el('div', 'mf-card-list');
      for (var i = 0; i < items.length; i++) {
        list.appendChild(renderItem(items[i]));
      }
      content.appendChild(list);
    }

    /* REPLACE THIS: set the polling interval in ms, or set to 0 to disable. */
    var POLL_MS = 0;  /* e.g. 15000 for a 15-second auto-refresh */

    if (POLL_MS > 0) {
      pollTimer = setInterval(function () {
        if (!document.hidden) loadData();
      }, POLL_MS);

      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) loadData();
      });
    }

    /* Initial load */
    loadData();

    /* ── Return control handle (optional) ──────────────────────────────── */
    /* Expose refresh() so the boot script can trigger reloads if needed. */
    return {
      refresh: loadData,
      destroy: function () {
        if (pollTimer) clearInterval(pollTimer);
      }
    };
  }

  /* ── Export ────────────────────────────────────────────────────────────── */

  /* REPLACE THIS: update the global name to match MF{{COMPONENT_NAME}} */
  global.MF{{COMPONENT_NAME}} = { mount: mount };

})(window);
