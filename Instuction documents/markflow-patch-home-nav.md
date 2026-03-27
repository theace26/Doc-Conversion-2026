# MarkFlow Patch: Add Home Nav Link
# Version: patch-0.7.4a
# Scope: Nav bar only — two files, no API changes, no schema changes.

---

## What This Patch Does

Adds a "Home" link to the shared navigation bar, positioned before "Convert".
Both "Home" and "Convert" link to `/`. The active link highlighter is updated
so both highlight when the user is on the index page.

---

## Files to Modify

### 1. `static/markflow.css` or shared nav HTML

Locate the nav bar HTML. It will look like this:

```html
<nav class="nav-bar">
  <a href="/" class="nav-logo">MarkFlow</a>
  <div class="nav-links">
    <a href="/" class="nav-link">Convert</a>
    ...
  </div>
</nav>
```

Add the Home link **before** the Convert link:

```html
<nav class="nav-bar">
  <a href="/" class="nav-logo">MarkFlow</a>
  <div class="nav-links">
    <a href="/" class="nav-link">Home</a>
    <a href="/" class="nav-link">Convert</a>
    ...
  </div>
</nav>
```

If the nav bar is defined inline in each HTML file rather than in a shared
component, make this change in every user-facing page:
- `static/index.html`
- `static/bulk.html`
- `static/search.html`
- `static/history.html`
- `static/settings.html`
- `static/locations.html`
- `static/providers.html`
- `static/bulk-review.html`
- `static/progress.html`

Do NOT add the Home link to:
- `static/review.html` (has its own contextual header)
- `static/debug.html` (standalone developer tool)

---

### 2. `static/app.js`

Find the nav link active-state highlighter. It will look something like:

```javascript
const path = window.location.pathname;
document.querySelectorAll(".nav-link").forEach(link => {
    if (link.getAttribute("href") === path) {
        link.classList.add("nav-link--active");
    }
});
```

Replace it with logic that handles the dual Home/Convert case:

```javascript
const path = window.location.pathname;
const isIndexPage = path === "/" || path === "/index.html";

document.querySelectorAll(".nav-link").forEach(link => {
    const href = link.getAttribute("href");
    let active = false;

    if (isIndexPage) {
        // Both Home and Convert point to "/" — highlight both on the index page
        active = href === "/";
    } else {
        // All other pages: exact or prefix match, skip "/" to avoid
        // highlighting Home/Convert on every page
        active = href !== "/" && path.startsWith(href);
    }

    link.classList.toggle("nav-link--active", active);
});
```

---

## Done Criteria

- [ ] "Home" link appears before "Convert" in the nav bar on all user-facing pages
- [ ] Both "Home" and "Convert" navigate to `/`
- [ ] Both "Home" and "Convert" are highlighted when on the index page
- [ ] No other page has both highlighted
- [ ] `review.html` and `debug.html` are not modified
- [ ] No console errors in browser devtools after the change

---

## Notes for Claude Code

- This is a cosmetic patch only. Do not modify any Python files.
- If the nav bar HTML is generated from a shared template or JS component,
  make the change in exactly one place. If it is copy-pasted into each HTML
  file individually, update every file listed above.
- Check CLAUDE.md to confirm how the nav bar is currently implemented before
  making any edits.
- No version tag required for this patch. No CLAUDE.md update required.
