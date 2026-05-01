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

## New Interface Toggle

The **New interface** toggle in Display preferences switches between the original MarkFlow UI and the redesigned search-as-home interface. Your preference is saved per-user and overrides any system default.

## Operator Settings

Operators and admins can configure system-wide defaults in **Settings -> Appearance**:

- **New interface (default)** -- sets whether new users see the original or new UI
- **Allow per-user display overrides** -- when disabled, the Display preferences option is hidden from the avatar menu for all users

The `ENABLE_NEW_UX` environment variable acts as a deployment-level override of the system DB default (it does not override individual user preferences).
