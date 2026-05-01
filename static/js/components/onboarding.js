/* MFOnboarding — first-run onboarding overlay. Plan 8 Task 1.
 * Spec §8 (onboarding wizard). 3-step overlay shown on first visit to #mf-home.
 *
 * Usage:
 *   var ob = MFOnboarding.show({
 *     fetchSources: function() { return fetch('/api/sources').then(function(r){ return r.json(); }); },
 *     onComplete:   function() { ... },   // Step 3 "Finish setup" or "Skip" in Step 3
 *     onSkip:       function() { ... }    // "Skip setup" in Steps 1 or 2
 *   });
 *   ob.hide();   // programmatic dismiss
 *
 * Constraints (enforced at review time):
 *   - Zero innerHTML — all DOM via createElement / textContent / appendChild
 *   - ES5 IIFE, var only, no arrow functions, no template literals, no const/let
 *   - All colors via var(--mf-*) except: rgba(10,10,10,0.55) backdrop scrim
 *     and rgba(0,0,0,0.38) card shadow — documented overlay aesthetic exceptions
 *   - No external images, no base64 — layout previews are pure CSS
 */
(function (global) {
  'use strict';

  /* ── Layout mode definitions ── */
  var MODES = [
    {
      id:          'maximal',
      label:       'Maximal',
      desc:        'Tuesday at 10am — browse everything',
      recommended: false
    },
    {
      id:          'recent',
      label:       'Recent',
      desc:        'Friday catch-up — jump back in',
      recommended: false
    },
    {
      id:          'minimal',
      label:       'Minimal',
      desc:        'Mid-meeting lookup — just search',
      recommended: true
    }
  ];

  /* ── Tiny DOM helper (matches convention from layout-popover.js) ── */
  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  /* ── Focus trap: cycle Tab inside card ── */
  function buildFocusTrap(card) {
    var FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    function handler(ev) {
      if (ev.key !== 'Tab') return;
      var nodes = card.querySelectorAll(FOCUSABLE);
      if (!nodes.length) return;
      var first = nodes[0];
      var last  = nodes[nodes.length - 1];
      if (ev.shiftKey) {
        if (document.activeElement === first) {
          ev.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          ev.preventDefault();
          first.focus();
        }
      }
    }
    return {
      attach: function () { document.addEventListener('keydown', handler); },
      detach: function () { document.removeEventListener('keydown', handler); }
    };
  }

  /* ── Progress dots ── */
  function buildProgress(totalSteps) {
    var wrap = el('div', 'mf-ob__progress');
    var dots = [];
    for (var i = 0; i < totalSteps; i++) {
      var dot = el('span', 'mf-ob__dot');
      dots.push(dot);
      wrap.appendChild(dot);
    }
    function setActive(idx) {
      for (var j = 0; j < dots.length; j++) {
        dots[j].className = j === idx ? 'mf-ob__dot mf-ob__dot--active' : 'mf-ob__dot';
      }
    }
    return { node: wrap, setActive: setActive };
  }

  /* ── Step 1: Welcome ── */
  function buildStep1() {
    var wrap = el('div', 'mf-ob__step');

    var icon = el('div', 'mf-ob__step-icon');
    icon.textContent = '🗂️';   /* 🗂️ file cabinet */

    var headline = el('h2', 'mf-ob__headline');
    headline.textContent = 'Welcome to MarkFlow.';

    var subtitle = el('p', 'mf-ob__subtitle');
    subtitle.textContent = 'Find any document on the K Drive in seconds. Let’s get you set up.';

    wrap.appendChild(icon);
    wrap.appendChild(headline);
    wrap.appendChild(subtitle);
    return wrap;
  }

  /* ── Layout preview wireframes (pure CSS rects) ── */
  function buildPreviewMaximal() {
    var p = el('div', 'mf-ob__layout-preview');
    /* Small grid of colored blocks filling the area */
    for (var r = 0; r < 2; r++) {
      var row = el('div', 'mf-ob__prev-row');
      for (var c = 0; c < 3; c++) {
        var block = el('div', 'mf-ob__prev-block');
        row.appendChild(block);
      }
      p.appendChild(row);
    }
    return p;
  }

  function buildPreviewRecent() {
    var p = el('div', 'mf-ob__layout-preview');
    /* Search bar-like rect at top */
    var bar = el('div', 'mf-ob__prev-bar');
    p.appendChild(bar);
    /* Row of small chip rects */
    var chips = el('div', 'mf-ob__prev-chips');
    for (var i = 0; i < 3; i++) {
      chips.appendChild(el('div', 'mf-ob__prev-chip'));
    }
    p.appendChild(chips);
    /* Grid of card rects */
    var grid = el('div', 'mf-ob__prev-cards');
    for (var j = 0; j < 4; j++) {
      grid.appendChild(el('div', 'mf-ob__prev-card-sm'));
    }
    p.appendChild(grid);
    return p;
  }

  function buildPreviewMinimal() {
    var p = el('div', 'mf-ob__layout-preview');
    /* Single centered tall rect — the search bar */
    var bar = el('div', 'mf-ob__prev-bar mf-ob__prev-bar--tall');
    p.appendChild(bar);
    return p;
  }

  /* ── Step 2: Layout picker ── */
  function buildStep2(initialMode, onModeChange) {
    var wrap = el('div', 'mf-ob__step');
    var cards = el('div', 'mf-ob__layout-cards');

    var selectedMode = initialMode;

    function buildCard(mode) {
      var btn = el('button', 'mf-ob__layout-card' +
        (mode.id === selectedMode ? ' mf-ob__layout-card--selected' : '') +
        (mode.recommended ? ' mf-ob__layout-card--recommended' : ''));
      btn.setAttribute('type', 'button');
      btn.setAttribute('data-mode', mode.id);

      /* Preview wireframe */
      var preview;
      if (mode.id === 'maximal') {
        preview = buildPreviewMaximal();
      } else if (mode.id === 'recent') {
        preview = buildPreviewRecent();
      } else {
        preview = buildPreviewMinimal();
      }
      btn.appendChild(preview);

      var name = el('div', 'mf-ob__card-name');
      name.textContent = mode.label;
      btn.appendChild(name);

      var desc = el('div', 'mf-ob__card-desc');
      desc.textContent = mode.desc;
      btn.appendChild(desc);

      if (mode.recommended) {
        var badge = el('span', 'mf-ob__recommended-badge');
        badge.textContent = 'Recommended';
        btn.appendChild(badge);
      }

      return btn;
    }

    var cardEls = [];
    for (var i = 0; i < MODES.length; i++) {
      var card = buildCard(MODES[i]);
      cardEls.push(card);
      cards.appendChild(card);
    }

    /* Click selection */
    cards.addEventListener('click', function (ev) {
      var t = ev.target;
      while (t && t !== cards && !t.getAttribute('data-mode')) t = t.parentNode;
      if (!t || t === cards) return;
      var mode = t.getAttribute('data-mode');
      if (mode === selectedMode) return;
      selectedMode = mode;
      for (var j = 0; j < cardEls.length; j++) {
        var m = cardEls[j].getAttribute('data-mode');
        if (m === selectedMode) {
          cardEls[j].classList.add('mf-ob__layout-card--selected');
        } else {
          cardEls[j].classList.remove('mf-ob__layout-card--selected');
        }
      }
      onModeChange(selectedMode);
    });

    /* Keyboard: ArrowLeft / ArrowRight cycles selection */
    cards.addEventListener('keydown', function (ev) {
      if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight' && ev.key !== 'Enter') return;
      var idx = 0;
      for (var j = 0; j < MODES.length; j++) {
        if (MODES[j].id === selectedMode) { idx = j; break; }
      }
      if (ev.key === 'ArrowLeft') {
        idx = (idx - 1 + MODES.length) % MODES.length;
      } else if (ev.key === 'ArrowRight') {
        idx = (idx + 1) % MODES.length;
      }
      if (ev.key !== 'Enter') {
        ev.preventDefault();
        selectedMode = MODES[idx].id;
        for (var k = 0; k < cardEls.length; k++) {
          if (cardEls[k].getAttribute('data-mode') === selectedMode) {
            cardEls[k].classList.add('mf-ob__layout-card--selected');
            cardEls[k].focus();
          } else {
            cardEls[k].classList.remove('mf-ob__layout-card--selected');
          }
        }
        onModeChange(selectedMode);
      } else {
        /* Enter on a layout card: advance to Step 3 */
        var ob = cards.closest ? cards.closest('.mf-ob__card') : null;
        if (!ob) {
          /* Fallback for IE: walk up manually */
          ob = cards.parentNode;
          while (ob && !ob.classList.contains('mf-ob__card')) {
            ob = ob.parentNode;
          }
        }
        if (ob) {
          var nextBtn = ob.querySelector('.mf-btn--primary');
          if (nextBtn) nextBtn.click();
        }
      }
    });

    wrap.appendChild(cards);
    return wrap;
  }

  /* ── Step 3: Pin folders ── */

  /* Build the folder list (or empty state) from resolved sources. */
  function _renderPinFolders(sources) {
    var frag = document.createDocumentFragment();
    var MAX_VISIBLE = 8;
    var MAX_PINS    = 6;

    /* Header */
    var icon = el('div', 'mf-ob__step-icon');
    icon.textContent = '📌';   /* 📌 */

    var headline = el('h2', 'mf-ob__headline');
    headline.textContent = 'Pin your first folders.';

    var subtitle = el('p', 'mf-ob__subtitle');
    subtitle.textContent = 'These appear as quick-access cards on your home page.';

    frag.appendChild(icon);
    frag.appendChild(headline);
    frag.appendChild(subtitle);

    if (!sources || sources.length === 0) {
      /* Empty state */
      var empty = el('div', 'mf-ob__folder-empty');

      var emptyIcon = el('span', 'mf-ob__step-icon');
      emptyIcon.textContent = '🗂️';   /* 🗂️ */

      var emptyLine1 = el('p');
      emptyLine1.textContent = 'No indexed folders yet.';

      var emptyLine2 = el('p');
      emptyLine2.textContent = 'Folders appear here once the pipeline scans your K Drive.';

      empty.appendChild(emptyIcon);
      empty.appendChild(emptyLine1);
      empty.appendChild(emptyLine2);
      frag.appendChild(empty);
      return frag;
    }

    /* Pin limit warning node (hidden until needed) */
    var limitNote = el('div', 'mf-ob__pin-limit-note');
    limitNote.textContent = 'Unpin a folder to add another.';
    limitNote.style.display = 'none';

    /* Folder list */
    var ul = el('ul', 'mf-ob__folder-list');
    ul.style.listStyle = 'none';

    var pinnedCount = 0;
    var liEls = [];   /* all li elements in order */

    function setPinned(liEl, cb, pinned) {
      if (pinned) {
        liEl.classList.add('mf-ob__folder-item--pinned');
        cb.checked = true;
      } else {
        liEl.classList.remove('mf-ob__folder-item--pinned');
        cb.checked = false;
      }
    }

    function toggleItem(liEl, cb) {
      var wasPinned = liEl.classList.contains('mf-ob__folder-item--pinned');
      if (!wasPinned) {
        /* Trying to pin */
        if (pinnedCount >= MAX_PINS) {
          /* Enforce max — show warning, don't change state */
          limitNote.style.display = '';
          cb.checked = false;
          return;
        }
        pinnedCount += 1;
        setPinned(liEl, cb, true);
      } else {
        /* Unpinning */
        pinnedCount -= 1;
        setPinned(liEl, cb, false);
        /* Hide warning if under the limit again */
        if (pinnedCount < MAX_PINS) {
          limitNote.style.display = 'none';
        }
      }
    }

    var hidden = [];   /* li elements beyond MAX_VISIBLE */

    for (var i = 0; i < sources.length; i++) {
      var src = sources[i];
      var displayText = (src.label && src.label !== src.path) ? src.label : src.path;

      var li = el('li', 'mf-ob__folder-item');
      li.setAttribute('data-path', src.path);

      var cb = el('input');
      cb.setAttribute('type', 'checkbox');
      cb.className = 'mf-ob__folder-cb';
      cb.style.width  = '18px';
      cb.style.height = '18px';

      var folderIcon = el('span');
      folderIcon.textContent = '📁';   /* 📁 */

      var labelSpan = el('span');
      labelSpan.textContent = displayText;

      li.appendChild(cb);
      li.appendChild(folderIcon);
      li.appendChild(labelSpan);

      /* Capture loop vars */
      (function (liRef, cbRef) {
        li.addEventListener('click', function (ev) {
          /* If the checkbox itself was clicked, the browser toggles it before
           * the click fires on li — we need to read the NEW checked state.
           * For any other part of the row, we manually flip. */
          if (ev.target === cbRef) {
            /* checkbox toggled natively; sync state */
            var willBePinned = cbRef.checked;
            if (willBePinned && pinnedCount >= MAX_PINS) {
              /* Undo native toggle */
              cbRef.checked = false;
              limitNote.style.display = '';
              return;
            }
            if (willBePinned) {
              pinnedCount += 1;
              liRef.classList.add('mf-ob__folder-item--pinned');
            } else {
              pinnedCount -= 1;
              liRef.classList.remove('mf-ob__folder-item--pinned');
              if (pinnedCount < MAX_PINS) limitNote.style.display = 'none';
            }
          } else {
            toggleItem(liRef, cbRef);
          }
        });
      })(li, cb);

      ul.appendChild(li);
      liEls.push(li);

      if (i >= MAX_VISIBLE) {
        li.style.display = 'none';
        hidden.push(li);
      }
    }

    frag.appendChild(ul);

    /* "Show N more" link */
    if (hidden.length > 0) {
      var showMore = el('a', 'mf-ob__show-more');
      showMore.setAttribute('href', '#');
      showMore.textContent = 'Show ' + hidden.length + ' more';
      showMore.addEventListener('click', function (ev) {
        ev.preventDefault();
        for (var j = 0; j < hidden.length; j++) {
          hidden[j].style.display = '';
        }
        if (showMore.parentNode) showMore.parentNode.removeChild(showMore);
      });
      frag.appendChild(showMore);
    }

    frag.appendChild(limitNote);

    return frag;
  }

  function buildStep3(sourcesPromise, fetchSources) {
    var s3 = el('div', 'mf-ob__step');
    var alive = true;

    /* Loading placeholder */
    var loading = el('p', 'mf-ob__loading');
    loading.textContent = 'Loading folders…';
    s3.appendChild(loading);

    /* Determine the promise to use */
    var promise = sourcesPromise;
    if (!promise) {
      promise = fetchSources();
    }

    promise.then(function (data) {
      if (!alive) { return; }
      /* API returns { sources: [...] } or a bare array */
      var list = Array.isArray(data) ? data : (data && data.sources ? data.sources : []);
      if (!Array.isArray(list)) { list = []; }
      /* Remove loading text */
      if (loading.parentNode) loading.parentNode.removeChild(loading);
      var frag = _renderPinFolders(list);
      s3.appendChild(frag);
    }).catch(function () {
      if (!alive) { return; }
      if (loading.parentNode) loading.parentNode.removeChild(loading);
      var frag = _renderPinFolders([]);
      s3.appendChild(frag);
    });

    s3._teardown = function () { alive = false; };
    return s3;
  }

  /* Collect pinned paths from step-3 node */
  function _getPinnedPaths(stepNode) {
    var pins = stepNode.querySelectorAll('.mf-ob__folder-item--pinned');
    var paths = [];
    for (var i = 0; i < pins.length; i++) {
      /* Third child is the label span; its text matches displayText (label or path).
       * We need the actual path — store it on the li as a data attribute. */
      var pathAttr = pins[i].getAttribute('data-path');
      if (pathAttr) paths.push(pathAttr);
    }
    return paths;
  }

  /* ── Footer buttons ── */
  function buildFooter(stepIdx, handlers) {
    var footer = el('div', 'mf-ob__footer');

    if (stepIdx === 0) {
      /* Step 1: [Skip setup] on right, [Next →] primary */
      var skipBtn = el('button', 'mf-btn mf-btn--ghost');
      skipBtn.setAttribute('type', 'button');
      skipBtn.textContent = 'Skip setup';
      skipBtn.addEventListener('click', handlers.onSkip);

      var nextBtn = el('button', 'mf-btn mf-btn--primary');
      nextBtn.setAttribute('type', 'button');
      nextBtn.textContent = 'Next →';
      nextBtn.addEventListener('click', handlers.onNext);

      footer.appendChild(skipBtn);
      footer.appendChild(nextBtn);

    } else if (stepIdx === 1) {
      /* Step 2: [← Back] left, [Skip setup] ghost smaller, [Next →] primary */
      var backBtn2 = el('button', 'mf-btn mf-btn--ghost');
      backBtn2.setAttribute('type', 'button');
      backBtn2.textContent = '← Back';
      backBtn2.addEventListener('click', handlers.onBack);

      var skipBtn2 = el('button', 'mf-btn mf-btn--ghost mf-btn--sm');
      skipBtn2.setAttribute('type', 'button');
      skipBtn2.textContent = 'Skip setup';
      skipBtn2.addEventListener('click', handlers.onSkip);

      var nextBtn2 = el('button', 'mf-btn mf-btn--primary');
      nextBtn2.setAttribute('type', 'button');
      nextBtn2.textContent = 'Next →';
      nextBtn2.addEventListener('click', handlers.onNext);

      footer.appendChild(backBtn2);
      footer.appendChild(skipBtn2);
      footer.appendChild(nextBtn2);

    } else {
      /* Step 3: [← Back] left, [Skip] ghost, [Finish setup →] primary */
      var backBtn3 = el('button', 'mf-btn mf-btn--ghost');
      backBtn3.setAttribute('type', 'button');
      backBtn3.textContent = '← Back';
      backBtn3.addEventListener('click', handlers.onBack);

      var skipBtn3 = el('button', 'mf-btn mf-btn--ghost');
      skipBtn3.setAttribute('type', 'button');
      skipBtn3.textContent = 'Skip';
      skipBtn3.addEventListener('click', handlers.onSkip3);

      var finishBtn = el('button', 'mf-btn mf-btn--primary');
      finishBtn.setAttribute('type', 'button');
      finishBtn.textContent = 'Finish setup →';
      finishBtn.addEventListener('click', handlers.onFinish);

      footer.appendChild(backBtn3);
      footer.appendChild(skipBtn3);
      footer.appendChild(finishBtn);
    }

    return footer;
  }

  /* ── Main show() ── */
  function show(opts) {
    var fetchSources = (opts && opts.fetchSources) || function () { return Promise.resolve([]); };
    var onComplete   = (opts && opts.onComplete)   || function () {};
    var onSkip       = (opts && opts.onSkip)       || function () {};

    var currentStep  = 0;
    var selectedMode = 'minimal';
    var sourcesPromise = null;

    /* Backdrop */
    var backdrop = el('div', 'mf-ob__backdrop');

    /* Card */
    var card = el('div', 'mf-ob__card');
    backdrop.appendChild(card);

    /* Progress */
    var progress = buildProgress(3);
    card.appendChild(progress.node);

    /* Step content slot */
    var stepSlot = el('div', 'mf-ob__step-slot');
    card.appendChild(stepSlot);

    /* Footer slot */
    var footerSlot = el('div', 'mf-ob__footer-slot');
    card.appendChild(footerSlot);

    /* Focus trap */
    var trap = buildFocusTrap(card);

    function clearSlot(slot) {
      while (slot.firstChild) slot.removeChild(slot.firstChild);
    }

    function render() {
      progress.setActive(currentStep);
      var oldStep = stepSlot.firstChild;
      if (oldStep && typeof oldStep._teardown === 'function') {
        oldStep._teardown();
      }
      clearSlot(stepSlot);
      clearSlot(footerSlot);

      var stepNode;
      if (currentStep === 0) {
        stepNode = buildStep1();
      } else if (currentStep === 1) {
        stepNode = buildStep2(selectedMode, function (mode) {
          selectedMode = mode;
        });
      } else {
        stepNode = buildStep3(sourcesPromise, fetchSources);
      }
      stepSlot.appendChild(stepNode);

      var footerNode = buildFooter(currentStep, {
        onNext: function () {
          if (currentStep === 1) {
            /* Persist layout choice and kick off background source fetch */
            if (global.MFPrefs && global.MFPrefs.set) {
              global.MFPrefs.set('layout', selectedMode);
            }
            if (!sourcesPromise) {
              sourcesPromise = fetchSources();
            }
          }
          currentStep += 1;
          render();
        },
        onBack: function () {
          currentStep -= 1;
          render();
        },
        onSkip: function () {
          onSkip();
          hide();
        },
        onSkip3: function () {
          /* Step 3 "Skip" — complete without saving pinned folders */
          onComplete();
          hide();
        },
        onFinish: function () {
          /* Step 3 "Finish setup" — save pinned folders then complete */
          var pinnedPaths = _getPinnedPaths(stepSlot);
          if (global.MFPrefs && global.MFPrefs.set) {
            global.MFPrefs.set('pinned_folders', JSON.stringify(pinnedPaths));
          }
          onComplete();
          hide();
        }
      });
      footerSlot.appendChild(footerNode);

      /* Move focus to first focusable element in card */
      var firstFocusable = card.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (firstFocusable) firstFocusable.focus();
    }

    function hide() {
      trap.detach();
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
    }

    document.body.appendChild(backdrop);
    trap.attach();
    render();

    return { hide: hide };
  }

  global.MFOnboarding = { show: show };
})(window);
