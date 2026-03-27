# MarkFlow Phase 10 — Auth Layer & UnionCore Integration Contract
## Claude Code Build Prompt — v1.0

---

## Context

Read `CLAUDE.md` before touching any code. This file is the source of truth.

**Current state:** v0.8.5. All phases 0–9 complete. 543 tests passing. The app has a full
conversion pipeline, OCR, bulk conversion, Meilisearch search, LLM providers, MCP server,
visual enrichment, file lifecycle management, and DB health tooling. It has no authentication.

**This phase adds:** JWT-based auth middleware, role-based route guards, API key service-account
auth for UnionCore's backend, UI restructuring so search is the default landing page with
role-filtered navigation, and a standalone integration contract document for the UnionCore team.

**This phase does NOT add:** login pages, user registration, password management, token issuance,
or user management UI. UnionCore owns all of that. MarkFlow only validates tokens that UnionCore
issues.

---

## Architecture

### Identity Model

UnionCore is the identity provider. It issues JWTs. MarkFlow validates them.

```
User authenticates with UnionCore → UnionCore issues JWT → User calls MarkFlow API
MarkFlow middleware validates JWT signature → reads role claim → allows or rejects
```

For service-to-service calls (UnionCore backend → MarkFlow search/cowork API):
```
UnionCore backend sends X-API-Key header → MarkFlow validates key against DB → grants search_user access
```

### JWT Claims Schema

MarkFlow expects this exact structure from UnionCore-issued tokens:

```json
{
  "sub": "user-uuid-string",
  "email": "user@local46.org",
  "role": "search_user",
  "iat": 1234567890,
  "exp": 1234567890
}
```

Role values (case-sensitive): `search_user` | `operator` | `manager` | `admin`

Roles are hierarchical — a higher role implies all lower role permissions:
`admin` > `manager` > `operator` > `search_user`

### Environment Variables (New)

Add to `docker-compose.yml` and `.env.example`:

```
UNIONCORE_JWT_SECRET=          # Shared secret for HS256 JWT validation (required in prod)
UNIONCORE_ORIGIN=              # Allowed CORS origin for UnionCore UI (e.g. https://app.unioncore.org)
DEV_BYPASS_AUTH=false          # Set to true in local dev — accepts any request as admin
API_KEY_SALT=                  # Random salt for API key hashing (generate once, never rotate)
```

`UNIONCORE_JWT_SECRET` and `API_KEY_SALT` must be set if `DEV_BYPASS_AUTH` is false.
App raises `ValueError` on startup if either is missing in production mode.
Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## Files to Create

### 1. `core/auth.py` — Auth core (NEW)

The single source of truth for all auth logic. No auth logic in route files directly.

```python
"""
core/auth.py — JWT validation and role-based access control.

UnionCore is the identity provider. This module only validates tokens it issues.
Never imports route-level code. No circular imports.
"""
```

Implement:

**`class UserRole(str, Enum)`**
```python
SEARCH_USER = "search_user"
OPERATOR    = "operator"
MANAGER     = "manager"
ADMIN       = "admin"

HIERARCHY = [SEARCH_USER, OPERATOR, MANAGER, ADMIN]

def satisfies(self, required: "UserRole") -> bool:
    """Return True if this role meets or exceeds the required role."""
    return HIERARCHY.index(self) >= HIERARCHY.index(required)
```

**`@dataclass class AuthenticatedUser`**
```python
sub:   str
email: str
role:  UserRole
is_service_account: bool = False   # True when authed via API key, not JWT
```

**`async def verify_token(token: str, secret: str) -> AuthenticatedUser`**
- Decode HS256 JWT using `python-jose` (`pip install python-jose[cryptography]`)
- Raise `HTTPException(401)` on expired, invalid signature, or malformed token
- Raise `HTTPException(403)` if `role` claim is missing or not a valid `UserRole` value
- Return `AuthenticatedUser` on success

**`async def verify_api_key(key: str, db_path: str) -> AuthenticatedUser`**
- Hash the raw key with BLAKE2b + `API_KEY_SALT`
- Look up hash in `api_keys` table (see DB schema below)
- Raise `HTTPException(401)` if not found or revoked
- Return `AuthenticatedUser(sub=row["key_id"], email="service@markflow", role=UserRole.SEARCH_USER, is_service_account=True)`
- Service accounts are always `search_user` — they cannot be elevated

**`async def get_current_user(request: Request) -> AuthenticatedUser`**
FastAPI dependency. Resolution order:
1. If `DEV_BYPASS_AUTH=true` → return `AuthenticatedUser(sub="dev", email="dev@local", role=UserRole.ADMIN, is_service_account=False)` immediately
2. Check `X-API-Key` header → call `verify_api_key()`
3. Check `Authorization: Bearer <token>` header → call `verify_token()`
4. Neither present → raise `HTTPException(401, "Authentication required")`

**`def require_role(minimum: UserRole) -> Callable`**
Returns a FastAPI dependency that calls `get_current_user` and then checks
`user.role.satisfies(minimum)`. Raises `HTTPException(403, "Insufficient role")` if not.

Usage in routes:
```python
@router.get("/api/bulk/jobs")
async def list_bulk_jobs(user: AuthenticatedUser = Depends(require_role(UserRole.MANAGER))):
    ...
```

---

### 2. `api/routes/admin.py` — API Key Management (NEW)

Admin-only route. Provides CRUD for service account API keys used by UnionCore.

```
POST   /api/admin/api-keys         → generate new key, return raw key ONCE (never stored raw)
GET    /api/admin/api-keys         → list keys (id, label, created_at, last_used_at, is_active)
DELETE /api/admin/api-keys/{id}    → revoke key (soft delete, sets is_active=false)
GET    /api/admin/system           → system info: version, env, auth mode, Meilisearch status
```

All routes: `Depends(require_role(UserRole.ADMIN))`

Key generation:
1. Generate `secrets.token_urlsafe(32)` — this is the raw key, returned to caller ONCE
2. Prefix with `mf_` → `mf_<token>` — the full key the caller stores
3. Hash with BLAKE2b + `API_KEY_SALT` → store hash in DB
4. Never store or log the raw key after returning it

Response for key creation:
```json
{
  "key_id": "uuid",
  "label": "unioncore-prod",
  "raw_key": "mf_xxxxxxxxxxxx",
  "warning": "Store this key now. It cannot be retrieved again."
}
```

---

### 3. `static/admin.html` — Admin Panel (NEW)

Vanilla HTML + fetch. Uses `markflow.css` and `app.js`. Admin role only (enforced by API).

Sections:
- **API Keys** — table of active keys with label, created date, last used, revoke button.
  "Generate New Key" button → form for label → shows raw key in a dismissible alert (copy button).
  Alert text: "Copy this key now — it will not be shown again."
- **System Info** — version, auth mode (JWT / DEV_BYPASS), Meilisearch status, DB size
- **Auth Mode Banner** — if `DEV_BYPASS_AUTH=true`, show a persistent warning banner:
  "⚠ Auth bypass is enabled. All requests are treated as Admin. Do not use in production."

---

### 4. `docs/unioncore-integration-contract.md` — Integration Contract (NEW)

Standalone document for the UnionCore team. Written as a spec they implement against.
See full specification in the **Integration Contract** section at the bottom of this prompt.

---

### 5. `tests/test_auth.py` — Auth Tests (NEW)

Cover:
- Valid JWT → correct `AuthenticatedUser` returned
- Expired JWT → 401
- Bad signature → 401
- Missing role claim → 403
- Unknown role value → 403
- API key valid → correct service account user
- API key revoked → 401
- API key missing → falls through to JWT check
- Neither header present → 401
- `DEV_BYPASS_AUTH=true` → returns admin user regardless
- `require_role(MANAGER)` with `search_user` role → 403
- `require_role(MANAGER)` with `manager` role → 200
- `require_role(MANAGER)` with `admin` role → 200 (hierarchy)
- Service account cannot access manager routes → 403

Use `pytest-mock` or monkeypatching for `DEV_BYPASS_AUTH`. Generate test JWTs in fixture
using the same `python-jose` library.

---

## Files to Modify

### 6. `core/database.py` — Add `api_keys` Table

Add to `_ensure_schema()`:

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    key_id      TEXT PRIMARY KEY,      -- UUID
    label       TEXT NOT NULL,          -- human-readable name e.g. "unioncore-prod"
    key_hash    TEXT NOT NULL UNIQUE,   -- BLAKE2b(raw_key + salt)
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    last_used_at TEXT                   -- updated on each successful auth
);
```

Add helpers:
- `async def create_api_key(label: str, key_hash: str) -> str` — inserts, returns key_id
- `async def get_api_key_by_hash(key_hash: str) -> dict | None`
- `async def revoke_api_key(key_id: str) -> bool`
- `async def list_api_keys() -> list[dict]`
- `async def touch_api_key(key_id: str)` — updates `last_used_at = NOW()`

---

### 7. `main.py` — Add Auth Middleware and CORS

**CORS middleware** (add before all routers):
```python
from fastapi.middleware.cors import CORSMiddleware

UNIONCORE_ORIGIN = os.getenv("UNIONCORE_ORIGIN", "")
DEV_BYPASS_AUTH  = os.getenv("DEV_BYPASS_AUTH", "false").lower() == "true"

allowed_origins = ["*"] if DEV_BYPASS_AUTH else (
    [UNIONCORE_ORIGIN] if UNIONCORE_ORIGIN else []
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-ID"],
)
```

**Startup validation:**
```python
if not DEV_BYPASS_AUTH:
    if not os.getenv("UNIONCORE_JWT_SECRET"):
        raise ValueError("UNIONCORE_JWT_SECRET must be set when DEV_BYPASS_AUTH=false")
    if not os.getenv("API_KEY_SALT"):
        raise ValueError("API_KEY_SALT must be set when DEV_BYPASS_AUTH=false")
```

**Register admin router:**
```python
from api.routes.admin import router as admin_router
app.include_router(admin_router)
```

**Note:** Do not add auth to `/api/health`. Health endpoint stays unauthenticated so
UnionCore's load balancer and monitoring can probe it without credentials.

---

### 8. Route Guards — Apply `require_role()` to All Existing Routes

Apply the correct minimum role to every route file. Use the table below.
In each file: `from core.auth import require_role, UserRole, AuthenticatedUser`
Add `Depends(require_role(UserRole.X))` to every endpoint.

| Route File | Minimum Role | Notes |
|---|---|---|
| `api/routes/search.py` | `SEARCH_USER` | Search is the public-facing feature |
| `api/routes/cowork.py` | `SEARCH_USER` | Also accepts X-API-Key (service account path) |
| `api/routes/convert.py` | `OPERATOR` | Single-file conversion |
| `api/routes/batch.py` | `OPERATOR` | Batch status + download |
| `api/routes/history.py` | `OPERATOR` | Job history |
| `api/routes/review.py` | `OPERATOR` | OCR review queue |
| `api/routes/lifecycle.py` | `OPERATOR` | Version history + diff |
| `api/routes/preferences.py` | `OPERATOR` | Read; write requires `MANAGER` for system prefs |
| `api/routes/bulk.py` | `MANAGER` | Bulk job create/control |
| `api/routes/locations.py` | `MANAGER` | Named locations CRUD |
| `api/routes/browse.py` | `MANAGER` | Directory browser |
| `api/routes/scanner.py` | `MANAGER` | Lifecycle scanner control |
| `api/routes/trash.py` | `MANAGER` | Trash management |
| `api/routes/unrecognized.py` | `MANAGER` | Unrecognized file catalog |
| `api/routes/llm_providers.py` | `ADMIN` | LLM provider config |
| `api/routes/mcp_info.py` | `ADMIN` | MCP connection info |
| `api/routes/debug.py` | `ADMIN` | Debug dashboard |
| `api/routes/db_health.py` | `ADMIN` | DB health + maintenance |
| `api/routes/admin.py` | `ADMIN` | API key management |

**Preferences split:** `GET /api/preferences` requires `OPERATOR`. `PUT /api/preferences/{key}`
requires `MANAGER` for system-level keys (worker_count, meilisearch_*, scheduler_*) and
`OPERATOR` for personal preference keys. Implement a `_SYSTEM_PREF_KEYS` set in `preferences.py`
and check role accordingly.

---

### 9. `static/app.js` — Role-Aware Navigation

After any page load, fetch `/api/auth/me` to get the current user's role.
Render nav items conditionally based on role.

Add to `app.js`:

```javascript
const NAV_ITEMS = [
  { href: "/search.html",       label: "Search",       minRole: "search_user" },
  { href: "/index.html",        label: "Convert",      minRole: "operator"    },
  { href: "/history.html",      label: "History",      minRole: "operator"    },
  { href: "/bulk.html",         label: "Bulk Jobs",    minRole: "manager"     },
  { href: "/settings.html",     label: "Settings",     minRole: "manager"     },
  { href: "/trash.html",        label: "Trash",        minRole: "manager"     },
  { href: "/admin.html",        label: "Admin",        minRole: "admin"       },
];

const ROLE_HIERARCHY = ["search_user", "operator", "manager", "admin"];

function roleGte(userRole, minRole) {
  return ROLE_HIERARCHY.indexOf(userRole) >= ROLE_HIERARCHY.indexOf(minRole);
}

async function buildNav(currentPath) {
  let role = "search_user";
  try {
    const res = await fetch("/api/auth/me");
    if (res.ok) role = (await res.json()).role;
  } catch {}

  const nav = document.getElementById("main-nav");
  if (!nav) return;

  NAV_ITEMS
    .filter(item => roleGte(role, item.minRole))
    .forEach(item => {
      const a = document.createElement("a");
      a.href = item.href;
      a.textContent = item.label;
      if (currentPath.includes(item.href.replace(".html", ""))) a.classList.add("active");
      nav.appendChild(a);
    });
}
```

Call `buildNav(window.location.pathname)` on DOMContentLoaded in all pages that use the
shared nav. Replace any hardcoded nav HTML in existing pages with `<nav id="main-nav"></nav>`.

---

### 10. `api/routes/auth.py` — Auth Info Endpoint (NEW, small)

```
GET /api/auth/me  →  { sub, email, role, is_service_account }
```

No role guard on this route — it's how the frontend discovers the current user's role.
If unauthenticated, returns 401. If `DEV_BYPASS_AUTH`, returns the dev admin user.

Register in `main.py`.

---

### 11. `static/search.html` — Promote as Default Landing

Add a redirect shim at `/` → `/search.html` (or configure FastAPI to serve `search.html`
as the root). Do this in `main.py`:

```python
from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    return RedirectResponse(url="/search.html")
```

The search page already exists and works. No visual changes needed beyond the nav update.

---

### 12. `docker-compose.yml` — New Environment Variables

Add to the `markflow` service environment block:

```yaml
- UNIONCORE_JWT_SECRET=${UNIONCORE_JWT_SECRET:-}
- UNIONCORE_ORIGIN=${UNIONCORE_ORIGIN:-}
- DEV_BYPASS_AUTH=${DEV_BYPASS_AUTH:-true}
- API_KEY_SALT=${API_KEY_SALT:-}
```

Default `DEV_BYPASS_AUTH=true` so existing local dev setups continue working without
any config changes. The intent is explicit: local dev bypasses auth by default,
production must set it to false.

Add `.env.example` if it doesn't exist, documenting all env vars including the new ones.

---

## DB Schema Notes

- `api_keys` table is additive. `_ensure_schema()` uses `CREATE TABLE IF NOT EXISTS`
  and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` patterns already established in the codebase.
- No data migration needed. Existing rows in all other tables are unaffected.
- Do NOT add a `users` table. User management is UnionCore's responsibility.

---

## Requirements.txt

Add:
```
python-jose[cryptography]>=3.3.0
```

`python-jose` is the only new dependency. All other auth work uses stdlib (`hashlib`,
`secrets`, `os`) and existing dependencies.

---

## Test Requirements

- All 543 existing tests must continue passing without modification
- New `tests/test_auth.py` must add at minimum 20 tests covering the cases listed above
- Test JWTs generated using `python-jose` with `UNIONCORE_JWT_SECRET=test-secret-do-not-use`
- Tests that call protected routes must pass a valid JWT or set `DEV_BYPASS_AUTH=true`
- Update `conftest.py` to provide an `auth_headers` fixture:
  ```python
  @pytest.fixture
  def auth_headers_admin():
      token = create_test_jwt(role="admin")
      return {"Authorization": f"Bearer {token}"}
  ```
  Provide variants for each role. Existing tests should use `auth_headers_admin` by default
  since most test protected endpoints that now need at least operator access.

---

## Done Criteria

- [ ] `DEV_BYPASS_AUTH=true` → app works exactly as before, no credential prompts anywhere
- [ ] `DEV_BYPASS_AUTH=false` + valid JWT → routes enforce role correctly
- [ ] `DEV_BYPASS_AUTH=false` + expired JWT → 401 with clear error message
- [ ] `DEV_BYPASS_AUTH=false` + no header → 401
- [ ] `DEV_BYPASS_AUTH=false` + wrong role → 403
- [ ] Service account API key grants `search_user` access to `/api/search` and `/api/cowork`
- [ ] Service account API key is rejected on `/api/bulk`, `/api/admin`, etc.
- [ ] Admin can generate API key, key is shown once, key is functional, key can be revoked
- [ ] Revoked key returns 401 immediately
- [ ] `GET /api/auth/me` returns correct user object for all auth paths
- [ ] Nav renders correct items for each role — no items above the user's role are shown
- [ ] `/` redirects to `/search.html`
- [ ] `admin.html` DEV_BYPASS warning banner visible when bypass is active
- [ ] CORS allows `UNIONCORE_ORIGIN` in prod, open in dev bypass mode
- [ ] Startup raises clear `ValueError` if prod mode and required env vars missing
- [ ] `docs/unioncore-integration-contract.md` exists and is complete
- [ ] All 543 existing tests still pass
- [ ] New auth tests pass (20+ tests)
- [ ] CLAUDE.md updated with v0.9.0 status, new files added to Key Files table, new gotchas documented
- [ ] Tagged `v0.9.0`

---

## Gotchas to Watch

- **`python-jose` vs `PyJWT`**: Use `python-jose`. `PyJWT` is already listed as a possibility
  in some docs but `python-jose` has better HS256 + claims validation ergonomics. Do not install both.

- **CORS and SSE**: The existing SSE endpoints (`/api/batch/{id}/stream`, bulk SSE) must
  work through CORS. `EventSource` does not send custom headers — SSE auth must fall back
  to a short-lived token passed as a query param, OR the SSE endpoint is left unauthenticated
  but scoped to only return data for the batch/job ID in the URL (which is a UUID, effectively
  a capability token). Recommended: leave SSE endpoints requiring only `search_user` role with
  a query-param token approach. Do not block on this — document it as a known limitation and
  handle in a follow-up if needed.

- **`/api/health` stays open**: Do not add auth to the health endpoint. It is probed by
  Docker, load balancers, and monitoring without credentials. This is intentional.

- **`/debug` and the MCP server**: The debug dashboard is ADMIN-gated via the web UI.
  The MCP server on port 8001 is a separate process — do not add JWT auth to it in this phase.
  MCP auth is a separate concern (it's used by Claude.ai, not by human users or UnionCore).
  Document this explicitly in CLAUDE.md.

- **`DEV_BYPASS_AUTH` injection order**: Set `DEV_BYPASS_AUTH` before calling `configure_logging()`
  so the startup log can record whether bypass is active.

- **Hash salting**: `API_KEY_SALT` prevents rainbow table attacks on the stored key hashes.
  Use `hashlib.blake2b(raw_key.encode() + salt.encode(), digest_size=32).hexdigest()`.
  The salt is never rotated after initial setup — rotating it invalidates all existing keys.
  Document this in the admin UI and in CLAUDE.md.

- **Role on preferences split**: The `_SYSTEM_PREF_KEYS` check in `preferences.py` must happen
  AFTER the base `OPERATOR` check. The flow is: auth → `OPERATOR` gate → if writing a system
  key, additionally check `MANAGER`. Do not create two separate dependencies — check inline.

---

## Integration Contract Document

Create `docs/unioncore-integration-contract.md` with the following content:

---

```markdown
# MarkFlow ↔ UnionCore Integration Contract
Version: 1.0 | Status: Draft — Pending UnionCore Implementation

## Overview

MarkFlow is a document conversion and repository search service. UnionCore integrates with it
via two surfaces:
1. **User-facing search** — UnionCore renders MarkFlow search results natively in its UI
2. **Service account API** — UnionCore's backend calls MarkFlow's search and document APIs

MarkFlow does NOT manage users. UnionCore is the identity provider.

---

## Authentication

### For User Requests (JWT)

UnionCore issues a JWT when a user authenticates. That JWT is passed to MarkFlow in requests
that require it.

**Algorithm:** HS256
**Shared secret:** `UNIONCORE_JWT_SECRET` — set in both systems' environment config.
**Transmission:** `Authorization: Bearer <token>` header

**Required claims:**
```json
{
  "sub":   "<user-uuid>",
  "email": "<user@domain.org>",
  "role":  "<role-value>",
  "iat":   1234567890,
  "exp":   1234567890
}
```

**Role values (case-sensitive):**
| Value | Access Level |
|---|---|
| `search_user` | Search and read documents only |
| `operator` | Search + single-file conversion + job history |
| `manager` | Operator + bulk jobs + locations + trash + scanner |
| `admin` | Full access including LLM config, debug, and API key management |

Roles are hierarchical — a higher role implies all lower role permissions.

UnionCore sets the role claim based on its own user database. MarkFlow reads it and enforces access.

### For Service Account Requests (API Key)

UnionCore's backend uses a static API key for server-to-server calls.

**Transmission:** `X-API-Key: mf_<key>` header
**Access level:** Service account keys always grant `search_user` role only.
**Key management:** Admin generates keys in MarkFlow's Admin panel at `/admin.html`.
  The raw key is shown exactly once at creation. Store it in UnionCore's environment config.

---

## Endpoints Available to UnionCore

### Search

```
GET /api/search
  ?q=<query>          required
  &limit=10           optional, default 10, max 50
  &offset=0           optional
  &index=documents    optional: "documents" | "adobe-files" | "both" (default: both)
  &type=pdf,docx      optional: comma-separated format filter

Authorization: Bearer <jwt>  OR  X-API-Key: mf_<key>
```

**Response:**
```json
{
  "query": "safety manual",
  "hits": [
    {
      "id": "abc123def456",
      "title": "Safety Manual 2024",
      "source_path": "/mnt/source/safety/manual.pdf",
      "markdown_path": "/mnt/output-repo/safety/manual.md",
      "format": "pdf",
      "snippet": "...highlighted <em>safety</em> content...",
      "score": 0.94,
      "modified_at": "2024-11-01T10:22:00Z",
      "lifecycle_status": "active"
    }
  ],
  "total": 42,
  "limit": 10,
  "offset": 0,
  "index": "both"
}
```

Notes:
- `snippet` contains pre-highlighted HTML using `<em>` tags (safe to render)
- `lifecycle_status` values: `active` | `marked_for_deletion` | `in_trash`
- If Meilisearch is down: returns HTTP 503 with `{"error": "search_unavailable"}`

---

### Document Content (for Cowork context loading)

```
GET /api/cowork/search
  ?q=<query>
  &limit=5
  &token_budget=50000   optional — MarkFlow trims results to fit within token count

Authorization: Bearer <jwt>  OR  X-API-Key: mf_<key>
```

**Response:**
```json
{
  "query": "apprenticeship requirements",
  "results": [
    {
      "id": "abc123def456",
      "title": "Apprenticeship Standards",
      "format": "docx",
      "snippet": "...highlighted text...",
      "full_content": "# Apprenticeship Standards\n\n## Section 1\n...",
      "token_estimate": 4200,
      "source_path": "/mnt/source/standards/apprenticeship.docx"
    }
  ],
  "total_tokens_returned": 18400,
  "budget_applied": true
}
```

Notes:
- `full_content` is the complete markdown of the document, trimmed if needed to fit `token_budget`
- Results are ordered by relevance score; trimming removes lowest-scored results first
- Use this endpoint to load context into Cowork's conversation window

---

### Document Read (single file)

```
GET /api/cowork/document/{id}
  Authorization: Bearer <jwt>  OR  X-API-Key: mf_<key>
```

**Response:**
```json
{
  "id": "abc123def456",
  "title": "Safety Manual 2024",
  "format": "pdf",
  "full_content": "# Safety Manual 2024\n\n## Section 1\n...",
  "token_estimate": 8200,
  "source_path": "/mnt/source/safety/manual.pdf",
  "modified_at": "2024-11-01T10:22:00Z"
}
```

---

### Health Check

```
GET /api/health
  (No authentication required)
```

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-03-24T12:00:00Z",
  "uptime_seconds": 86400,
  "components": {
    "database": "ok",
    "meilisearch": "ok",
    "tesseract": "ok"
  }
}
```

Use this for load balancer health probes. No credentials needed.

---

## Error Responses

| HTTP Status | Meaning |
|---|---|
| 401 | Missing or invalid/expired token or API key |
| 403 | Valid credentials but insufficient role for this endpoint |
| 503 | Meilisearch unavailable (search endpoints only) |

All error responses include:
```json
{ "detail": "Human-readable error message" }
```

---

## CORS

MarkFlow is configured with `UNIONCORE_ORIGIN` set to UnionCore's frontend origin.
Only requests from that origin (or with a valid server-side API key) are accepted in production.

UnionCore should call MarkFlow search from its own backend (server-to-server) to avoid
CORS issues and to keep the API key out of the browser. The UnionCore frontend calls
its own API, which proxies to MarkFlow.

Recommended UnionCore architecture:
```
User browser → UnionCore frontend → UnionCore backend → MarkFlow /api/search
                                                   (X-API-Key header here)
```

---

## Shared Secret Management

- `UNIONCORE_JWT_SECRET` — set identically in both systems. Rotate by updating both simultaneously.
- MarkFlow API keys — generated in MarkFlow's Admin panel, stored in UnionCore's env config.
  Rotate by generating a new key in MarkFlow, updating UnionCore's config, then revoking the old key.

---

## What UnionCore Must Implement

1. JWT issuance with the claims schema above (HS256, shared secret)
2. Role assignment for each user in UnionCore's user database
3. Token forwarding: when a logged-in user triggers a MarkFlow search, forward their JWT
   (or use the service account key from the backend, depending on architecture choice)
4. Native rendering of MarkFlow search results in UnionCore's search UI
5. Optional: Cowork integration — pass `full_content` from `/api/cowork/search` into
   the Cowork conversation context window

## What MarkFlow Provides

1. JWT validation (HS256)
2. Role-based route enforcement
3. Search results with pre-highlighted snippets
4. Full document markdown content for context loading
5. Health endpoint for monitoring
```

---

## After Implementation

When all done criteria are checked:

1. Run the full test suite: `pytest --tb=short`
2. Confirm all 543 original tests pass plus 20+ new auth tests
3. Update `CLAUDE.md`:
   - Add `**v0.9.0**` status line describing the auth layer
   - Add new files to the Key Files table
   - Add new gotchas for `python-jose`, CORS+SSE, API key salt, MCP server auth deferred
   - Update `DEV_BYPASS_AUTH=true` as the default docker-compose state
4. Git tag: `git tag v0.9.0 && git push origin v0.9.0`
