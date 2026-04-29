/* Hover preview popover for document cards.
 * Spec §4 (anatomy). 400ms hover delay. Body-mounted to escape
 * overflow:hidden ancestors.
 *
 * Usage:
 *   var hp = MFHoverPreview.create({
 *     onAction: function(action, doc) { ... }   // 'preview' | 'download' | 'goto-folder' | 'more'
 *   });
 *   hp.armOn(cardEl, doc);   // arms hover trigger; 400ms after enter -> show
 *   hp.disarm(cardEl);       // remove the listeners
 *
 * Safe DOM throughout — every text via textContent.
 */
(function (global) {
  'use strict';

  var DELAY_MS = 600;
  var CLOSE_DELAY_MS = 300;

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function build(doc, onAction, onClose) {
    var root = el('div', 'mf-hover-preview');
    root.setAttribute('role', 'tooltip');

    var title = el('h3', 'mf-hover-preview__title');
    title.textContent = doc.title || '(untitled)';
    root.appendChild(title);

    var path = el('div', 'mf-hover-preview__path');
    path.textContent = doc.path || '';
    root.appendChild(path);

    // Meta grid
    var grid = el('div', 'mf-hover-preview__grid');
    var rows = [
      ['Format', formatLine(doc)],
      ['Modified', doc.modified_human || formatStamp(doc.modified) || '-'],
      ['Indexed', doc.indexed_status || '-'],
      ['Opens', doc.opens != null ? String(doc.opens) + ' in last 7 days' : '-'],
      ['Status', doc.status || '-'],
    ];
    rows.forEach(function (pair) {
      var k = el('span', 'mf-hover-preview__k'); k.textContent = pair[0];
      var v = el('span', 'mf-hover-preview__v'); v.textContent = pair[1];
      grid.appendChild(k); grid.appendChild(v);
    });
    root.appendChild(grid);

    if (doc.ai_summary) {
      var summary = el('div', 'mf-hover-preview__summary');
      var lab = el('div', 'mf-hover-preview__summary-lab');
      lab.textContent = 'AI Summary';
      summary.appendChild(lab);
      summary.appendChild(document.createTextNode(doc.ai_summary));
      root.appendChild(summary);
    }

    var actions = el('div', 'mf-hover-preview__actions');
    [
      { id: 'preview',   label: 'Preview',       primary: true },
      { id: 'download',  label: 'Download' },
      { id: 'goto-folder', label: 'Go to folder' },
      { id: 'more',      label: '…' },
    ].forEach(function (a) {
      var b = el('button', 'mf-hover-preview__btn' + (a.primary ? ' mf-hover-preview__btn--primary' : ''));
      b.type = 'button';
      b.textContent = a.label;
      b.setAttribute('data-action', a.id);
      b.addEventListener('click', function () {
        if (typeof onAction === 'function') onAction(a.id, doc);
        if (typeof onClose === 'function') onClose();
      });
      actions.appendChild(b);
    });
    root.appendChild(actions);

    return root;
  }

  function formatLine(doc) {
    var parts = [];
    if (doc.format) parts.push(String(doc.format).toUpperCase());
    if (typeof doc.size === 'number') {
      parts.push((typeof MFDocCard !== 'undefined' && MFDocCard.formatSize)
        ? MFDocCard.formatSize(doc.size)
        : doc.size + ' B');
    }
    return parts.length ? parts.join(' · ') : '-';
  }
  function formatStamp(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  function create(opts) {
    var onAction = (opts && opts.onAction) || function () {};
    var current = null;       // { card, popover, doc }
    var openTimer = null;
    var closeTimer = null;

    function cancelClose() {
      if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    }

    function scheduleClose() {
      cancelClose();
      closeTimer = setTimeout(closeNow, CLOSE_DELAY_MS);
    }

    function closeNow() {
      cancelClose();
      if (openTimer) { clearTimeout(openTimer); openTimer = null; }
      if (current && current.popover && current.popover.parentNode) {
        current.popover.parentNode.removeChild(current.popover);
      }
      if (current && current.card) {
        current.card.removeAttribute('data-mf-hover-active');
      }
      current = null;
    }

    // Public close (immediate) — used by action buttons and disarm.
    function close() { closeNow(); }

    function show(card, doc) {
      closeNow();
      var pop = build(doc, onAction, close);
      pop.style.position = 'absolute';
      document.body.appendChild(pop);
      anchor(pop, card);
      card.setAttribute('data-mf-hover-active', 'true');
      current = { card: card, popover: pop, doc: doc };
      // Keep popover open while mouse is over it.
      pop.addEventListener('mouseenter', cancelClose);
      pop.addEventListener('mouseleave', scheduleClose);
      MFTelemetry && MFTelemetry.emit && MFTelemetry.emit(
        'ui.hover_preview_shown', { doc_id: doc.id || '' }
      );
    }

    function anchor(pop, card) {
      var r = card.getBoundingClientRect();
      var width = 340;
      var spaceRight = document.documentElement.clientWidth - r.right;
      var spaceTop = r.top;
      // Default: anchor to card's right side, vertically aligned to its top
      pop.style.width = width + 'px';
      if (spaceRight > width + 16) {
        pop.style.left = (window.scrollX + r.right + 12) + 'px';
        pop.style.top = (window.scrollY + r.top - 12) + 'px';
      } else if (spaceTop > 280) {
        // Anchor above
        pop.style.left = (window.scrollX + r.left) + 'px';
        pop.style.top = (window.scrollY + r.top - 280) + 'px';
      } else {
        // Anchor below
        pop.style.left = (window.scrollX + r.left) + 'px';
        pop.style.top = (window.scrollY + r.bottom + 12) + 'px';
      }
    }

    function armOn(card, doc) {
      function onEnter() {
        cancelClose();
        if (openTimer) clearTimeout(openTimer);
        openTimer = setTimeout(function () { show(card, doc); }, DELAY_MS);
      }
      function onLeave() {
        if (openTimer) { clearTimeout(openTimer); openTimer = null; }
        if (current && current.card === card) scheduleClose();
      }
      card.addEventListener('mouseenter', onEnter);
      card.addEventListener('mouseleave', onLeave);
      // Store for disarm
      card._mfHoverHandlers = { onEnter: onEnter, onLeave: onLeave };
    }

    function disarm(card) {
      var h = card._mfHoverHandlers;
      if (!h) return;
      card.removeEventListener('mouseenter', h.onEnter);
      card.removeEventListener('mouseleave', h.onLeave);
      delete card._mfHoverHandlers;
      if (current && current.card === card) close();
    }

    return { armOn: armOn, disarm: disarm, close: close };
  }

  global.MFHoverPreview = { create: create, DELAY_MS: DELAY_MS };
})(window);
