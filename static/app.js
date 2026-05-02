/**
 * MarkFlow — shared JS utilities (fetch helpers, common UI patterns).
 * Loaded on all pages.
 */

function _throwOnError(res, fallbackMsg) {
    return res.json().catch(() => ({})).then(data => {
        const msg = data.detail || fallbackMsg;
        const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        err.status = res.status;
        err.data = data;
        throw err;
    });
}

const API = {
    async get(url) {
        const res = await fetch(url);
        if (!res.ok) return _throwOnError(res, `GET ${url} failed (${res.status})`);
        return res.json();
    },
    async post(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) return _throwOnError(res, `POST ${url} failed (${res.status})`);
        return res.json();
    },
    async upload(url, formData) {
        const res = await fetch(url, { method: 'POST', body: formData });
        if (!res.ok) return _throwOnError(res, `Upload failed (${res.status})`);
        return res.json();
    },
    async del(url) {
        const res = await fetch(url, { method: 'DELETE' });
        if (!res.ok && res.status !== 204) return _throwOnError(res, `DELETE ${url} failed (${res.status})`);
        if (res.status === 204) return null;
        return res.json();
    },
    async put(url, body) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) return _throwOnError(res, `PUT ${url} failed (${res.status})`);
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

/**
 * Parse a backend ISO timestamp as UTC. Appends "Z" when the offset
 * suffix is missing so the browser doesn't treat it as local time.
 */
function parseUTC(isoString) {
    if (!isoString) return null;
    let s = String(isoString);
    // SQLite datetime('now') produces "YYYY-MM-DD HH:MM:SS" (space, no T, no offset).
    // Normalize to ISO 8601 with T separator so Date() can parse it.
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) {
        s = s.replace(' ', 'T');
    }
    // Backend stores all timestamps in UTC. Append Z if no offset present.
    if (s.includes('T') && !s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) {
        s += 'Z';
    }
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
}

/**
 * Format an ISO timestamp as local time, always showing full date + time.
 * Use this anywhere a date/time is displayed to the user.
 */
function formatLocalTime(isoString) {
    if (!isoString) return '—';
    try {
        const d = parseUTC(isoString);
        if (!d) return isoString;
        return d.toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: 'numeric', minute: '2-digit',
        });
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
    { href: "/pipeline-files.html", label: "Files", minRole: "operator"    },
    { href: "/index.html",      label: "Convert",   minRole: "operator"    },
    { href: "/history.html",    label: "History",   minRole: "operator"    },
    { href: "/bulk.html",       label: "Bulk Jobs", minRole: "manager"     },
    { href: "/batch-management.html", label: "Batches", minRole: "manager" },
    { href: "/trash.html",      label: "Trash",     minRole: "manager"     },
    { href: "/resources.html",  label: "Resources", minRole: "manager"     },
    { href: "/storage.html",    label: "Storage",   minRole: "manager"     },
    { href: "/settings.html",   label: "Settings",  minRole: "manager"     },
    { href: "/flagged.html",    label: "Flagged",   minRole: "admin"       },
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

    // Inject version badge next to logo
    const logo = document.querySelector('.nav-logo');
    if (logo) {
        try {
            const vRes = await fetch('/api/version');
            if (vRes.ok) {
                const vData = await vRes.json();
                const badge = document.createElement('span');
                badge.className = 'version-badge';
                badge.textContent = 'v' + vData.version;
                logo.appendChild(badge);
            }
        } catch { /* version badge is non-critical */ }
    }

    // Load status badge script dynamically and init after it loads
    _loadStatusBadge();

    // Load contextual help link component
    var helpScript = document.createElement('script');
    helpScript.src = '/static/js/help-link.js';
    document.head.appendChild(helpScript);

    // Avatar menu with Display Preferences drawer (original UX)
    _loadAvatarMenu();
}

function _loadAvatarMenu() {
    const nav = document.getElementById('main-nav');
    if (!nav || document.getElementById('mf-orig-avatar-slot')) return;

    const slot = document.createElement('div');
    slot.id = 'mf-orig-avatar-slot';
    nav.appendChild(slot);

    // Bring in component styles (mf-* tokens + avatar/menu CSS)
    if (!document.querySelector('link[href*="components.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/css/components.css';
        document.head.appendChild(link);
    }

    function _loadScript(src, cb) {
        if (document.querySelector('script[src="' + src + '"]')) { cb(); return; }
        const s = document.createElement('script');
        s.src = src;
        s.onload = cb;
        document.head.appendChild(s);
    }

    _loadScript('/static/js/preferences.js', function () {
        _loadScript('/static/js/components/avatar.js', function () {
            _loadScript('/static/js/components/avatar-menu.js', function () {
                _loadScript('/static/js/components/display-prefs-drawer.js', function () {
                    _loadScript('/static/js/components/avatar-menu-wiring.js', function () {
                        if (MFPrefs && typeof MFPrefs.load === 'function') { MFPrefs.load(); }
                        fetch('/api/me', { credentials: 'same-origin' })
                            .then(function (r) { return r.ok ? r.json() : null; })
                            .catch(function () { return null; })
                            .then(function (me) {
                                const user = {
                                    name:  (me && me.name)  || '',
                                    role:  (me && me.role)  || 'member',
                                    scope: (me && me.scope) || '',
                                };
                                const build = (me && me.build) || null;
                                MFAvatarMenuWiring.mount(slot, { user: user, build: build, pageSet: 'original' });
                            });
                    });
                });
            });
        });
    });
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
    _loadStorageRestartBanner();
});

// v0.25.0: inject the Universal Storage Manager restart-banner script once on
// every page that loads app.js, without needing to touch each individual HTML
// file. The banner polls /api/storage/restart-status every 60s.
function _loadStorageRestartBanner() {
    if (document.getElementById('storage-restart-banner-script')) return;
    const s = document.createElement('script');
    s.id = 'storage-restart-banner-script';
    s.src = '/static/js/storage-restart-banner.js';
    s.defer = true;
    document.head.appendChild(s);
}
