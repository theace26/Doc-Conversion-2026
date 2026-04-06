/**
 * Version history timeline panel — renders version history for a file.
 */
async function renderVersionPanel(containerId, bulkFileId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '<div class="text-sm text-muted">Loading version history...</div>';

  try {
    const data = await API.get(`/api/lifecycle/files/${bulkFileId}/versions`);
    if (!data.versions || data.versions.length === 0) {
      container.innerHTML = '<div class="text-sm text-muted">No version history available.</div>';
      return;
    }

    let html = '<div class="version-timeline">';
    for (const v of data.versions) {
      const date = v.recorded_at ? (parseUTC(v.recorded_at) || new Date(v.recorded_at)).toLocaleString() : '';
      const typeLabel = _changeTypeLabel(v.change_type);
      const icon = _changeTypeIcon(v.change_type);

      html += `<div class="version-entry">`;
      html += `<div class="version-header">`;
      html += `<span class="version-num">v${v.version_number}</span>`;
      html += `<span class="version-type">${icon} ${typeLabel}</span>`;
      html += `<span class="version-date text-muted text-sm">${date}</span>`;
      html += `</div>`;

      // Summary bullets
      if (v.diff_summary && v.diff_summary.length > 0) {
        html += '<ul class="version-bullets">';
        for (const bullet of v.diff_summary) {
          html += `<li>${_escapeHtml(bullet)}</li>`;
        }
        html += '</ul>';
      } else if (v.notes) {
        html += `<ul class="version-bullets"><li>${_escapeHtml(v.notes)}</li></ul>`;
      } else if (v.change_type === 'initial') {
        html += '<ul class="version-bullets"><li>First indexed</li></ul>';
      }

      html += `</div>`;
    }
    html += '</div>';

    // Compare button (if more than 1 version)
    if (data.versions.length > 1) {
      html += `<button class="btn btn-ghost btn-sm mt-1" onclick="openDiffModal('${bulkFileId}', ${data.versions[data.versions.length - 1].version_number}, ${data.versions[0].version_number})">Compare first & latest</button>`;
    }

    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div class="text-sm text-muted">Could not load version history.</div>`;
  }
}

function _changeTypeLabel(type) {
  const labels = {
    initial: 'Initial',
    content_change: 'Content Changed',
    metadata_change: 'Metadata Changed',
    moved: 'Moved',
    restored: 'Restored',
    marked_deleted: 'Marked for Deletion',
    trashed: 'Trashed',
    purged: 'Purged',
  };
  return labels[type] || type;
}

function _changeTypeIcon(type) {
  const icons = {
    initial: '+',
    content_change: '~',
    moved: '->',
    restored: '<-',
    marked_deleted: '!',
    trashed: 'x',
    purged: '-',
  };
  return icons[type] || '*';
}

function _escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Open a modal showing diff between two versions.
 */
async function openDiffModal(bulkFileId, v1, v2) {
  // Create or reuse modal dialog
  let dialog = document.getElementById('diff-modal');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'diff-modal';
    dialog.className = 'modal-dialog';
    dialog.innerHTML = `
      <div class="modal-content" style="max-width:700px;max-height:80vh;overflow:auto">
        <div class="modal-header">
          <h3>Version Comparison</h3>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('diff-modal').close()">&times;</button>
        </div>
        <div id="diff-modal-body" style="padding:1rem"></div>
      </div>
    `;
    document.body.appendChild(dialog);
  }

  const body = document.getElementById('diff-modal-body');
  body.innerHTML = '<div class="text-sm text-muted">Loading diff...</div>';
  dialog.showModal();

  try {
    const data = await API.get(`/api/lifecycle/files/${bulkFileId}/diff/${v1}/${v2}`);
    let html = '';

    // Summary
    if (data.summary && data.summary.length) {
      html += '<h4>Summary</h4><ul>';
      for (const s of data.summary) {
        html += `<li>${_escapeHtml(s)}</li>`;
      }
      html += '</ul>';
    }

    // Stats
    if (data.lines_added || data.lines_removed) {
      html += `<div class="text-sm text-muted mt-1">+${data.lines_added} / -${data.lines_removed} lines</div>`;
    }

    // Patch
    if (data.patch) {
      html += `<h4 class="mt-1">Diff</h4><pre class="diff-patch">${_escapeHtml(data.patch)}</pre>`;
    } else if (data.patch_truncated) {
      html += '<div class="text-sm text-muted mt-1">Full diff is too large to display.</div>';
    }

    body.innerHTML = html;
  } catch (err) {
    body.innerHTML = `<div class="text-sm text-muted">Could not load diff.</div>`;
  }
}
