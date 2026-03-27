/**
 * Contextual help link component — adds "?" icons next to elements with data-help attributes.
 *
 * Usage: <h2 data-help="bulk-conversion">Bulk Conversion</h2>
 * The script appends a clickable "?" icon linking to /help#bulk-conversion.
 */
(function() {
    'use strict';

    var style = document.createElement('style');
    style.textContent =
        '.help-icon{display:inline-flex;align-items:center;justify-content:center;' +
        'width:18px;height:18px;border-radius:50%;background:var(--text-muted,#888);' +
        'color:var(--bg,#fff);font-size:11px;font-weight:700;text-decoration:none;' +
        'margin-left:0.5rem;vertical-align:middle;cursor:pointer;opacity:0.5;' +
        'transition:opacity 0.15s,background 0.15s;flex-shrink:0}' +
        '.help-icon:hover{opacity:1;background:var(--accent,#4f5bd5)}';
    document.head.appendChild(style);

    function initHelpLinks() {
        document.querySelectorAll('[data-help]').forEach(function(el) {
            if (el.querySelector('.help-icon')) return;
            var slug = el.getAttribute('data-help');
            var link = document.createElement('a');
            link.href = '/help#' + slug;
            link.className = 'help-icon';
            link.title = 'Help';
            link.setAttribute('aria-label', 'Help');
            link.textContent = '?';
            el.appendChild(link);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initHelpLinks);
    } else {
        initHelpLinks();
    }

    window.initHelpLinks = initHelpLinks;
})();
