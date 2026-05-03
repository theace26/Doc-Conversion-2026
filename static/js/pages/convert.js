/* MarkFlow Convert page component (new UX).
 *
 * Usage:
 *   MFConvert.mount(document.getElementById('mf-convert-page'), { role: 'member' });
 *
 * Provides a drop zone + file queue with per-file progress states.
 * Calls POST /api/convert (multipart/form-data) — same endpoint as
 * the original /index.html convert flow. On success redirects to
 * /progress.html?batch_id=<id> just like the legacy page.
 *
 * States per file: pending → uploading → converting → done | failed
 *
 * TODO (follow-ups, not MVP):
 *   - Direction toggle (to_md / from_md) with target format picker
 *   - Advanced options (fidelity tier, OCR mode, brute-force password)
 *   - Output-directory override field
 *   - Unattended mode toggle
 *   - Shift+click for folder picker (webkitdirectory)
 *   - Preview endpoint (/api/convert/preview)
 *
 * Safe DOM throughout — no innerHTML with user-controlled content.
 */
(function (global) {
  'use strict';

  // Accepted file extensions — mirrors index.html's VALID_EXTENSIONS set.
  var VALID_EXT = new Set([
    '.docx','.doc','.pdf','.pptx','.ppt','.xlsx','.xls','.csv','.tsv','.rtf',
    '.odt','.ods','.odp','.md','.txt','.log','.text',
    '.html','.htm','.xml','.epub',
    '.json','.yaml','.yml','.ini','.cfg','.conf','.properties',
    '.eml','.msg',
    '.psd','.ai','.indd','.aep','.prproj','.xd',
    '.mp3','.mp4','.mov','.avi','.mkv','.wav','.flac','.ogg','.webm',
    '.m4a','.m4v','.wmv','.aac','.wma',
    '.srt','.vtt','.sbv',
  ]);

  // ── helpers ──────────────────────────────────────────────────────────────────

  function el(tag, cls) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    return n;
  }

  function extOf(name) {
    var dot = name.lastIndexOf('.');
    return dot >= 0 ? name.slice(dot).toLowerCase() : '';
  }

  function isValid(file) {
    return VALID_EXT.has(extOf(file.name));
  }

  // ── per-file row ─────────────────────────────────────────────────────────────

  // row state: { file, status: 'pending'|'uploading'|'converting'|'done'|'failed', msg }
  function makeRow(file) {
    return { file: file, status: 'pending', msg: '' };
  }

  function renderRow(state) {
    var row = el('li', 'mf-convert__queue-row');
    row.setAttribute('data-status', state.status);

    var icon = el('span', 'mf-convert__row-icon');
    var iconMap = {
      pending:    '○',
      uploading:  '↑',
      converting: '⟳',
      done:       '✓',
      failed:     '✕',
    };
    icon.textContent = iconMap[state.status] || '○';
    row.appendChild(icon);

    var name = el('span', 'mf-convert__row-name');
    name.textContent = state.file.name;
    row.appendChild(name);

    var status = el('span', 'mf-convert__row-status');
    var statusLabels = {
      pending:    'Pending',
      uploading:  'Uploading…',
      converting: 'Converting…',
      done:       'Done',
      failed:     state.msg || 'Failed',
    };
    status.textContent = statusLabels[state.status] || state.status;
    row.appendChild(status);

    return row;
  }

  // ── main mount ───────────────────────────────────────────────────────────────

  function mount(slot, opts) {
    if (!slot) return;
    var _opts = opts || {};

    // State
    var queue = [];           // array of row-state objects
    var converting = false;

    // ── DOM structure ──────────────────────────────────────────────────────────

    var body = el('div', 'mf-convert__body');

    // Headline block
    var headline = el('h1', 'mf-convert__headline');
    headline.textContent = 'Convert documents';
    body.appendChild(headline);

    var subtitle = el('p', 'mf-convert__subtitle');
    subtitle.textContent = 'Drop files here or click to browse. Markdown conversion happens automatically.';
    body.appendChild(subtitle);

    // Drop zone
    var dropZone = el('div', 'mf-convert__dropzone');
    dropZone.setAttribute('tabindex', '0');
    dropZone.setAttribute('role', 'button');
    dropZone.setAttribute('aria-label', 'Drop files here or click to browse');

    var dzIcon = el('div', 'mf-convert__dz-icon');
    dzIcon.textContent = '↑';
    dropZone.appendChild(dzIcon);

    var dzLabel = el('p', 'mf-convert__dz-label');
    dzLabel.textContent = 'Drop files here, or click to browse';
    dropZone.appendChild(dzLabel);

    var dzHint = el('p', 'mf-convert__dz-hint');
    dzHint.textContent = 'Supports DOCX, PDF, PPTX, XLSX, MP4, MP3, and dozens more formats';
    dropZone.appendChild(dzHint);

    // Hidden file input
    var fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.multiple = true;
    fileInput.style.display = 'none';
    fileInput.accept = Array.from(VALID_EXT).join(',');
    dropZone.appendChild(fileInput);

    body.appendChild(dropZone);

    // Queue section (hidden until files are added)
    var queueSection = el('div', 'mf-convert__queue-section');
    queueSection.hidden = true;

    var queueHeader = el('div', 'mf-convert__queue-header');

    var queueTitle = el('span', 'mf-convert__queue-title');
    queueTitle.textContent = 'Files';
    queueHeader.appendChild(queueTitle);

    var clearBtn = el('button', 'mf-btn mf-btn--ghost mf-btn--sm mf-convert__clear-btn');
    clearBtn.textContent = 'Clear all';
    queueHeader.appendChild(clearBtn);

    queueSection.appendChild(queueHeader);

    var queueList = el('ul', 'mf-convert__queue');
    queueSection.appendChild(queueList);

    var actionsBar = el('div', 'mf-convert__actions');

    var convertBtn = el('button', 'mf-btn mf-btn--primary mf-convert__convert-btn');
    convertBtn.textContent = 'Convert';
    actionsBar.appendChild(convertBtn);

    queueSection.appendChild(actionsBar);
    body.appendChild(queueSection);

    slot.appendChild(body);

    // ── Queue rendering ────────────────────────────────────────────────────────

    function redrawQueue() {
      while (queueList.firstChild) queueList.removeChild(queueList.firstChild);
      queue.forEach(function (state) {
        queueList.appendChild(renderRow(state));
      });
      queueSection.hidden = queue.length === 0;
      // Disable convert button while a conversion is in flight or queue empty
      convertBtn.disabled = converting || queue.length === 0;
    }

    // ── File addition ──────────────────────────────────────────────────────────

    function addFiles(files) {
      var added = 0;
      for (var i = 0; i < files.length; i++) {
        var f = files[i];
        if (!isValid(f)) continue;
        // Avoid duplicate filenames already in queue
        var already = queue.some(function (s) { return s.file.name === f.name; });
        if (already) continue;
        queue.push(makeRow(f));
        added++;
      }
      if (added > 0) redrawQueue();
    }

    // ── Drop zone events ───────────────────────────────────────────────────────

    dropZone.addEventListener('click', function () {
      if (!converting) fileInput.click();
    });

    dropZone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (!converting) fileInput.click();
      }
    });

    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropZone.classList.add('mf-convert__dropzone--over');
    });

    dropZone.addEventListener('dragleave', function () {
      dropZone.classList.remove('mf-convert__dropzone--over');
    });

    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('mf-convert__dropzone--over');
      var files = e.dataTransfer ? e.dataTransfer.files : null;
      if (files && files.length) addFiles(files);
    });

    fileInput.addEventListener('change', function () {
      if (fileInput.files && fileInput.files.length) {
        addFiles(fileInput.files);
        // Reset so same file can be re-added after clear
        fileInput.value = '';
      }
    });

    // ── Clear ──────────────────────────────────────────────────────────────────

    clearBtn.addEventListener('click', function () {
      if (converting) return;
      queue = [];
      redrawQueue();
    });

    // ── Convert ───────────────────────────────────────────────────────────────

    convertBtn.addEventListener('click', function () {
      if (converting || queue.length === 0) return;
      startConvert();
    });

    function startConvert() {
      converting = true;

      // Mark all pending files as uploading
      queue.forEach(function (s) { if (s.status === 'pending') s.status = 'uploading'; });
      redrawQueue();

      var fd = new FormData();
      queue.forEach(function (s) { fd.append('files', s.file); });
      fd.append('direction', 'to_md');
      fd.append('unattended', 'true');
      // TODO: expose output_dir, fidelity_tier, ocr_mode, password in advanced options panel

      fetch('/api/convert', {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      })
        .then(function (r) {
          if (!r.ok) {
            return r.text().then(function (t) {
              throw new Error(t || ('HTTP ' + r.status));
            });
          }
          return r.json();
        })
        .then(function (result) {
          // Mark all uploading → converting then redirect
          queue.forEach(function (s) {
            if (s.status === 'uploading') s.status = 'converting';
          });
          redrawQueue();
          // Redirect to the progress page (same as legacy convert UI)
          if (result && result.batch_id) {
            window.location.href = '/progress.html?batch_id=' + encodeURIComponent(result.batch_id);
          } else {
            // No batch_id — mark done and stay on page
            queue.forEach(function (s) {
              if (s.status === 'converting') s.status = 'done';
            });
            converting = false;
            redrawQueue();
          }
        })
        .catch(function (e) {
          queue.forEach(function (s) {
            if (s.status === 'uploading' || s.status === 'converting') {
              s.status = 'failed';
              s.msg = e.message || 'Upload failed';
            }
          });
          converting = false;
          redrawQueue();
          console.error('mf: convert upload failed', e);
        });
    }
  }

  global.MFConvert = { mount: mount };
})(window);
