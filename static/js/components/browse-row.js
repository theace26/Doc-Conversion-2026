/* Generic browse-row. Title + count + L/R arrows + content slot.
 * Spec §3 (Maximal mode rows).
 *
 * Usage:
 *   MFBrowseRow.mount(slot, {
 *     title: 'Pinned folders',
 *     count: 14,
 *     countSuffix: 'pinned',
 *     onSeeAll: function() { ... },   // fires on title click + arrow icon
 *     content: domNode,               // pre-built children (any layout)
 *   });
 *
 * Safe DOM throughout.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFBrowseRow.mount: slot is required');
    var title = (opts && opts.title) || '';
    var count = (opts && typeof opts.count === 'number') ? opts.count : null;
    var countSuffix = (opts && opts.countSuffix) || '';
    var content = (opts && opts.content) || null;
    var onSeeAll = (opts && opts.onSeeAll) || null;

    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var row = el('div', 'mf-row');
    var head = el('div', 'mf-row__head');

    var titleLink = el('a', 'mf-row__title-link');
    titleLink.href = '#';
    if (onSeeAll) {
      titleLink.addEventListener('click', function (ev) {
        ev.preventDefault();
        onSeeAll();
      });
    }
    var h3 = el('h3', 'mf-row__title');
    h3.textContent = title;
    titleLink.appendChild(h3);
    var arrow = el('span', 'mf-row__arrow');
    arrow.textContent = '→';   // →
    titleLink.appendChild(arrow);
    head.appendChild(titleLink);

    var controls = el('div', 'mf-row__controls');
    if (count !== null) {
      var c = el('span', 'mf-row__count');
      c.textContent = count.toLocaleString() + (countSuffix ? ' ' + countSuffix : '');
      controls.appendChild(c);
    }
    var leftBtn = el('button', 'mf-row__nav-btn');
    leftBtn.type = 'button'; leftBtn.setAttribute('aria-label', 'Scroll left');
    leftBtn.textContent = '←'; // ←
    var rightBtn = el('button', 'mf-row__nav-btn');
    rightBtn.type = 'button'; rightBtn.setAttribute('aria-label', 'Scroll right');
    rightBtn.textContent = '→'; // →
    controls.appendChild(leftBtn);
    controls.appendChild(rightBtn);
    head.appendChild(controls);

    row.appendChild(head);

    var body = el('div', 'mf-row__body');
    if (content) body.appendChild(content);
    row.appendChild(body);

    leftBtn.addEventListener('click', function () { body.scrollBy({ left: -400, behavior: 'smooth' }); });
    rightBtn.addEventListener('click', function () { body.scrollBy({ left: 400, behavior: 'smooth' }); });

    slot.appendChild(row);
  }

  global.MFBrowseRow = { mount: mount };
})(window);
