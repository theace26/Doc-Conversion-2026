# Keyboard Shortcuts

MarkFlow is primarily a mouse-driven application, so there are no elaborate
keyboard shortcut systems to memorize. That said, a handful of keyboard
interactions are built into the interface, and your browser provides several
more that work well with MarkFlow's pages.

---

## Search Page

The search input field has `autofocus`, which means your cursor is already
in the search box when the page loads. Just start typing.

| Key | Action |
|-----|--------|
| Any character | Starts typing in the focused search box |
| Enter | Submits the current search query |
| Arrow Down | Moves down through autocomplete suggestions |
| Arrow Up | Moves up through autocomplete suggestions |
| Enter (with suggestion highlighted) | Selects the highlighted suggestion and runs the search |
| Escape | Closes the autocomplete dropdown |

The autocomplete dropdown appears after you type at least two characters.
It is debounced (200 milliseconds), so you can type continuously without
triggering a suggestion on every keystroke. Once the dropdown is visible,
the arrow keys let you pick a suggestion without reaching for the mouse.

> **Tip:** If you already know the exact title, type the first few letters,
> wait for the dropdown, then press Arrow Down and Enter. This is often
> faster than typing the full title and clicking Search.

---

## Upload and Convert Page

On the Convert page (`/index.html`), the file input area accepts files
via drag-and-drop, but you can also trigger the file picker from the
keyboard:

| Key | Action |
|-----|--------|
| Tab to the upload area, then Enter or Space | Opens the file picker dialog |
| Tab to the Convert button, then Enter | Starts conversion |

The direction toggle (Markdown-to-original vs. original-to-Markdown) is a
set of radio buttons. You can Tab to them and use the arrow keys to switch
between directions.

---

## Forms and Settings

MarkFlow uses standard HTML form elements throughout. The usual keyboard
conventions apply on every page:

| Key | Action |
|-----|--------|
| Tab | Move to the next form field |
| Shift + Tab | Move to the previous form field |
| Space | Toggle a checkbox or open a dropdown |
| Enter | Click the currently focused button |
| Escape | Close a dialog or confirmation modal |

On the **Settings** page, range sliders (like the OCR confidence threshold
and worker count) respond to the arrow keys:

| Key | Action |
|-----|--------|
| Left Arrow | Decrease the slider value by one step |
| Right Arrow | Increase the slider value by one step |
| Home | Jump to the minimum value |
| End | Jump to the maximum value |

---

## Dialog Boxes and Confirmations

Several actions in MarkFlow -- revoking an API key, repairing the database,
resetting preferences, or stopping all jobs -- show a browser confirmation
dialog. These respond to:

| Key | Action |
|-----|--------|
| Enter | Confirm (same as clicking OK) |
| Escape | Cancel (same as clicking Cancel) |

The FolderPicker modal on the Locations page uses the HTML `<dialog>`
element, which also closes with Escape.

---

## Status and Admin Pages

The Status page and Admin page are largely read-only displays with action
buttons. You can Tab to any button (Stop, Pause, Resume, Refresh, Apply
Changes) and press Enter to activate it.

On the Admin page, the **Resource Controls** section is inside a collapsible
`<details>` element. When it is focused, press Enter or Space to expand or
collapse it.

---

## Useful Browser Shortcuts

Because MarkFlow is a multi-page web application (not a single-page app),
standard browser navigation shortcuts are especially helpful:

| Shortcut | Action |
|----------|--------|
| Ctrl + L (Cmd + L on Mac) | Focus the browser address bar -- type a page name like `/admin.html` to navigate directly |
| Alt + Left Arrow | Go back to the previous page |
| Alt + Right Arrow | Go forward |
| Ctrl + R (Cmd + R) | Reload the current page |
| Ctrl + Shift + R (Cmd + Shift + R) | Hard reload -- bypasses cache, useful after a MarkFlow update |
| Ctrl + F (Cmd + F) | Open browser find-in-page -- great for long History or Admin tables |
| Ctrl + + / Ctrl + - | Zoom in or out (the layout is responsive and adapts) |
| F12 | Open developer tools -- useful when reporting bugs |

> **Tip:** If a page seems stuck or data looks stale, try Ctrl + Shift + R
> to do a hard reload. This ensures you are loading the latest JavaScript
> and CSS from the server.

---

## Quick Page Reference

Rather than tabbing through nav links, use the browser address bar
(Ctrl + L) and type one of these paths:

| Page | URL |
|------|-----|
| Search | `/search.html` |
| Status | `/status.html` |
| Convert | `/index.html` |
| History | `/history.html` |
| Bulk Jobs | `/bulk.html` |
| Trash | `/trash.html` |
| Resources | `/resources.html` |
| Settings | `/settings.html` |
| Admin | `/admin.html` |
| Debug | `/debug` |

---

## Accessibility Notes

MarkFlow uses semantic HTML (`<nav>`, `<main>`, `<section>`, `<table>`) and
standard form elements, which means screen readers and assistive technologies
can navigate the interface effectively. All interactive elements are reachable
via Tab, and buttons and links have visible focus indicators styled by the
MarkFlow design system.

Dark mode activates automatically based on your operating system preference
(via CSS `prefers-color-scheme`), and the color contrast ratios are designed
to meet readability standards in both light and dark themes.

If you rely on keyboard navigation and find an element that cannot be
reached or does not have a visible focus state, please report it as a bug.

---

## Related Articles

- [Searching Your Documents](/help#search) -- full guide to search and filters
- [Settings Reference](/help#settings-guide) -- all form controls explained
- [Troubleshooting](/help#troubleshooting) -- what to do when things are not
  responding
