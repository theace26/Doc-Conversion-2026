/* Topic cloud — pill cloud of topics with counts.
 * Spec §3 (Maximal mode "Browse by topic" row).
 *
 * Usage:
 *   var node = MFTopicCloud.build([
 *     { name: 'Contracts', count: 428 },
 *     ...
 *   ], onClick);   // onClick receives the full topic object { name, count }
 *
 * Returns a DOM node ready to drop into MFBrowseRow content slot.
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

  function build(topics, onClick) {
    var wrap = el('div', 'mf-topic-cloud');
    (topics || []).forEach(function (t) {
      var pill = el('a', 'mf-topic-cloud__pill');
      pill.href = '#';
      pill.setAttribute('data-topic', t.name);
      var name = el('span'); name.textContent = t.name;
      pill.appendChild(name);
      if (typeof t.count === 'number') {
        var c = el('span', 'mf-topic-cloud__count');
        c.textContent = ' ' + t.count.toLocaleString();
        pill.appendChild(c);
      }
      pill.addEventListener('click', function (ev) {
        ev.preventDefault();
        if (typeof onClick === 'function') onClick(t);
      });
      wrap.appendChild(pill);
    });
    return wrap;
  }

  global.MFTopicCloud = { build: build };
})(window);
