/* Hero search bar. Airbnb-style segmented input with three fields and
 * a circular submit button.
 *
 * Usage:
 *   MFSearchBar.mount(slot, {
 *     onSubmit: function(payload) { ... }   // { q, format, when }
 *   });
 *
 * Safe DOM throughout. No frameworks.
 */
(function (global) {
  'use strict';

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function makeSeg(label, placeholder, name, flex) {
    var seg = el('div', 'mf-sb__seg');
    if (flex) seg.style.flex = String(flex);
    var lab = el('div', 'mf-sb__label');
    lab.textContent = label;
    var input = el('input', 'mf-sb__input');
    input.type = 'text';
    input.name = name;
    input.placeholder = placeholder;
    seg.appendChild(lab);
    seg.appendChild(input);
    return { wrap: seg, input: input };
  }

  function mount(slot, opts) {
    if (!slot) throw new Error('MFSearchBar.mount: slot is required');
    var onSubmit = (opts && opts.onSubmit) || function () {};

    while (slot.firstChild) slot.removeChild(slot.firstChild);

    var form = el('form', 'mf-sb');
    form.setAttribute('role', 'search');
    var q = makeSeg('Looking for', 'Keywords, filename, or natural language', 'q', 2);
    var fmt = makeSeg('Format', 'Any', 'format', 1);
    var when = makeSeg('When', 'Anytime', 'when', 1);
    form.appendChild(q.wrap);
    form.appendChild(fmt.wrap);
    form.appendChild(when.wrap);

    var btn = el('button', 'mf-sb__go');
    btn.type = 'submit';
    btn.setAttribute('aria-label', 'Submit search');
    btn.textContent = '⌕';   // ⌕ search-shape glyph
    form.appendChild(btn);

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var payload = {
        q: q.input.value.trim(),
        format: fmt.input.value.trim() || null,
        when: when.input.value.trim() || null,
      };
      try { onSubmit(payload); } catch (e) { console.error(e); }
    });

    slot.appendChild(form);

    return {
      focus: function () { q.input.focus(); },
      clear: function () { q.input.value = ''; fmt.input.value = ''; when.input.value = ''; },
    };
  }

  global.MFSearchBar = { mount: mount };
})(window);
