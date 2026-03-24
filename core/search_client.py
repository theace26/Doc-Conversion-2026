"""
Thin async Meilisearch HTTP client using httpx.

All methods treat Meilisearch as optional infrastructure — if the host is
unreachable, methods return safe defaults and log a warning. They never raise
connection errors to callers.
"""

import os

import httpx
import structlog

log = structlog.get_logger(__name__)

MEILI_HOST = os.getenv("MEILI_HOST", "http://localhost:7700")
MEILI_MASTER_KEY = os.getenv("MEILI_MASTER_KEY", "")


class MeilisearchClient:
    def __init__(
        self,
        host: str = MEILI_HOST,
        master_key: str = MEILI_MASTER_KEY,
    ):
        self._host = host.rstrip("/")
        self._headers: dict[str, str] = {}
        if master_key:
            self._headers["Authorization"] = f"Bearer {master_key}"

    def _url(self, path: str) -> str:
        return f"{self._host}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | list | None = None,
        timeout: float = 10.0,
    ) -> httpx.Response | None:
        """Make an HTTP request. Returns None on connection error."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method,
                    self._url(path),
                    headers=self._headers,
                    json=json_data,
                )
                return resp
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            log.warning("meilisearch_unavailable", path=path, error=str(exc))
            return None

    async def health_check(self) -> bool:
        """GET /health -> True if 200."""
        resp = await self._request("GET", "/health")
        return resp is not None and resp.status_code == 200

    async def create_index(self, uid: str, primary_key: str) -> None:
        """POST /indexes — idempotent."""
        resp = await self._request("POST", "/indexes", {"uid": uid, "primaryKey": primary_key})
        if resp is not None and resp.status_code not in (200, 201, 202):
            # Index may already exist (409) — that's fine
            if resp.status_code != 409:
                log.warning("meilisearch_create_index_fail", uid=uid, status=resp.status_code)

    async def update_index_settings(self, uid: str, settings: dict) -> None:
        """PATCH /indexes/{uid}/settings."""
        resp = await self._request("PATCH", f"/indexes/{uid}/settings", settings)
        if resp is not None and resp.status_code not in (200, 202):
            log.warning("meilisearch_settings_fail", uid=uid, status=resp.status_code)

    async def add_documents(self, uid: str, documents: list[dict]) -> str | None:
        """POST /indexes/{uid}/documents — returns task_uid or None."""
        resp = await self._request("POST", f"/indexes/{uid}/documents", documents)
        if resp is None:
            return None
        if resp.status_code in (200, 202):
            data = resp.json()
            return str(data.get("taskUid", ""))
        log.warning("meilisearch_add_docs_fail", uid=uid, status=resp.status_code)
        return None

    async def delete_document(self, uid: str, doc_id: str) -> None:
        """DELETE /indexes/{uid}/documents/{doc_id}."""
        await self._request("DELETE", f"/indexes/{uid}/documents/{doc_id}")

    async def search(
        self,
        uid: str,
        query: str,
        options: dict | None = None,
    ) -> dict:
        """POST /indexes/{uid}/search — returns raw Meilisearch response."""
        body: dict = {"q": query}
        if options:
            body.update(options)
        resp = await self._request("POST", f"/indexes/{uid}/search", body)
        if resp is None:
            return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 0}
        if resp.status_code == 200:
            return resp.json()
        log.warning("meilisearch_search_fail", uid=uid, status=resp.status_code)
        return {"hits": [], "estimatedTotalHits": 0, "processingTimeMs": 0}

    async def get_index_stats(self, uid: str) -> dict:
        """GET /indexes/{uid}/stats."""
        resp = await self._request("GET", f"/indexes/{uid}/stats")
        if resp is None:
            return {}
        if resp.status_code == 200:
            return resp.json()
        return {}

    async def wait_for_task(self, task_uid: str, timeout_ms: int = 5000) -> bool:
        """Poll GET /tasks/{task_uid} until succeeded/failed."""
        import asyncio
        elapsed = 0
        interval = 200
        while elapsed < timeout_ms:
            resp = await self._request("GET", f"/tasks/{task_uid}")
            if resp and resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "")
                if status == "succeeded":
                    return True
                if status in ("failed", "canceled"):
                    return False
            await asyncio.sleep(interval / 1000)
            elapsed += interval
        return False


# Module-level singleton
_client: MeilisearchClient | None = None


def get_meili_client() -> MeilisearchClient:
    global _client
    if _client is None:
        _client = MeilisearchClient()
    return _client
