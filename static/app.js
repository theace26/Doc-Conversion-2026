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
    async del(url) {
        const res = await fetch(url, { method: 'DELETE' });
        if (!res.ok && res.status !== 204) {
            const data = await res.json().catch(() => ({}));
            const msg = data.detail || `DELETE ${url} failed (${res.status})`;
            const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            err.status = res.status;
            err.data = data;
            throw err;
        }
        if (res.status === 204) return null;
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

// ── Location picker helper ──────────────────────────────────────────────────

async function populateLocationSelect(selectEl, type, selectedId = null) {
    const locations = await API.get(`/api/locations?type=${type}`);
    selectEl.innerHTML = '';
    if (locations.length === 0) {
        selectEl.innerHTML = '<option value="" disabled selected>(none available)</option>';
        selectEl.disabled = true;
        return locations;
    }
    locations.forEach(loc => {
        const opt = document.createElement('option');
        opt.value = loc.id;
        opt.textContent = loc.name;
        opt.dataset.path = loc.path;
        if (loc.id === selectedId) opt.selected = true;
        selectEl.appendChild(opt);
    });
    selectEl.disabled = false;
    if (locations.length === 1) selectEl.value = locations[0].id;
    return locations;
}

// ── Role-aware navigation ────────────────────────────────────────────────────

const NAV_ITEMS = [
    { href: "/search.html",     label: "Search",    minRole: "search_user" },
    { href: "/status.html",     label: "Status",    minRole: "search_user", badge: true },
    { href: "/index.html",      label: "Convert",   minRole: "operator"    },
    { href: "/history.html",    label: "History",   minRole: "operator"    },
    { href: "/bulk.html",       label: "Bulk Jobs", minRole: "manager"     },
    { href: "/trash.html",      label: "Trash",     minRole: "manager"     },
    { href: "/resources.html",  label: "Resources", minRole: "manager"     },
    { href: "/settings.html",   label: "Settings",  minRole: "manager"     },
    { href: "/admin.html",      label: "Admin",     minRole: "admin"       },
    { href: "/help.html",       label: "Help",      minRole: "search_user" },
];

const ROLE_HIERARCHY = ["search_user", "operator", "manager", "admin"];

function roleGte(userRole, minRole) {
    return ROLE_HIERARCHY.indexOf(userRole) >= ROLE_HIERARCHY.indexOf(minRole);
}

async function buildNav() {
    const nav = document.getElementById('main-nav');
    if (!nav) return;

    let role = "search_user";
    try {
        const res = await fetch("/api/auth/me");
        if (res.ok) {
            const data = await res.json();
            role = data.role || "search_user";
        }
    } catch { /* default to search_user */ }

    const currentPath = window.location.pathname;
    nav.innerHTML = '';

    NAV_ITEMS
        .filter(item => roleGte(role, item.minRole))
        .forEach(item => {
            const a = document.createElement('a');
            a.href = item.href;
            a.textContent = item.label;
            a.className = 'nav-link';
            if (item.badge) {
                const badge = document.createElement('span');
                badge.className = 'nav-badge';
                badge.style.display = 'none';
                a.appendChild(badge);
            }
            const hrefBase = item.href.replace('.html', '');
            const isActive = currentPath === item.href
                || currentPath.startsWith(hrefBase)
                || (item.href === '/index.html' && currentPath === '/');
            if (isActive) a.classList.add('nav-link--active');
            nav.appendChild(a);
        });

    // Load status badge script dynamically and init after it loads
    _loadStatusBadge();

    // Load contextual help link component
    var helpScript = document.createElement('script');
    helpScript.src = '/static/js/help-link.js';
    document.head.appendChild(helpScript);
}

function _loadStatusBadge() {
    if (typeof initStatusBadge === 'function') {
        initStatusBadge();
        return;
    }
    var script = document.createElement('script');
    script.src = '/static/js/global-status-bar.js';
    script.onload = function () {
        if (typeof initStatusBadge === 'function') initStatusBadge();
    };
    document.head.appendChild(script);
}

// ── Client event logging (developer mode) ────────────────────────────────────

window._devLoggingEnabled = false;

async function logClientEvent(event, target, detail = "") {
    if (!window._devLoggingEnabled) return;
    try {
        await fetch("/api/log/client-event", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ page: location.pathname, event, target, detail })
        });
    } catch { /* never throw */ }
}

// Check dev logging on load
async function _initDevLogging() {
    try {
        const data = await fetch("/api/preferences").then(r => r.ok ? r.json() : null);
        if (data) {
            const prefs = data.preferences || data;
            window._devLoggingEnabled = (prefs.log_level === "developer");
        }
    } catch { /* ignore */ }
}

// ── Instrument user actions ────────────────────────────────────────────────────

function _instrumentActions() {
    // Nav link clicks
    const nav = document.getElementById('main-nav');
    if (nav) {
        nav.addEventListener('click', (e) => {
            const link = e.target.closest('a');
            if (link) logClientEvent('nav_click', link.textContent.trim(), link.href);
        });
    }

    // Global delegated button instrumentation for known action buttons
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('button, [role="button"]');
        if (!btn) return;
        const id = btn.id || '';
        const text = btn.textContent.trim().substring(0, 40);

        // Instrument specific known action buttons
        const tracked = [
            'btn-convert', 'btn-save', 'btn-reset', 'reset-confirm',
            'start-btn', 'pause-btn', 'cancel-btn',
            'stop-all-btn', 'reset-stop-btn',
        ];
        if (tracked.includes(id)) {
            logClientEvent('click', id, text);
        }
    });

    // Form submissions
    document.addEventListener('submit', (e) => {
        const form = e.target;
        const id = form.id || form.action || 'unknown-form';
        logClientEvent('form_submit', id);
    });
}

// Build nav on page load
document.addEventListener('DOMContentLoaded', async () => {
    await buildNav();
    _instrumentActions();
    _initDevLogging();
});
