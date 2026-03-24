# MarkFlow <> UnionCore Integration Contract
Version: 1.0 | Status: Draft -- Pending UnionCore Implementation

## Overview

MarkFlow is a document conversion and repository search service. UnionCore integrates with it
via two surfaces:
1. **User-facing search** -- UnionCore renders MarkFlow search results natively in its UI
2. **Service account API** -- UnionCore's backend calls MarkFlow's search and document APIs

MarkFlow does NOT manage users. UnionCore is the identity provider.

---

## Authentication

### For User Requests (JWT)

UnionCore issues a JWT when a user authenticates. That JWT is passed to MarkFlow in requests
that require it.

**Algorithm:** HS256
**Shared secret:** `UNIONCORE_JWT_SECRET` -- set in both systems' environment config.
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

Roles are hierarchical -- a higher role implies all lower role permissions.

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
  &limit=10           optional, default 10, max 25
  &offset=0           optional
  &index=documents    optional: "documents" | "adobe-files" (default: documents)
  &format=pdf,docx    optional: format filter

Authorization: Bearer <jwt>  OR  X-API-Key: mf_<key>
```

**Response:**
```json
{
  "query": "safety manual",
  "index": "documents",
  "total_hits": 42,
  "page": 1,
  "per_page": 10,
  "processing_time_ms": 12,
  "hits": [
    {
      "id": "abc123def456",
      "title": "Safety Manual 2024",
      "source_path": "/mnt/source/safety/manual.pdf",
      "source_format": "pdf",
      "highlight": "...highlighted <em>safety</em> content...",
      "modified_at": "2024-11-01T10:22:00Z"
    }
  ]
}
```

Notes:
- `highlight` contains pre-highlighted HTML using `<em>` tags (safe to render)
- If Meilisearch is down: returns HTTP 503 with `{"error": "search_unavailable"}`

---

### Document Content (for Cowork context loading)

```
GET /api/cowork/search
  ?q=<query>
  &limit=5
  &token_budget=50000   optional -- MarkFlow trims results to fit within token count

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
- Use this endpoint to load context into Cowork's conversation context window

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
User browser -> UnionCore frontend -> UnionCore backend -> MarkFlow /api/search
                                                   (X-API-Key header here)
```

---

## Shared Secret Management

- `UNIONCORE_JWT_SECRET` -- set identically in both systems. Rotate by updating both simultaneously.
- MarkFlow API keys -- generated in MarkFlow's Admin panel, stored in UnionCore's env config.
  Rotate by generating a new key in MarkFlow, updating UnionCore's config, then revoking the old key.

---

## What UnionCore Must Implement

1. JWT issuance with the claims schema above (HS256, shared secret)
2. Role assignment for each user in UnionCore's user database
3. Token forwarding: when a logged-in user triggers a MarkFlow search, forward their JWT
   (or use the service account key from the backend, depending on architecture choice)
4. Native rendering of MarkFlow search results in UnionCore's search UI
5. Optional: Cowork integration -- pass `full_content` from `/api/cowork/search` into
   the Cowork conversation context window

## What MarkFlow Provides

1. JWT validation (HS256)
2. Role-based route enforcement
3. Search results with pre-highlighted snippets
4. Full document markdown content for context loading
5. Health endpoint for monitoring
