/* Document card. Gradient top-band + paper snippet body.
 * Used in Cards (6/row) and Compact (8/row) densities.
 * Spec §4.
 *
 * Usage:
 *   var cardEl = MFDocCard.create(doc);
 *   gridEl.appendChild(cardEl);
 *
 * For List density, use MFDocCard.createListRow(doc) which returns a
 * linear row element with a tiny format icon instead of a gradient band.
 *
 * Safe DOM throughout — no innerHTML.
 */
(function (global) {
  'use strict';

  var SUPPORTED_FORMATS = ['pdf', 'docx', 'pptx', 'xlsx', 'eml', 'psd', 'mp4', 'md'];

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function safeFormat(fmt) {
    if (typeof fmt !== 'string') return 'md';
    var f = fmt.toLowerCase();
    return SUPPORTED_FORMATS.indexOf(f) >= 0 ? f : 'md';
  }

  // Build the card DOM (cards / compact density).
  function create(doc) {
    if (!doc) throw new Error('MFDocCard.create: doc record required');
    var fmt = safeFormat(doc.format);

    var card = el('div', 'mf-doc-card');
    card.setAttribute('data-doc-id', doc.id || '');
    card.setAttribute('data-doc-format', fmt);

    var thumb = el('div', 'mf-doc-card__thumb');

    // Gradient band with format label.
    var band = el('div', 'mf-doc-card__band mf-doc-card__band--' + fmt);
    band.style.background = 'var(--mf-fmt-' + fmt + ')';
    var label = el('span', 'mf-doc-card__band-label');
    label.textContent = fmt.toUpperCase();
    band.appendChild(label);
    thumb.appendChild(band);

    // Heart icon (favorite indicator).
    var fav = el('span', 'mf-doc-card__fav');
    fav.setAttribute('aria-hidden', 'true');
    fav.textContent = doc.favorite ? '♥' : '♡';
    thumb.appendChild(fav);

    // Multi-select checkbox slot (visible on hover or when selected).
    var cb = el('span', 'mf-doc-card__checkbox');
    cb.setAttribute('aria-hidden', 'true');
    cb.setAttribute('data-mf-checkbox', '1');
    thumb.appendChild(cb);

    // Snippet body — serif text. Title shown as bold first line.
    var snippet = el('div', 'mf-doc-card__snippet');
    var h = el('div', 'mf-doc-card__snippet-h');
    h.textContent = doc.title || '(untitled)';
    snippet.appendChild(h);
    if (doc.snippet) {
      snippet.appendChild(document.createTextNode(doc.snippet));
    }
    thumb.appendChild(snippet);

    var meta = el('div', 'mf-doc-card__meta');
    var sizeSpan = el('span', 'mf-doc-card__meta-size');
    sizeSpan.textContent = formatSize(doc.size);
    var stampSpan = el('span', 'mf-doc-card__meta-stamp');
    stampSpan.textContent = formatStamp(doc.modified);
    meta.appendChild(sizeSpan);
    meta.appendChild(stampSpan);
    thumb.appendChild(meta);

    card.appendChild(thumb);

    card.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      var detail = { doc: doc, x: ev.clientX, y: ev.clientY };
      card.dispatchEvent(new CustomEvent('mf:doc-contextmenu', { detail: detail, bubbles: true }));
    });

    // Click-on-checkbox toggles selection (clicking elsewhere on the card
    // is reserved for "open" — left-click default).
    card.addEventListener('click', function (ev) {
      var t = ev.target;
      if (t && t.getAttribute && t.getAttribute('data-mf-checkbox') === '1') {
        ev.stopPropagation();
        if (typeof MFCardSelection !== 'undefined') MFCardSelection.toggle(doc.id);
      }
    });

    return card;
  }

  // Build a linear row DOM (list density).
  function createListRow(doc) {
    if (!doc) throw new Error('MFDocCard.createListRow: doc record required');
    var fmt = safeFormat(doc.format);

    var row = el('div', 'mf-doc-list-row');
    row.setAttribute('data-doc-id', doc.id || '');
    row.setAttribute('data-doc-format', fmt);

    var icon = el('span', 'mf-doc-list-row__fmt mf-doc-list-row__fmt--' + fmt);
    icon.textContent = fmt.toUpperCase().slice(0, 3);
    row.appendChild(icon);

    var title = el('span', 'mf-doc-list-row__title');
    title.textContent = doc.title || '(untitled)';
    row.appendChild(title);

    var path = el('span', 'mf-doc-list-row__path');
    path.textContent = doc.path || '';
    row.appendChild(path);

    var size = el('span', 'mf-doc-list-row__size');
    size.textContent = formatSize(doc.size);
    row.appendChild(size);

    var stamp = el('span', 'mf-doc-list-row__stamp');
    stamp.textContent = formatStamp(doc.modified);
    row.appendChild(stamp);

    var fav = el('span', 'mf-doc-list-row__fav');
    fav.setAttribute('aria-hidden', 'true');
    fav.textContent = doc.favorite ? '♥' : '♡';
    row.appendChild(fav);

    return row;
  }

  function formatSize(bytes) {
    if (typeof bytes !== 'number' || bytes < 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function formatStamp(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      var now = new Date();
      var diff = (now - d) / 1000;
      if (diff < 60) return Math.floor(diff) + ' sec ago';
      if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
      if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
      if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' d ago';
      return d.toISOString().slice(0, 10);
    } catch (e) { return ''; }
  }

  global.MFDocCard = {
    create: create,
    createListRow: createListRow,
    formatSize: formatSize,
    formatStamp: formatStamp,
    safeFormat: safeFormat
  };
})(window);
