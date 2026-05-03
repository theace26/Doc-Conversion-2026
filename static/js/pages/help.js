/* Help wiki page logic.
 * Loaded by help-new.html. Uses /api/help/* endpoints.
 * All article HTML is server-rendered markdown (trusted source).
 * Safe DOM for chrome; server markdown injected via innerHTML (same as
 * original help.html - content originates from /docs/help/*.md, not user input).
 */
(function () {
  'use strict';

  var helpIndex = null;
  var currentSlug = '';

  // ── Load index and render sidebar ───────────────────────────────
  function init() {
    fetch('/api/help/index', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        helpIndex = data;
        renderTOC(data);
      })
      .catch(function () {
        var toc = document.getElementById('help-toc');
        if (toc) toc.textContent = 'Failed to load help index.';
      })
      .then(function () {
        var slug = window.location.hash ? window.location.hash.slice(1) : 'getting-started';
        return loadArticle(slug);
      });

    var searchEl = document.getElementById('help-search');
    if (searchEl) searchEl.addEventListener('input', debounce(handleSearch, 300));

    window.addEventListener('hashchange', function () {
      var s = window.location.hash ? window.location.hash.slice(1) : '';
      if (!s || s === currentSlug) return;
      if (isArticleSlug(s)) {
        loadArticle(s);
      } else {
        var target = document.getElementById(s);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }

  function renderTOC(index) {
    var toc = document.getElementById('help-toc');
    if (!toc) return;
    while (toc.firstChild) toc.removeChild(toc.firstChild);
    (index.categories || []).forEach(function (cat) {
      var heading = document.createElement('div');
      heading.className = 'category-heading';
      heading.textContent = cat.name;
      heading.addEventListener('click', function () {
        this.classList.toggle('open');
        var next = this.nextElementSibling;
        if (next) next.hidden = !this.classList.contains('open');
      });
      toc.appendChild(heading);

      var list = document.createElement('div');
      list.className = 'category-articles';
      list.hidden = true;
      (cat.articles || []).forEach(function (art) {
        var a = document.createElement('a');
        a.className = 'article-link';
        a.href = '#' + art.slug;
        a.dataset.slug = art.slug;
        a.textContent = art.title;
        a.addEventListener('click', function (e) {
          e.preventDefault();
          loadArticle(art.slug);
        });
        list.appendChild(a);
      });
      toc.appendChild(list);
    });
  }

  function openCategoryFor(slug) {
    document.querySelectorAll('.category-heading').forEach(function (h) {
      var list = h.nextElementSibling;
      if (!list || !list.classList.contains('category-articles')) return;
      if (list.querySelector('.article-link[data-slug="' + slug + '"]')) {
        h.classList.add('open');
        list.hidden = false;
      }
    });
  }

  function isArticleSlug(slug) {
    if (!helpIndex) return false;
    return (helpIndex.categories || []).some(function (cat) {
      return (cat.articles || []).some(function (a) { return a.slug === slug; });
    });
  }

  function renderInPageTOC(slug) {
    document.querySelectorAll('.article-subtoc').forEach(function (el) { el.remove(); });
    var activeLink = document.querySelector('.article-link[data-slug="' + slug + '"]');
    if (!activeLink) return;
    var content = document.getElementById('help-content');
    if (!content) return;
    var headings = content.querySelectorAll('h2[id], h3[id]');
    if (headings.length < 2) return;
    var activeHash = window.location.hash ? window.location.hash.slice(1) : null;
    var subToc = document.createElement('div');
    subToc.className = 'article-subtoc';
    var currentH2Wrap = null;
    var currentHasChildren = false;
    var pendingH3s = [];

    function flushH2(h2Wrap, hasChildren, h3Nodes) {
      if (!h2Wrap) return;
      if (hasChildren && h3Nodes.length > 0) {
        var toggleBtn = document.createElement('button');
        toggleBtn.className = 'article-subtoc-toggle';
        toggleBtn.setAttribute('type', 'button');
        toggleBtn.setAttribute('aria-label', 'Toggle sub-sections');
        toggleBtn.textContent = '▸';
        h2Wrap.appendChild(toggleBtn);
        subToc.appendChild(h2Wrap);
        var childDiv = document.createElement('div');
        childDiv.className = 'article-subtoc-children';
        childDiv.hidden = true;
        h3Nodes.forEach(function (node) { childDiv.appendChild(node); });
        subToc.appendChild(childDiv);
        var shouldOpen = h3Nodes.some(function (node) {
          return activeHash && node.getAttribute('href') === '#' + activeHash;
        });
        if (shouldOpen) {
          childDiv.hidden = false;
          toggleBtn.className = 'article-subtoc-toggle open';
        }
        toggleBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          var isOpen = !childDiv.hidden;
          childDiv.hidden = isOpen;
          toggleBtn.className = 'article-subtoc-toggle' + (isOpen ? '' : ' open');
        });
      } else {
        subToc.appendChild(h2Wrap);
      }
    }

    headings.forEach(function (h) {
      if (h.tagName.toLowerCase() === 'h2') {
        flushH2(currentH2Wrap, currentHasChildren, pendingH3s);
        var wrap = document.createElement('div');
        wrap.className = 'article-subtoc-h2-wrap';
        var link = document.createElement('a');
        link.className = 'article-subtoc-item article-subtoc-h2';
        link.href = '#' + h.id;
        link.textContent = h.textContent;
        (function (heading) {
          link.addEventListener('click', function (e) {
            e.preventDefault();
            heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
            history.replaceState(null, '', '#' + heading.id);
          });
        }(h));
        wrap.appendChild(link);
        currentH2Wrap = wrap;
        currentHasChildren = false;
        pendingH3s = [];
      } else {
        var item = document.createElement('a');
        item.className = 'article-subtoc-item article-subtoc-h3';
        item.href = '#' + h.id;
        item.textContent = h.textContent;
        (function (heading) {
          item.addEventListener('click', function (e) {
            e.preventDefault();
            heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
            history.replaceState(null, '', '#' + heading.id);
          });
        }(h));
        pendingH3s.push(item);
        currentHasChildren = true;
      }
    });
    flushH2(currentH2Wrap, currentHasChildren, pendingH3s);
    activeLink.parentNode.insertBefore(subToc, activeLink.nextSibling);
  }

  function renderRelatedTopics(slug) {
    if (!helpIndex) return;
    var content = document.getElementById('help-content');
    if (!content) return;
    var existing = Array.prototype.find
      ? Array.prototype.find.call(content.querySelectorAll('h2, h3'), function (h) {
          var t = (h.textContent || '').trim().toLowerCase();
          return t === 'related' || t === 'related articles' || t === 'related topics' || t === 'see also';
        })
      : null;
    if (existing) return;
    var siblings = null;
    (helpIndex.categories || []).some(function (cat) {
      if ((cat.articles || []).some(function (a) { return a.slug === slug; })) {
        siblings = (cat.articles || []).filter(function (a) { return a.slug !== slug; });
        return true;
      }
      return false;
    });
    if (!siblings || siblings.length === 0) return;
    var section = document.createElement('section');
    section.className = 'related-topics';
    var heading = document.createElement('h2');
    heading.id = 'related-topics';
    heading.textContent = 'Related topics';
    section.appendChild(heading);
    var list = document.createElement('ul');
    list.className = 'related-topics-list';
    siblings.forEach(function (a) {
      var li = document.createElement('li');
      var link = document.createElement('a');
      link.href = '#' + a.slug;
      link.textContent = a.title;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        loadArticle(a.slug);
      });
      li.appendChild(link);
      if (a.description) {
        var desc = document.createElement('span');
        desc.className = 'related-topics-desc';
        desc.textContent = ' — ' + a.description;
        li.appendChild(desc);
      }
      list.appendChild(li);
    });
    section.appendChild(list);
    content.appendChild(section);
  }

  function addBackToTopLinks() {
    var content = document.getElementById('help-content');
    if (!content) return;
    content.querySelectorAll('h2[id]').forEach(function (h2) {
      if (h2.querySelector('.back-to-top')) return;
      var hid = h2.getAttribute('id');
      if (hid === 'related-topics' || hid === 'contents') return;
      var link = document.createElement('a');
      link.className = 'back-to-top';
      link.href = '#';
      link.title = 'Back to top';
      link.textContent = '↑ top';
      link.addEventListener('click', function (e) {
        e.preventDefault();
        content.scrollTo({ top: 0, behavior: 'smooth' });
        history.replaceState(null, '', '#' + currentSlug);
      });
      h2.appendChild(link);
    });
  }

  function addCopyButtons() {
    var content = document.getElementById('help-content');
    if (!content) return;
    content.querySelectorAll('pre').forEach(function (pre) {
      if (pre.parentNode.classList && pre.parentNode.classList.contains('code-block-wrap')) return;
      var wrap = document.createElement('div');
      wrap.className = 'code-block-wrap';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      var btn = document.createElement('button');
      btn.className = 'code-copy-btn';
      btn.type = 'button';
      btn.textContent = 'Copy';
      btn.setAttribute('aria-label', 'Copy code to clipboard');
      btn.addEventListener('click', function () {
        var code = pre.textContent;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(function () {
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
          }).catch(function () {
            btn.textContent = 'Failed';
            setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
          });
        } else {
          var ta = document.createElement('textarea');
          ta.value = code;
          ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
          document.body.appendChild(ta);
          ta.select();
          try {
            document.execCommand('copy');
            btn.textContent = 'Copied!';
            btn.classList.add('copied');
            setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 1500);
          } catch (err) {
            btn.textContent = 'Failed';
          }
          document.body.removeChild(ta);
        }
      });
      wrap.appendChild(btn);
    });
  }

  function loadArticle(slug) {
    var content = document.getElementById('help-content');
    if (!content) return Promise.resolve();
    var loading = document.createElement('p');
    loading.className = 'text-muted';
    loading.style.cssText = 'padding:3rem 0;text-align:center';
    loading.textContent = 'Loading…';
    while (content.firstChild) content.removeChild(content.firstChild);
    content.appendChild(loading);
    currentSlug = slug;

    return fetch('/api/help/article/' + slug, { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (article) {
        // Inject server-rendered markdown HTML (trusted source: /docs/help/*.md)
        content.innerHTML = article.html; // eslint-disable-line no-unsanitized/property

        content.querySelectorAll('blockquote').forEach(function (bq) {
          var text = bq.textContent.trim();
          if (text.startsWith('Tip:')) bq.classList.add('tip');
          else if (text.startsWith('Warning:')) bq.classList.add('warning');
          else if (text.startsWith('Note:')) bq.classList.add('note');
        });

        document.querySelectorAll('.article-link').forEach(function (a) {
          a.classList.toggle('active', a.dataset.slug === slug);
        });
        openCategoryFor(slug);
        window.location.hash = slug;
        content.scrollTop = 0;
        renderInPageTOC(slug);
        renderRelatedTopics(slug);
        addCopyButtons();
        addBackToTopLinks();
      })
      .catch(function () {
        while (content.firstChild) content.removeChild(content.firstChild);
        var h1 = document.createElement('h1');
        h1.textContent = 'Article Not Found';
        var p = document.createElement('p');
        p.textContent = 'The help article "' + slug + '" doesn\'t exist yet.';
        var back = document.createElement('p');
        var a = document.createElement('a');
        a.href = '#getting-started';
        a.textContent = 'Go to Getting Started';
        back.appendChild(a);
        content.appendChild(h1);
        content.appendChild(p);
        content.appendChild(back);
      });
  }

  function handleSearch(e) {
    var q = e.target.value.trim();
    var resultsEl = document.getElementById('search-results');
    var tocEl = document.getElementById('help-toc');
    if (!resultsEl || !tocEl) return;

    if (q.length < 2) {
      resultsEl.hidden = true;
      tocEl.hidden = false;
      return;
    }

    fetch('/api/help/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        while (resultsEl.firstChild) resultsEl.removeChild(resultsEl.firstChild);
        if (!data.results || data.results.length === 0) {
          var empty = document.createElement('p');
          empty.className = 'text-muted';
          empty.style.padding = '0.5rem';
          empty.textContent = 'No results found.';
          resultsEl.appendChild(empty);
        } else {
          var ul = document.createElement('ul');
          ul.className = 'help-search-results';
          data.results.forEach(function (r) {
            var li = document.createElement('li');
            li.addEventListener('click', function () {
              loadArticle(r.slug);
              var searchInp = document.getElementById('help-search');
              if (searchInp) searchInp.value = '';
              resultsEl.hidden = true;
              tocEl.hidden = false;
            });
            var strong = document.createElement('strong');
            strong.textContent = r.title;
            li.appendChild(strong);
            var cat = document.createElement('span');
            cat.className = 'text-muted text-sm';
            cat.textContent = ' — ' + r.category;
            li.appendChild(cat);
            if (r.snippet) {
              var snip = document.createElement('div');
              snip.className = 'snippet';
              snip.textContent = r.snippet;
              li.appendChild(snip);
            }
            ul.appendChild(li);
          });
          resultsEl.appendChild(ul);
        }
        resultsEl.hidden = false;
        tocEl.hidden = true;
      })
      .catch(function () {
        while (resultsEl.firstChild) resultsEl.removeChild(resultsEl.firstChild);
        var err = document.createElement('p');
        err.className = 'text-muted';
        err.textContent = 'Search failed.';
        resultsEl.appendChild(err);
        resultsEl.hidden = false;
      });
  }

  function debounce(fn, ms) {
    var timer;
    return function (e) {
      clearTimeout(timer);
      var evt = e;
      timer = setTimeout(function () { fn(evt); }, ms);
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
