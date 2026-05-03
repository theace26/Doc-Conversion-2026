# Customizing Your Display

MarkFlow lets you personalize fonts, colors, text size, and interface style. All preferences save automatically and sync across sessions.

## Opening Display Preferences

Click your **avatar** in the top-right corner -> **Display preferences**. The drawer slides in from the right.

## Themes

Choose from 28 color themes organized in six groups:

| Group | Description |
|---|---|
| **Original UX** | Classic Light, Classic Dark, Cobalt, Sage, Slate, Crimson, Sandstone, Graphite |
| **New UX** | Nebula, Aurora, Cobalt, Rose Quartz, Midnight Slate, Forest, Obsidian, Dusk |
| **High Contrast** | HC Light, HC Dark, HC Light+, HC Dark+ |
| **Pastel** | Lavender, Mint, Lavender+, Mint+ |
| **Seasonal (Original)** | Spring, Summer, Fall, Winter |
| **Seasonal (New UX)** | Spring+, Summer+, Fall+, Winter+ |

Themes apply instantly -- no page reload. When you switch interface mode (see below), your theme automatically migrates to the matching theme in the other group.

## Fonts

14 typefaces are available:

- **System UI** -- your OS default (fastest to load)
- **Sans-serif:** Inter, IBM Plex Sans, Roboto, Source Sans 3, Lato, Nunito, Raleway, Poppins, DM Sans
- **Serif:** Merriweather, Playfair Display, Crimson Pro
- **Monospace:** JetBrains Mono

Each option is previewed in its own typeface inside the picker.

## Text Size

Four steps, independent of your browser zoom:

| Setting | Scale |
|---|---|
| Small | 0.84x |
| Default | 1x |
| Large | 1.18x |
| X-Large | 1.36x |

## New Interface Toggle (v0.39.0+)

The **New interface** toggle in Display preferences switches between the original MarkFlow UI and the redesigned search-as-home interface. Your preference is saved per-user via cookie + server pref and persists across sessions, devices, and browsers.

**How it works under the hood:** when you flip the toggle, MarkFlow sets a `mf_use_new_ux` cookie (1 or 0) and writes the preference to your account. On every page request, the server reads the cookie and serves the matching HTML — `index-new.html` (or `convert-new.html`, `help-new.html`, etc.) if you're in new UX, the original file otherwise.

**Pages that don't yet have a new-UX twin** (Status, History, Locations, Bulk, Pipeline Files, Viewer, and a few admin-only surfaces) auto-fall-back to the original interface. The toggle is updated to reflect the actual mode you ended up in, so it never lies.

**To use the new UI:**

1. Click your avatar -> **Display preferences**.
2. Flip the **New interface** toggle on.
3. Pages re-render in new UX. The toggle persists; you don't need to flip it again on the next visit.

To go back, flip the toggle off in any avatar menu.

## Match-system Auto-switch (v0.39.0+)

The **Match system** toggle in Display preferences makes MarkFlow follow your operating system's light/dark setting. When you turn it on:

1. Pick one light theme (Classic Light, Sage, Lavender, Spring, etc.) — used while your OS is in light mode.
2. Pick one dark theme (Classic Dark, Obsidian, Midnight Slate, Spring+, etc.) — used while your OS is in dark mode.
3. MarkFlow swaps between your two choices in real time as your OS preference changes.

Turn the toggle off to use a single theme regardless of OS. Your two saved choices are remembered for the next time you turn it on.

**When this is useful:** if you keep your OS in light mode during the day and dark mode at night, Match system means MarkFlow tracks the change automatically without you flipping themes by hand.

## Operator Settings

Operators and admins can configure system-wide defaults in **Settings -> Appearance**:

- **New interface (default)** -- sets whether new users see the original or new UI
- **Allow per-user display overrides** -- when disabled, the Display preferences option is hidden from the avatar menu for all users

The `ENABLE_NEW_UX` environment variable acts as a deployment-level override of the system DB default (it does not override individual user preferences).
