# How to build a new-UX page (~30 minutes)

This directory contains copy-paste templates for building new-UX equivalents
of legacy MarkFlow pages. Target time per page is 30 minutes once you're
familiar with the pattern.

The canonical reference implementation is `static/convert-new.html` +
`static/js/convert-new-boot.js` + `static/js/pages/convert.js`.

---

## 5-step guide

### Step 1 — Create the HTML file

```bash
cp docs/templates/new-ux-page.html static/{{PAGE_ID}}-new.html
```

Open the file and replace every `{{PLACEHOLDER}}`:

| Placeholder | Replace with |
|---|---|
| `{{PAGE_TITLE}}` | Human-readable title, e.g. `History` |
| `{{PAGE_ID}}` | URL-slug ID, e.g. `history` |
| `{{COMPONENT_NAME}}` | PascalCase global name, e.g. `History` |

The `data-env="dev"` attribute on `<body>` can be removed in production builds.

---

### Step 2 — Create the boot script

```bash
cp docs/templates/new-ux-page-boot.js static/js/{{PAGE_ID}}-new-boot.js
```

Replace all `{{PLACEHOLDER}}` values (same set as step 1), then:

- Set `activePage` in `MFTopNav.mount()` to the nav item this page lives under
  (`'search'`, `'activity'`, `'convert'`, or `null`).
- Set the correct `role` fallback in `fetchMe()` — member for end-user pages,
  operator for admin/ops pages.

---

### Step 3 — Create the page component

```bash
cp docs/templates/new-ux-page-component.js static/js/pages/{{PAGE_ID}}.js
```

Replace all `{{PLACEHOLDER}}` values, then:

- Update `API_LIST` / `API_DETAIL` constants to the actual API endpoints.
- Update `renderItem()` to match your data shape.
- Set `POLL_MS` if the page auto-refreshes (e.g. `15000` for activity pages).
- Add any page-specific actions (operator-gated, admin-gated).

---

### Step 4 — Wire the server route

In `main.py`, add a dispatched route using `serve_ux_page()`.

If the page has both new-UX and original-UX equivalents:

```python
@app.get("/{{PAGE_ID}}", include_in_schema=False)
async def {{PAGE_ID}}_page(request: Request):
    """{{PAGE_TITLE}} — per-user UX dispatch."""
    return serve_ux_page(request, "static/{{PAGE_ID}}-new.html", "static/{{PAGE_ID}}.html")
```

If the page is new-UX only (no original equivalent):

```python
@app.get("/{{PAGE_ID}}", include_in_schema=False)
async def {{PAGE_ID}}_page():
    return FileResponse("static/{{PAGE_ID}}-new.html")
```

Add the route in the correct section of `main.py` (Settings block, Help block, etc.).

---

### Step 5 — Wire the avatar menu

In `static/js/components/avatar-menu-wiring.js`, add the canonical path to
`URLS_NEW` (and optionally to `URLS_ORIGINAL` if you're retiring the old page):

```js
var URLS_NEW = {
  // existing entries ...
  '{{PAGE_ID}}': '/{{PAGE_ID}}',   // canonical server-dispatched path
};
```

If this page replaces an original-UX page in `URLS_ORIGINAL`, update that
entry too to point at the canonical path instead of the `.html` file.

---

## Where files live

| File | Purpose |
|---|---|
| `static/{{PAGE_ID}}-new.html` | HTML shell (pref-flash guard, script tags) |
| `static/js/{{PAGE_ID}}-new-boot.js` | Wires chrome + page component after `/api/me` |
| `static/js/pages/{{PAGE_ID}}.js` | Page logic + rendering |
| `main.py` (updated) | Server-side route dispatching |
| `static/js/components/avatar-menu-wiring.js` (updated) | Avatar menu URL map |

---

## Do NOT inject ux-fallback.js into new-UX pages

`ux-fallback.js` is only injected into original-only pages (ones that have no
new-UX equivalent). Once you build a new-UX equivalent and add the
`serve_ux_page()` route, remove the `ux-fallback.js` injection from the original
page — both UX modes now work correctly for that URL.

---

## Page inventory

See `docs/new-ux-pages.md` for a full list of every page in the app with its
current UX status, API endpoints, and build priority order.
