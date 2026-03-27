# MarkFlow v0.10.0 Patch: In-App Help Wiki & Contextual Help System

> **Patch target:** New files + modifications to every existing `static/*.html` page  
> **Purpose:** Build an in-app help wiki accessible at `/help`, add contextual "?" help icons throughout the UI, add inline descriptions under every Settings section, and place a "Help" link in the global nav.  
> **Grounded in:** CLAUDE.md as of v0.9.8. All file paths, table names, page names, route patterns, CSS class names, and JS conventions match the running codebase.

---

## 1. What This Patch Does

MarkFlow has grown into a large application with 15+ pages, dozens of settings, and features ranging from document conversion to GPU-accelerated password cracking. There is no in-app documentation. Users have to figure everything out on their own.

This patch adds:

1. **A help wiki** (`/help`) — a browsable, searchable documentation site served inside the MarkFlow Docker container. Written in Markdown, rendered to HTML at runtime via `mistune`. No external dependencies beyond what's already installed.

2. **Contextual "?" buttons** — small circular help icons placed next to feature headings, form groups, and page titles. Clicking opens the relevant wiki article (or scrolls to the relevant section within one).

3. **Inline setting descriptions** — short helper text rendered beneath each setting group in `settings.html`, pulled from a `help_text` property already present in `_PREFERENCE_SCHEMA`.

4. **A global "Help" nav link** — added to the navigation bar on every page, right-aligned, with a "?" icon.

---

## 2. Architecture Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Wiki content format | Markdown files in `docs/help/` | Easy to write/edit, same format MarkFlow already processes |
| Rendering engine | `mistune` (already a project dependency) | Already installed, fast, pure Python |
| Routing | Single FastAPI route `GET /api/help/{slug}` + static `help.html` | Consistent with existing vanilla HTML + fetch pattern |
| Search within wiki | Client-side text search via JS | No need for Meilisearch overhead for ~20 articles |
| "?" buttons | `data-help` attributes + shared JS handler | Minimal per-page code, one shared component |
| Article linking | Slug-based (`getting-started`, `bulk-conversion`) | Clean URLs, easy to reference |

**Architecture rules followed:**
- No SPA — vanilla HTML + fetch calls
- No new Python dependencies (mistune is already installed)
- No localStorage (search state is ephemeral)
- structlog for any new logging
- Role-aware: help is accessible to ALL roles (including `search_user`)

---

## 3. Help Wiki Content Structure

### 3.1 Article List

Each article is a `.md` file in `docs/help/`. The filename (without extension) is the slug.

| Slug | Title | Covers |
|------|-------|--------|
| `getting-started` | Getting Started | What MarkFlow is, first-time setup, the home page, uploading your first file |
| `document-conversion` | Document Conversion | Supported formats, upload UI, direction toggle (to-md / from-md), fidelity tiers, batch processing, downloading results |
| `fidelity-tiers` | Fidelity Tiers Explained | Tier 1 (structure), Tier 2 (style sidecar), Tier 3 (original patching), when each applies, examples |
| `ocr-pipeline` | OCR & Scanned Documents | How OCR detection works, confidence scores, the review UI, unattended mode, bulk OCR skip-and-review |
| `bulk-conversion` | Bulk Repository Conversion | What bulk conversion is, locations setup, starting a job, pause/resume/cancel, incremental re-scanning, the status page |
| `search` | Searching Your Documents | How Meilisearch indexing works, the search page, autocomplete, filtering by format/index, what's searchable |
| `file-lifecycle` | File Lifecycle & Versioning | How MarkFlow tracks changes in the source share, version history, diffs, soft-delete pipeline, trash management, grace periods |
| `password-recovery` | Password-Protected Documents | Two protection layers (restrictions vs encryption), the cracking cascade, GPU acceleration, the host worker, supplying known passwords |
| `adobe-files` | Adobe File Indexing | What Level 2 indexing means, which Adobe formats are supported, what gets extracted, searching Adobe metadata |
| `unrecognized-files` | Unrecognized Files | What happens when the scanner finds a file type it can't convert, MIME classification, the unrecognized files page, CSV export |
| `settings-guide` | Settings Reference | Every settings section explained: conversion, OCR, bulk, LLM providers, password recovery, logging, MCP |
| `llm-providers` | LLM Provider Setup | Adding API keys, verifying connections, activating a provider, Ollama local setup, what LLM enhancement does (OCR correction, summaries, heading inference) |
| `status-page` | Status & Active Jobs | Reading the status page, job cards, progress bars, per-directory stats, STOP ALL, lifecycle scanner card |
| `admin-tools` | Administration | Admin panel overview, API key management, database tools, disk usage, resource controls |
| `resources-monitoring` | Resources & Monitoring | The resources page, CPU/memory charts, disk growth, activity log, CSV export |
| `mcp-integration` | AI Assistant Integration | What MCP is, connecting to Claude.ai, Cowork pattern, available MCP tools, Cloudflare Tunnel setup |
| `gpu-setup` | GPU Acceleration Setup | NVIDIA container path, AMD/Intel host worker, detecting your GPU, the host worker script |
| `troubleshooting` | Troubleshooting | Common issues, container logs, stale volumes, the debug dashboard, health check |
| `keyboard-shortcuts` | Keyboard Shortcuts | Any keyboard navigation available (search focus, etc.) |

### 3.2 Article Index File

A `docs/help/_index.json` file defines order, titles, categories, and short descriptions:

```json
{
  "categories": [
    {
      "name": "Basics",
      "icon": "book",
      "articles": [
        {
          "slug": "getting-started",
          "title": "Getting Started",
          "description": "First-time setup and your first conversion"
        },
        {
          "slug": "document-conversion",
          "title": "Document Conversion",
          "description": "Upload, convert, and download documents"
        },
        {
          "slug": "fidelity-tiers",
          "title": "Fidelity Tiers Explained",
          "description": "How MarkFlow preserves formatting quality"
        }
      ]
    },
    {
      "name": "Core Features",
      "icon": "layers",
      "articles": [
        {
          "slug": "ocr-pipeline",
          "title": "OCR & Scanned Documents",
          "description": "Automatic text extraction from images and scans"
        },
        {
          "slug": "bulk-conversion",
          "title": "Bulk Repository Conversion",
          "description": "Convert entire document libraries at once"
        },
        {
          "slug": "search",
          "title": "Searching Your Documents",
          "description": "Full-text search across your converted repository"
        },
        {
          "slug": "file-lifecycle",
          "title": "File Lifecycle & Versioning",
          "description": "Change tracking, version history, and trash management"
        }
      ]
    },
    {
      "name": "Advanced",
      "icon": "settings",
      "articles": [
        {
          "slug": "password-recovery",
          "title": "Password-Protected Documents",
          "description": "Handling encrypted and restricted files"
        },
        {
          "slug": "adobe-files",
          "title": "Adobe File Indexing",
          "description": "Metadata and text extraction from creative files"
        },
        {
          "slug": "unrecognized-files",
          "title": "Unrecognized Files",
          "description": "What happens with unsupported file types"
        },
        {
          "slug": "llm-providers",
          "title": "LLM Provider Setup",
          "description": "AI-powered OCR correction and summaries"
        },
        {
          "slug": "gpu-setup",
          "title": "GPU Acceleration Setup",
          "description": "NVIDIA, AMD, and Intel GPU configuration"
        }
      ]
    },
    {
      "name": "Configuration",
      "icon": "sliders",
      "articles": [
        {
          "slug": "settings-guide",
          "title": "Settings Reference",
          "description": "Every setting explained"
        },
        {
          "slug": "status-page",
          "title": "Status & Active Jobs",
          "description": "Monitoring running jobs and system state"
        },
        {
          "slug": "admin-tools",
          "title": "Administration",
          "description": "Admin panel, API keys, and database tools"
        },
        {
          "slug": "resources-monitoring",
          "title": "Resources & Monitoring",
          "description": "System metrics, charts, and activity log"
        }
      ]
    },
    {
      "name": "Integration",
      "icon": "link",
      "articles": [
        {
          "slug": "mcp-integration",
          "title": "AI Assistant Integration",
          "description": "Connect MarkFlow to Claude.ai and Cowork"
        },
        {
          "slug": "troubleshooting",
          "title": "Troubleshooting",
          "description": "Common issues and how to fix them"
        },
        {
          "slug": "keyboard-shortcuts",
          "title": "Keyboard Shortcuts",
          "description": "Quick navigation reference"
        }
      ]
    }
  ]
}
```

---

## 4. Backend: Help Article API

### 4.1 New File: `api/routes/help.py`

```python
"""Help wiki API — serves rendered markdown articles."""

import json
from pathlib import Path
from typing import Optional

import mistune
import structlog
from fastapi import APIRouter, HTTPException

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/help", tags=["help"])

# Help articles live in docs/help/ as .md files
_HELP_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "help"
_INDEX_PATH = _HELP_DIR / "_index.json"

# Cache rendered articles (invalidated on restart — acceptable for built-in docs)
_article_cache: dict[str, dict] = {}
_index_cache: Optional[dict] = None

# Create the mistune renderer with table support
_markdown = mistune.create_markdown(
    plugins=["table", "strikethrough", "footnotes"]
)


def _load_index() -> dict:
    """Load and cache the article index."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    try:
        _index_cache = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        return _index_cache
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("help_index_load_failed", error=str(e))
        return {"categories": []}


def _render_article(slug: str) -> Optional[dict]:
    """Load a markdown file, render to HTML, extract title from first H1."""
    if slug in _article_cache:
        return _article_cache[slug]

    md_path = _HELP_DIR / f"{slug}.md"
    if not md_path.exists():
        return None

    # Security: ensure the resolved path is still inside _HELP_DIR
    resolved = md_path.resolve()
    if not str(resolved).startswith(str(_HELP_DIR.resolve())):
        logger.warning("help_path_traversal_attempt", slug=slug)
        return None

    raw = md_path.read_text(encoding="utf-8")

    # Extract title from first line if it's an H1
    lines = raw.strip().splitlines()
    title = slug.replace("-", " ").title()
    if lines and lines[0].startswith("# "):
        title = lines[0].lstrip("# ").strip()

    html = _markdown(raw)

    result = {
        "slug": slug,
        "title": title,
        "html": html,
        "raw_length": len(raw),
    }
    _article_cache[slug] = result
    return result


@router.get("/index")
async def get_help_index():
    """Return the structured article index with categories."""
    return _load_index()


@router.get("/article/{slug}")
async def get_help_article(slug: str):
    """Return a rendered help article by slug."""
    # Validate slug format: lowercase, hyphens, digits only
    if not all(c.isalnum() or c == "-" for c in slug):
        raise HTTPException(status_code=400, detail="Invalid article slug")

    article = _render_article(slug)
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' not found")
    return article


@router.get("/search")
async def search_help(q: str = ""):
    """Simple keyword search across all help articles."""
    if not q or len(q) < 2:
        return {"results": []}

    q_lower = q.lower()
    results = []
    index = _load_index()

    for category in index.get("categories", []):
        for article_meta in category.get("articles", []):
            slug = article_meta["slug"]
            md_path = _HELP_DIR / f"{slug}.md"
            if not md_path.exists():
                continue

            raw = md_path.read_text(encoding="utf-8").lower()
            if q_lower in raw:
                # Find the first line containing the match for a snippet
                snippet = ""
                for line in raw.splitlines():
                    if q_lower in line and not line.startswith("#"):
                        # Clean up markdown syntax for display
                        snippet = line.strip().lstrip("-*> ")[:200]
                        break

                results.append({
                    "slug": slug,
                    "title": article_meta["title"],
                    "description": article_meta.get("description", ""),
                    "category": category["name"],
                    "snippet": snippet,
                })

    return {"query": q, "results": results}
```

### 4.2 Register Router in `main.py`

In the router registration section of `main.py` (where all the other `app.include_router()` calls are), add:

```python
from api.routes.help import router as help_router
app.include_router(help_router)
```

**Important:** The help routes do NOT require authentication. Help should be accessible even to unauthenticated users (or at minimum, `search_user` role). Do NOT wrap these routes with `require_role()`. If `DEV_BYPASS_AUTH=true`, they work as-is. If auth is enforced, add an explicit bypass in the auth middleware for `/api/help/*` paths, same pattern as `/api/health`.

Add this to the auth bypass list in `core/auth.py` (wherever public paths are listed):

```python
# Paths that don't require authentication
PUBLIC_PATHS = {
    "/api/health",
    "/api/help",        # ← ADD THIS
    # ... existing public paths
}
```

The check should be a prefix match: any path starting with `/api/help` is public.

---

## 5. Frontend: Help Page (`static/help.html`)

New file. This is the main help wiki page with a sidebar table of contents and a content area that loads articles dynamically.

### 5.1 Page Structure

```
┌──────────────────────────────────────────────┐
│  MarkFlow Nav Bar                  [?] Help  │
├───────────┬──────────────────────────────────┤
│           │                                  │
│  Search   │   Article Title                  │
│  [______] │   ─────────────                  │
│           │                                  │
│  Basics   │   Article content rendered       │
│   > Get.. │   from markdown...               │
│   > Doc.. │                                  │
│           │   ## Subheading                   │
│  Core     │                                  │
│   > OCR.. │   More content...                │
│   > Bulk. │                                  │
│   > Sear. │   ### Example                    │
│           │                                  │
│  Advanced │   > Tip: This is a tip block     │
│   > Pass. │                                  │
│   > Adob. │                                  │
│           │                                  │
│  Config   │                                  │
│   > Sett. │                                  │
│   > Stat. │                                  │
│           │                                  │
└───────────┴──────────────────────────────────┘
```

### 5.2 Key UI Behaviors

1. **Sidebar loads from `/api/help/index`** — categories are collapsible, articles are links
2. **Article loads from `/api/help/article/{slug}`** — HTML injected into content area
3. **URL hash tracks article**: `help.html#bulk-conversion` — deep-linkable
4. **Search bar** at top of sidebar: filters article list client-side on title + description, OR calls `/api/help/search?q=` for full-text
5. **Default article**: If no hash, load `getting-started`
6. **Active article highlighted** in sidebar
7. **Mobile responsive**: sidebar collapses to a hamburger/dropdown on narrow screens
8. **Article headings** get auto-generated `id` attributes for in-page anchor linking (the API returns HTML with heading IDs via mistune)

### 5.3 CSS Classes (use existing design system)

Use the existing `markflow.css` design system variables. New classes needed:

```css
/* Help wiki layout — ADD TO markflow.css */
.help-layout {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 0;
    min-height: calc(100vh - var(--nav-height, 60px));
}

.help-sidebar {
    border-right: 1px solid var(--border);
    padding: 1rem;
    overflow-y: auto;
    position: sticky;
    top: var(--nav-height, 60px);
    height: calc(100vh - var(--nav-height, 60px));
    background: var(--bg-secondary, var(--surface));
}

.help-sidebar .search-input {
    width: 100%;
    padding: 0.5rem 0.75rem;
    margin-bottom: 1rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg);
    color: var(--text);
    font-size: 0.875rem;
}

.help-sidebar .category-heading {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 1rem 0 0.5rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

.help-sidebar .category-heading::before {
    content: "▸";
    transition: transform 0.15s;
}

.help-sidebar .category-heading.open::before {
    transform: rotate(90deg);
}

.help-sidebar .article-link {
    display: block;
    padding: 0.35rem 0.75rem;
    margin: 0.1rem 0;
    border-radius: var(--radius);
    color: var(--text);
    text-decoration: none;
    font-size: 0.875rem;
    transition: background 0.15s;
}

.help-sidebar .article-link:hover {
    background: var(--hover);
}

.help-sidebar .article-link.active {
    background: var(--accent-bg, var(--primary-bg));
    color: var(--accent, var(--primary));
    font-weight: 500;
}

.help-content {
    padding: 2rem 3rem;
    max-width: 800px;
    overflow-y: auto;
}

.help-content h1 {
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    color: var(--text);
}

.help-content h2 {
    font-size: 1.35rem;
    font-weight: 600;
    margin-top: 2rem;
    margin-bottom: 0.75rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--border);
    color: var(--text);
}

.help-content h3 {
    font-size: 1.1rem;
    font-weight: 600;
    margin-top: 1.5rem;
    margin-bottom: 0.5rem;
    color: var(--text);
}

.help-content p {
    line-height: 1.7;
    margin-bottom: 1rem;
    color: var(--text);
}

.help-content code {
    background: var(--code-bg, var(--surface));
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    font-size: 0.875em;
    color: var(--code-color, var(--accent));
}

.help-content pre {
    background: var(--code-bg, var(--surface));
    padding: 1rem;
    border-radius: var(--radius);
    overflow-x: auto;
    margin-bottom: 1rem;
    border: 1px solid var(--border);
}

.help-content pre code {
    background: none;
    padding: 0;
    font-size: 0.85rem;
}

.help-content blockquote {
    border-left: 3px solid var(--accent, var(--primary));
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    background: var(--accent-bg, var(--primary-bg));
    border-radius: 0 var(--radius) var(--radius) 0;
}

.help-content blockquote p {
    margin-bottom: 0;
}

.help-content table {
    width: 100%;
    border-collapse: collapse;
    margin: 1rem 0;
}

.help-content th,
.help-content td {
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border);
    text-align: left;
    font-size: 0.9rem;
}

.help-content th {
    background: var(--surface);
    font-weight: 600;
}

.help-content img {
    max-width: 100%;
    border-radius: var(--radius);
    border: 1px solid var(--border);
}

/* Tip / Warning / Note blocks — use blockquote with a class */
.help-content .tip,
.help-content .warning,
.help-content .note {
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    border-radius: var(--radius);
    font-size: 0.9rem;
}

.help-content .tip {
    background: var(--success-bg, #f0fdf4);
    border-left: 3px solid var(--success, #22c55e);
}

.help-content .warning {
    background: var(--warning-bg, #fffbeb);
    border-left: 3px solid var(--warning, #f59e0b);
}

.help-content .note {
    background: var(--info-bg, #eff6ff);
    border-left: 3px solid var(--info, #3b82f6);
}

/* Search results */
.help-search-results {
    list-style: none;
    padding: 0;
    margin: 0.5rem 0;
}

.help-search-results li {
    padding: 0.5rem 0.75rem;
    border-radius: var(--radius);
    cursor: pointer;
}

.help-search-results li:hover {
    background: var(--hover);
}

.help-search-results .snippet {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-top: 0.15rem;
}

/* Responsive: collapse sidebar on mobile */
@media (max-width: 768px) {
    .help-layout {
        grid-template-columns: 1fr;
    }
    .help-sidebar {
        position: static;
        height: auto;
        max-height: 50vh;
        border-right: none;
        border-bottom: 1px solid var(--border);
    }
    .help-content {
        padding: 1.5rem 1rem;
    }
}
```

### 5.4 JavaScript for `help.html`

Key behaviors to implement:

```javascript
// Pseudocode — implement as real JS in the help.html <script> section

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Load the index
    const index = await fetch('/api/help/index').then(r => r.json());
    renderSidebar(index);

    // 2. Determine which article to load
    const slug = window.location.hash?.slice(1) || 'getting-started';
    await loadArticle(slug);

    // 3. Set up search
    const searchInput = document.querySelector('.help-search');
    searchInput.addEventListener('input', debounce(handleSearch, 300));

    // 4. Listen for hash changes (back/forward navigation)
    window.addEventListener('hashchange', () => {
        const newSlug = window.location.hash?.slice(1);
        if (newSlug) loadArticle(newSlug);
    });
});

async function loadArticle(slug) {
    const content = document.querySelector('.help-content');
    content.innerHTML = '<p class="loading">Loading...</p>';
    
    try {
        const article = await fetch(`/api/help/article/${slug}`).then(r => {
            if (!r.ok) throw new Error('Not found');
            return r.json();
        });
        
        content.innerHTML = article.html;
        
        // Post-process: convert blockquote tips/warnings
        // Convention: blockquotes starting with "**Tip:**" get .tip class, etc.
        content.querySelectorAll('blockquote').forEach(bq => {
            const text = bq.textContent.trim();
            if (text.startsWith('Tip:') || text.startsWith('💡')) bq.classList.add('tip');
            else if (text.startsWith('Warning:') || text.startsWith('⚠')) bq.classList.add('warning');
            else if (text.startsWith('Note:') || text.startsWith('ℹ')) bq.classList.add('note');
        });
        
        // Update active state in sidebar
        document.querySelectorAll('.article-link').forEach(a => {
            a.classList.toggle('active', a.dataset.slug === slug);
        });
        
        // Scroll to section if hash has a section anchor (e.g., #bulk-conversion:incremental)
        // Not needed for v1 but nice to have
        
        window.location.hash = slug;
        content.scrollTop = 0;
        
    } catch (err) {
        content.innerHTML = `<h1>Article Not Found</h1><p>The help article "${slug}" doesn't exist yet.</p>`;
    }
}

async function handleSearch(e) {
    const q = e.target.value.trim();
    if (q.length < 2) {
        // Show normal sidebar
        showNormalSidebar();
        return;
    }
    const results = await fetch(`/api/help/search?q=${encodeURIComponent(q)}`).then(r => r.json());
    renderSearchResults(results.results);
}
```

---

## 6. Contextual "?" Help Buttons

### 6.1 Shared Component: `static/js/help-link.js`

A tiny shared script that:
1. Finds all elements with `data-help="<slug>"` (or `data-help="<slug>#<section>"`
2. Injects a small "?" icon link next to them
3. Clicking navigates to `/help#<slug>` (opens in same tab or new tab based on context)

```javascript
/**
 * Help link component — adds contextual "?" icons.
 * 
 * Usage in HTML:
 *   <h2 data-help="bulk-conversion">Bulk Conversion</h2>
 *   <div class="card" data-help="password-recovery#gpu">GPU Acceleration</div>
 *   
 * The script finds these elements and appends a clickable "?" icon.
 */
(function() {
    'use strict';

    function initHelpLinks() {
        document.querySelectorAll('[data-help]').forEach(el => {
            // Don't double-init
            if (el.querySelector('.help-icon')) return;

            const slug = el.getAttribute('data-help');
            
            const link = document.createElement('a');
            link.href = `/help#${slug}`;
            link.className = 'help-icon';
            link.title = 'Help — click to learn more';
            link.setAttribute('aria-label', 'Help');
            link.innerHTML = '?';
            link.addEventListener('click', (e) => {
                // If Ctrl/Cmd held, open in new tab (default browser behavior)
                // Otherwise navigate in current tab
                if (!e.ctrlKey && !e.metaKey) {
                    e.preventDefault();
                    window.location.href = `/help#${slug}`;
                }
            });

            el.style.position = 'relative';
            el.appendChild(link);
        });
    }

    // CSS for the "?" icon — injected once
    const style = document.createElement('style');
    style.textContent = `
        .help-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--text-muted, #888);
            color: var(--bg, #fff);
            font-size: 11px;
            font-weight: 700;
            text-decoration: none;
            margin-left: 0.5rem;
            vertical-align: middle;
            cursor: pointer;
            opacity: 0.5;
            transition: opacity 0.15s, background 0.15s;
            flex-shrink: 0;
        }
        .help-icon:hover {
            opacity: 1;
            background: var(--accent, var(--primary, #3b82f6));
        }
    `;
    document.head.appendChild(style);

    // Initialize on DOMContentLoaded and also export for dynamic content
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initHelpLinks);
    } else {
        initHelpLinks();
    }

    // Expose for pages that render content dynamically
    window.initHelpLinks = initHelpLinks;
})();
```

### 6.2 Load the Script on Every Page

Add to the `<head>` of every `.html` page, or better — add it in `app.js` dynamically (same pattern used for `global-status-bar.js`):

In `app.js`, after the nav is built:

```javascript
// Load help link component
const helpScript = document.createElement('script');
helpScript.src = '/static/js/help-link.js';
document.head.appendChild(helpScript);
```

### 6.3 Where to Place `data-help` Attributes

**These are the specific elements to modify in existing HTML files.** For each page, add `data-help="slug"` to the appropriate heading or container element.

| Page | Element | `data-help` value |
|------|---------|-------------------|
| `index.html` | The main page heading or upload card title | `document-conversion` |
| `index.html` | Direction toggle label (if one exists) | `document-conversion#direction` |
| `index.html` | Fidelity tier selector (if visible) | `fidelity-tiers` |
| `progress.html` | Page heading | `document-conversion#batch-progress` |
| `history.html` | Page heading | `document-conversion#history` |
| `search.html` | Page heading | `search` |
| `bulk.html` | Page heading | `bulk-conversion` |
| `bulk.html` | Locations dropdown section | `bulk-conversion#locations` |
| `bulk-review.html` | Page heading | `ocr-pipeline#bulk-review` |
| `review.html` | Page heading | `ocr-pipeline#review-ui` |
| `settings.html` | "Conversion" section heading | `settings-guide#conversion` |
| `settings.html` | "OCR" section heading | `settings-guide#ocr` |
| `settings.html` | "Bulk Conversion" section heading | `settings-guide#bulk` |
| `settings.html` | "Password Recovery" section heading | `settings-guide#password` |
| `settings.html` | "LLM / AI Enhancement" section heading | `settings-guide#llm` |
| `settings.html` | "Logging" section heading | `settings-guide#logging` |
| `settings.html` | "MCP Server" section heading | `settings-guide#mcp` |
| `settings.html` | "Vision / Enrichment" section heading | `settings-guide#vision` |
| `providers.html` | Page heading | `llm-providers` |
| `locations.html` | Page heading | `bulk-conversion#locations` |
| `unrecognized.html` | Page heading | `unrecognized-files` |
| `trash.html` | Page heading | `file-lifecycle#trash` |
| `db-health.html` | Page heading | `admin-tools#database` |
| `status.html` | Page heading | `status-page` |
| `admin.html` | Page heading | `admin-tools` |
| `admin.html` | "API Keys" section heading | `admin-tools#api-keys` |
| `admin.html` | "Database Tools" section heading | `admin-tools#database` |
| `admin.html` | "Disk Usage" section heading | `admin-tools#disk` |
| `admin.html` | "Resource Controls" section heading | `admin-tools#resources` |
| `resources.html` | Page heading | `resources-monitoring` |
| `debug.html` | Page heading | `troubleshooting#debug` |

---

## 7. Inline Setting Descriptions

### 7.1 Section Descriptions in `settings.html`

Each section on the settings page should have a short description paragraph below its heading. These are static HTML — not dynamically loaded from the API.

Add a `<p class="section-help">` immediately after each section `<h3>` (or whatever heading element the section uses):

```html
<!-- Conversion section -->
<h3 data-help="settings-guide#conversion">Conversion Settings</h3>
<p class="section-help">Controls how documents are converted between formats. These settings affect single-file conversions from the home page and bulk repository jobs.</p>

<!-- OCR section -->
<h3 data-help="settings-guide#ocr">OCR Settings</h3>
<p class="section-help">Configure automatic text extraction from scanned documents and images. The confidence threshold determines when files are flagged for manual review.</p>

<!-- Bulk section -->
<h3 data-help="settings-guide#bulk">Bulk Conversion</h3>
<p class="section-help">Settings for large repository conversion jobs. Worker count controls parallelism — more workers convert faster but use more CPU and memory.</p>

<!-- Password Recovery section -->
<h3 data-help="settings-guide#password">Password Recovery</h3>
<p class="section-help">Configure how MarkFlow handles password-protected and restricted documents. The cracking cascade tries each method in order: empty password, organization passwords, dictionary, brute-force, and GPU-accelerated cracking.</p>

<!-- LLM section -->
<h3 data-help="settings-guide#llm">LLM / AI Enhancement</h3>
<p class="section-help">Enable AI-powered features like OCR error correction, document summarization, and heading inference. Requires an active LLM provider configured on the <a href="/providers">Providers page</a>.</p>

<!-- Vision / Enrichment section -->
<h3 data-help="settings-guide#vision">Vision & Enrichment</h3>
<p class="section-help">Configure visual content analysis for video and image-heavy documents. Uses the active LLM provider's vision capabilities to describe keyframes and scene content.</p>

<!-- Logging section -->
<h3 data-help="settings-guide#logging">Logging</h3>
<p class="section-help">Control logging verbosity. Normal mode logs warnings only. Elevated adds operational info. Developer mode enables full debug traces and frontend event logging.</p>

<!-- MCP section -->
<h3 data-help="settings-guide#mcp">MCP Server</h3>
<p class="section-help">The MCP (Model Context Protocol) server allows AI assistants like Claude to search and read your document repository. <a href="/help#mcp-integration">Learn how to connect →</a></p>

<!-- Lifecycle section (if present) -->
<h3 data-help="settings-guide#lifecycle">File Lifecycle</h3>
<p class="section-help">Configure automatic change detection and file lifecycle management. The scanner periodically checks the source share for new, modified, moved, or deleted files.</p>
```

### 7.2 CSS for Section Help Text

Add to `markflow.css`:

```css
.section-help {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin: -0.25rem 0 1rem;
    line-height: 1.5;
    max-width: 600px;
}

.section-help a {
    color: var(--accent, var(--primary));
    text-decoration: none;
}

.section-help a:hover {
    text-decoration: underline;
}
```

### 7.3 Per-Setting Help Text

The `_PREFERENCE_SCHEMA` in `core/database.py` already has `description` fields on most preference keys. Currently the settings page may or may not render these.

**Ensure** the settings page renders the `description` from each preference as small help text below the input control:

```html
<!-- Pattern for each setting -->
<div class="setting-row">
    <label for="pref-ocr_confidence_threshold">OCR Confidence Threshold</label>
    <input type="range" id="pref-ocr_confidence_threshold" ... />
    <small class="setting-description">Minimum confidence score (0-100) for OCR text. Pages below this threshold are flagged for manual review.</small>
</div>
```

The `description` comes from the `GET /api/preferences` response's schema metadata. The JS that builds the settings form should already have access to this. Add the `<small>` element after each input if a description exists.

CSS:

```css
.setting-description {
    display: block;
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-top: 0.25rem;
    line-height: 1.4;
}
```

---

## 8. Global Nav: "Help" Link

### 8.1 Add to Navigation

In `app.js` (or wherever `buildNav()` constructs the nav links), add a "Help" link. It should appear for ALL roles (no role gating). Position it right-aligned or at the end of the nav list.

```javascript
// In the nav items array, add:
{ label: 'Help', href: '/help', icon: '?', alwaysShow: true }
```

The exact implementation depends on how `buildNav()` currently works, but the key points:

- Label: `Help` (or just a `?` icon on narrow screens)
- Href: `/help`
- No role requirement — visible to everyone
- Position: last item in nav, or right-aligned
- Style: slightly different from other nav items to make it findable — e.g., the `?` in a small circle like the contextual help icons

If the nav uses a standard `<a>` pattern:

```html
<a href="/help" class="nav-link nav-help" title="Help & Documentation">
    <span class="nav-help-icon">?</span>
    <span class="nav-label">Help</span>
</a>
```

CSS for the nav help icon:

```css
.nav-help-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--text-muted);
    color: var(--bg);
    font-size: 12px;
    font-weight: 700;
    margin-right: 0.25rem;
}

.nav-link.nav-help:hover .nav-help-icon {
    background: var(--accent, var(--primary));
}
```

---

## 9. Help Article Content

### 9.1 Writing Guidelines

Each markdown article in `docs/help/` follows this pattern:

```markdown
# Article Title

Brief one-paragraph overview of what this feature does and why you'd use it.

## How It Works

Explanation of the feature mechanics in plain language. Avoid jargon.

## Using [Feature Name]

Step-by-step instructions:

1. Do this
2. Then this
3. Result

## Example

> **Tip:** Walk through a concrete scenario the user can follow.

A real example with specific details.

## Settings

If this feature has configurable settings, list them:

| Setting | What It Does | Default |
|---------|-------------|---------|
| `setting_name` | Description | `value` |

## Common Questions

**Q: Question users might ask?**
A: Clear answer.

## Related

- [Other Article Title](/help#other-slug)
- [Another Related Topic](/help#another-slug)
```

### 9.2 Starter Articles to Write

Create **all 19 articles** listed in section 3.1. Each should be **150-400 lines** of markdown. They must be written for a **non-technical user** — someone who knows how to use a web app but doesn't know Docker, APIs, or Markdown.

Here is the content outline for the most important articles. The rest follow the same pattern.

#### `docs/help/getting-started.md`

```markdown
# Getting Started

MarkFlow converts your documents between their original format (Word, PDF, 
PowerPoint, Excel) and Markdown — a simple, universal text format. It can 
process a single file or an entire repository of hundreds of thousands of 
documents.

## What You Can Do

- **Convert a single file** — upload a Word doc and get Markdown, or upload 
  Markdown and get a Word doc back
- **Convert an entire document library** — point MarkFlow at a network drive 
  and it converts everything, preserving your folder structure
- **Search across everything** — once converted, search the full text of every 
  document instantly
- **Handle scanned documents** — MarkFlow automatically detects and OCRs 
  image-based PDFs
- **Track changes** — when source files change, MarkFlow detects it and keeps 
  version history

## Your First Conversion

1. Click **Convert** in the navigation bar
2. Drag a document onto the upload area (or click to browse)
3. Choose your direction:
   - **To Markdown** — converts your document into Markdown text
   - **From Markdown** — converts a Markdown file back to its original format
4. Click **Convert**
5. Watch the progress bar — when it's done, click **Download** to get your result

> **Tip:** Start with a simple Word document to see how it works. You'll get a 
> `.md` file with all your headings, paragraphs, tables, and images preserved.

## The Navigation Bar

The nav bar at the top of every page takes you to all of MarkFlow's features:

| Link | What It Does |
|------|-------------|
| **Convert** | Upload and convert individual files |
| **Search** | Search across all converted documents |
| **Bulk** | Start or manage large repository conversion jobs |
| **History** | View all past conversions with details |
| **Status** | See running jobs, pause, resume, or stop them |
| **Settings** | Configure MarkFlow's behavior |
| **Help** | You're here! |

Some links (Admin, Resources) only appear if you have the right permissions.

## What's Markdown?

Markdown is a lightweight text format that uses simple symbols for formatting:
- `# Heading` becomes a heading
- `**bold**` becomes **bold** text
- `| cell |` creates tables

It's readable as plain text but renders beautifully. MarkFlow uses Markdown as 
its universal intermediate format because it's searchable, lightweight, and works 
everywhere.

## Next Steps

- [Learn about document conversion](/help#document-conversion)
- [Set up bulk conversion for your document library](/help#bulk-conversion)
- [Configure search](/help#search)
```

#### `docs/help/bulk-conversion.md` (abbreviated outline)

Cover: what bulk conversion is, the concept of "locations" (source + output paths), starting a job, the scan phase, the conversion phase, pause/resume/cancel, incremental rescanning, the status page during a bulk job, worker count setting, skip-and-review for low-confidence OCR, the manifest file, error handling (one bad file doesn't crash the batch), path collision handling.

Include a worked example: "Say your company has a shared drive at `K:\Shared Documents` with 50,000 files. Here's how you'd set up MarkFlow to convert them all..."

#### `docs/help/password-recovery.md` (abbreviated outline)

Cover: two types of protection (restrictions vs encryption), how MarkFlow handles each automatically, the cracking cascade (empty → user-supplied → org list → found-reuse → dictionary → brute-force → john → hashcat GPU), how to supply a known password on the convert page, the organization password list setting, GPU acceleration (NVIDIA auto-detected, AMD/Intel need the host worker), the settings for this feature.

Include a practical example: "You have a batch of 200 Excel files from the accounting department. About 30 of them are password-protected with the department's standard password..."

#### `docs/help/search.md` (abbreviated outline)

Cover: what's indexed (full text of all converted documents, Adobe file metadata), how search works (Meilisearch under the hood — user doesn't need to know the name), autocomplete, filtering by format and source index, what a search result looks like (title, snippet, link to original + markdown), how to access search through the AI assistant (MCP/Cowork).

---

## 10. Files to Create

| File | Purpose |
|------|---------|
| `api/routes/help.py` | Help article API: index, article rendering, search |
| `static/help.html` | Help wiki page: sidebar TOC + article content area |
| `static/js/help-link.js` | Contextual "?" icon component |
| `docs/help/_index.json` | Article index with categories, titles, descriptions |
| `docs/help/getting-started.md` | Getting Started article |
| `docs/help/document-conversion.md` | Document Conversion article |
| `docs/help/fidelity-tiers.md` | Fidelity Tiers Explained article |
| `docs/help/ocr-pipeline.md` | OCR & Scanned Documents article |
| `docs/help/bulk-conversion.md` | Bulk Repository Conversion article |
| `docs/help/search.md` | Searching Your Documents article |
| `docs/help/file-lifecycle.md` | File Lifecycle & Versioning article |
| `docs/help/password-recovery.md` | Password-Protected Documents article |
| `docs/help/adobe-files.md` | Adobe File Indexing article |
| `docs/help/unrecognized-files.md` | Unrecognized Files article |
| `docs/help/settings-guide.md` | Settings Reference article |
| `docs/help/llm-providers.md` | LLM Provider Setup article |
| `docs/help/status-page.md` | Status & Active Jobs article |
| `docs/help/admin-tools.md` | Administration article |
| `docs/help/resources-monitoring.md` | Resources & Monitoring article |
| `docs/help/mcp-integration.md` | AI Assistant Integration article |
| `docs/help/gpu-setup.md` | GPU Acceleration Setup article |
| `docs/help/troubleshooting.md` | Troubleshooting article |
| `docs/help/keyboard-shortcuts.md` | Keyboard Shortcuts article |

---

## 11. Files to Modify

| File | Change |
|------|--------|
| `main.py` | Register `help_router` |
| `core/auth.py` | Add `/api/help` to public (no-auth) path list |
| `static/app.js` | Add "Help" link to nav, load `help-link.js` dynamically |
| `static/markflow.css` | Add help wiki layout, section-help, setting-description, help-icon, nav-help styles |
| `static/index.html` | Add `data-help` attributes to conversion UI elements |
| `static/progress.html` | Add `data-help` to page heading |
| `static/history.html` | Add `data-help` to page heading |
| `static/search.html` | Add `data-help` to page heading |
| `static/bulk.html` | Add `data-help` to page heading + locations section |
| `static/bulk-review.html` | Add `data-help` to page heading |
| `static/review.html` | Add `data-help` to page heading |
| `static/settings.html` | Add `data-help` to each section heading, add `<p class="section-help">` descriptions, render per-setting description text |
| `static/providers.html` | Add `data-help` to page heading |
| `static/locations.html` | Add `data-help` to page heading |
| `static/unrecognized.html` | Add `data-help` to page heading |
| `static/trash.html` | Add `data-help` to page heading |
| `static/db-health.html` | Add `data-help` to page heading |
| `static/status.html` | Add `data-help` to page heading |
| `static/admin.html` | Add `data-help` to page heading + each section heading |
| `static/resources.html` | Add `data-help` to page heading |
| `static/debug.html` | Add `data-help` to page heading |
| `CLAUDE.md` | Add v0.10.0 entry |

---

## 12. Test Requirements

### New Tests: `tests/test_help.py`

| Test | What It Verifies |
|------|-----------------|
| `test_help_index_returns_categories` | `GET /api/help/index` returns categories with articles |
| `test_help_article_renders_html` | `GET /api/help/article/getting-started` returns `html` field with `<h1>` |
| `test_help_article_not_found` | `GET /api/help/article/nonexistent` returns 404 |
| `test_help_article_invalid_slug` | `GET /api/help/article/../../etc/passwd` returns 400 |
| `test_help_article_path_traversal` | Slug with `..` is rejected |
| `test_help_search_finds_results` | `GET /api/help/search?q=conversion` returns matches |
| `test_help_search_empty_query` | `GET /api/help/search?q=` returns empty results |
| `test_help_search_short_query` | `GET /api/help/search?q=a` returns empty (min 2 chars) |
| `test_help_no_auth_required` | Help endpoints work without JWT/auth headers |
| `test_all_index_articles_exist` | Every slug in `_index.json` has a matching `.md` file |
| `test_all_articles_have_title` | Every article renders with a non-empty `title` field |

---

## 13. Writing Style for Articles

**Audience:** A person who uses web apps daily but does NOT know:
- What Docker is
- What an API is
- What Markdown is (until you explain it)
- What Meilisearch, FastAPI, or SQLite are
- What OCR means (until you explain it)

**Tone:** Friendly, direct, practical. Like explaining to a coworker.

**Rules:**
- Avoid technical jargon. When you must use a term (like "OCR"), define it on first use.
- Use concrete examples, not abstract descriptions.
- Each article should be self-contained — a user might land on any article directly.
- Use `> **Tip:**` blockquotes for practical advice.
- Use `> **Warning:**` blockquotes for things that could cause problems.
- Use `> **Note:**` blockquotes for supplementary info.
- Use tables for reference material (settings, keyboard shortcuts, format lists).
- Link to related articles using `/help#slug` format.
- Keep paragraphs short (3-4 sentences max).
- Use numbered lists for step-by-step procedures.
- Use bullet lists for feature descriptions.

---

## 14. CLAUDE.md Updates

### Version Entry

```
**v0.10.0** — In-app help wiki & contextual help system. 19 markdown articles
  in `docs/help/` rendered via mistune at `GET /api/help/article/{slug}`.
  Searchable via `GET /api/help/search?q=`. Article index with categories at
  `GET /api/help/index`. Help page (`/help.html`) with sidebar TOC, client-side
  search, hash-based article navigation. Contextual "?" icons throughout UI via
  `data-help` attributes + `static/js/help-link.js` component. Every page heading
  and settings section heading links to relevant article. Settings sections gain
  `<p class="section-help">` descriptions. Per-setting `description` text rendered
  below controls. Nav bar gains "Help" link (visible to all roles, no auth required).
  Help API endpoints are public (no JWT required). 11 new tests.
```

### New Gotchas

```
- **Help articles are cached in-memory**: `_article_cache` persists for the life
  of the process. Editing a .md file in docs/help/ requires container restart
  to see changes. This is acceptable for built-in docs. If user-editable wiki
  is needed later, add a cache-clear endpoint.

- **mistune rendering must include table plugin**: The same `plugins=["table",
  "strikethrough", "footnotes"]` config used elsewhere. Without it, tables in
  help articles render as plain text.

- **Help routes bypass auth**: `/api/help/*` is in the PUBLIC_PATHS list.
  This is intentional — help should always be accessible. Do not add role
  guards to help endpoints.

- **data-help attributes are passive**: They don't break anything if the target
  article doesn't exist — the user just gets a "not found" page on the wiki.
  No runtime errors from missing articles.

- **help-link.js is idempotent**: Calling `initHelpLinks()` multiple times won't
  create duplicate icons (it checks for existing `.help-icon` children).
  Safe to call after dynamic content loads.

- **Article slugs are validated**: Only lowercase alphanumeric + hyphens. No
  path traversal possible. The resolver also checks that the resolved path is
  within docs/help/.

- **Section anchors in data-help**: The format `data-help="slug#section"` passes
  the full value as the hash. The help page JS should handle `#slug#section`
  by loading the article and scrolling to the section heading. For v0.10.0,
  just loading the article is sufficient — section scrolling is a nice-to-have.
```

---

## 15. Done Criteria Checklist

- [ ] `api/routes/help.py` exists with index, article, and search endpoints
- [ ] Help router registered in `main.py`
- [ ] Help API endpoints are publicly accessible (no auth required)
- [ ] `docs/help/_index.json` exists with all 19 articles categorized
- [ ] All 19 `.md` article files exist in `docs/help/`
- [ ] Each article is 150-400 lines and written for non-technical users
- [ ] `static/help.html` renders with sidebar + content area
- [ ] Sidebar loads categories and articles from index API
- [ ] Clicking an article loads its rendered HTML content
- [ ] URL hash updates when navigating articles (deep-linkable)
- [ ] Default article is `getting-started` when no hash present
- [ ] Client-side search filters sidebar, full-text search calls API
- [ ] `static/js/help-link.js` exists and injects "?" icons
- [ ] `help-link.js` loaded on every page via `app.js`
- [ ] `data-help` attributes added to headings on all existing pages (per table in section 6.3)
- [ ] "?" icons appear next to attributed headings, link to correct articles
- [ ] `settings.html` has `<p class="section-help">` under each section heading
- [ ] `settings.html` renders per-setting `description` text below each control
- [ ] Nav bar includes "Help" link with "?" icon, visible to all roles
- [ ] Help page is responsive (sidebar collapses on mobile)
- [ ] Help content supports dark mode (uses CSS variables)
- [ ] All new CSS classes added to `markflow.css`
- [ ] All 11 tests pass
- [ ] CLAUDE.md updated with v0.10.0 entry + gotchas
