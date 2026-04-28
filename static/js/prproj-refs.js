/**
 * static/js/prproj-refs.js — v0.34.0
 *
 * Shared module for the Premiere-project (.prproj) cross-reference UI.
 * Used by:
 *   - static/preview.html — "Used in Premiere projects" sidebar card on
 *     video / audio / image / graphic file detail pages.
 *
 * All DOM is built via createElement + textContent (XSS-safe per the
 * project gotcha). No innerHTML.
 *
 * Public surface (attached to window.PrprojRefs):
 *   fetchProjectsReferencing(mediaPath)   -> Promise<Array>
 *   renderReferencesCard(container, refs) -> void
 *   isLikelyMediaPath(path)               -> bool   (cheap extension check)
 */
(function () {
  'use strict';

  var VIDEO_EXTS = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v',
                    '.mxf', '.wmv', '.mts', '.m2ts', '.r3d', '.braw'];
  var AUDIO_EXTS = ['.mp3', '.wav', '.flac', '.aac', '.m4a',
                    '.aif', '.aiff', '.ogg', '.wma'];
  var IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff',
                    '.webp', '.heic', '.heif', '.dpx', '.exr', '.tga'];
  var GRAPHIC_EXTS = ['.psd', '.ai', '.svg', '.eps', '.prtl'];

  var ALL_REFERENCEABLE = VIDEO_EXTS.concat(AUDIO_EXTS, IMAGE_EXTS, GRAPHIC_EXTS);

  function isLikelyMediaPath(path) {
    if (!path || typeof path !== 'string') return false;
    var lower = path.toLowerCase();
    var dotIdx = lower.lastIndexOf('.');
    if (dotIdx < 0) return false;
    var ext = lower.substring(dotIdx);
    return ALL_REFERENCEABLE.indexOf(ext) >= 0;
  }

  function fetchProjectsReferencing(mediaPath) {
    if (!mediaPath) return Promise.resolve([]);
    var url = '/api/prproj/references?path=' + encodeURIComponent(mediaPath);
    return fetch(url, { credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp.ok) {
          // 404 / 401 / 500 — silent failure, return empty list.
          // The "no references" empty state and the "fetch failed" empty
          // state are visually identical for this informational card.
          return { projects: [] };
        }
        return resp.json();
      })
      .then(function (body) {
        return (body && body.projects) ? body.projects : [];
      })
      .catch(function () { return []; });
  }

  function renderReferencesCard(container, refs) {
    // Container is `.pv-card`. Wipe + repopulate.
    while (container.firstChild) container.removeChild(container.firstChild);

    var heading = document.createElement('h3');
    heading.textContent = 'Used in Premiere projects';
    if (refs && refs.length > 0) {
      var count = document.createElement('span');
      count.className = 'pv-card-badge';
      count.textContent = ' (' + refs.length + ')';
      heading.appendChild(count);
    }
    container.appendChild(heading);

    if (!refs || refs.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'Not referenced by any indexed Premiere project.';
      container.appendChild(empty);
      return;
    }

    var list = document.createElement('ul');
    list.className = 'pv-prproj-refs-list';
    refs.forEach(function (ref) {
      var li = document.createElement('li');
      li.className = 'pv-prproj-refs-item';

      // Each entry deep-links into its own preview page.
      var link = document.createElement('a');
      var hrefBase = '/preview.html?path=';
      link.href = hrefBase + encodeURIComponent(ref.project_path || '');
      link.textContent = _basename(ref.project_path || '(unknown)');
      link.title = ref.project_path || '';
      li.appendChild(link);

      // Show the bin / clip name beneath if present and different from
      // the project filename.
      if (ref.media_name && ref.media_name !== _basename(ref.project_path)) {
        var sub = document.createElement('div');
        sub.className = 'pv-prproj-refs-sub';
        sub.textContent = 'as: ' + ref.media_name;
        li.appendChild(sub);
      }

      list.appendChild(li);
    });
    container.appendChild(list);
  }

  function _basename(path) {
    if (!path) return '';
    var n = path.lastIndexOf('/');
    var b = path.lastIndexOf('\\');
    var idx = Math.max(n, b);
    return idx >= 0 ? path.substring(idx + 1) : path;
  }

  window.PrprojRefs = {
    fetchProjectsReferencing: fetchProjectsReferencing,
    renderReferencesCard: renderReferencesCard,
    isLikelyMediaPath: isLikelyMediaPath,
  };
})();
