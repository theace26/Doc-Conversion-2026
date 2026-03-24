/**
 * MarkFlow — shared JS utilities (fetch helpers, common UI patterns).
 * Loaded on all pages.
 */

const API = {
    async get(url) {
        const res = await fetch(url);
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            const msg = body.detail || `GET ${url} failed (${res.status})`;
            const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            err.status = res.status;
            throw err;
        }
        return res.json();
    },
    async post(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            const msg = data.detail || `POST ${url} failed (${res.status})`;
            const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            err.status = res.status;
            throw err;
        }
        return res.json();
    },
    async upload(url, formData) {
        const res = await fetch(url, { method: 'POST', body: formData });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            const msg = data.detail || `Upload failed (${res.status})`;
            const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            err.status = res.status;
            throw err;
        }
        return res.json();
    },
    async put(url, body) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            const msg = data.detail || `PUT ${url} failed (${res.status})`;
            const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            err.status = res.status;
            throw err;
        }
        return res.json();
    },
};

function showError(message) {
    const el = document.getElementById('error-banner');
    if (el) {
        el.textContent = message;
        el.hidden = false;
        el.classList.add('error-banner');
    } else {
        console.error(message);
    }
}

function hideError() {
    const el = document.getElementById('error-banner');
    if (el) { el.hidden = true; el.textContent = ''; }
}

function formatBytes(bytes) {
    if (bytes == null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatDuration(ms) {
    if (ms == null || ms === 0) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function timeAgo(isoString) {
    if (!isoString) return '—';
    const diff = (Date.now() - new Date(isoString)) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

function formatDate(isoString) {
    if (!isoString) return '—';
    try {
        const d = new Date(isoString);
        const now = new Date();
        const today = now.toDateString();
        const yesterday = new Date(now - 86400000).toDateString();
        if (d.toDateString() === today) return 'Today ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        if (d.toDateString() === yesterday) return 'Yesterday ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        return d.toLocaleDateString([], {month:'short', day:'numeric'}) + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    } catch { return isoString; }
}

function formatBadge(fmt) {
    const f = (fmt || '').toLowerCase();
    return `<span class="badge badge-${f}">${f.toUpperCase()}</span>`;
}

function showToast(message, type = 'success') {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        document.body.appendChild(toast);
    }
    toast.className = `toast toast-${type} visible`;
    toast.textContent = message;
    setTimeout(() => { toast.classList.remove('visible'); }, 3000);
}

// Set active nav link
document.addEventListener('DOMContentLoaded', () => {
    const path = location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href === '/' && (path === '/' || path === '/index.html')) {
            link.classList.add('nav-link--active');
        } else if (href !== '/' && path.startsWith(href.replace('.html', ''))) {
            link.classList.add('nav-link--active');
        }
    });
});
