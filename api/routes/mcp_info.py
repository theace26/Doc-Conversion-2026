"""
MCP connection info endpoint for the settings UI.

GET /api/mcp/connection-info — Returns MCP server URL and status.
"""

import os

import httpx
import structlog
from fastapi import APIRouter, Depends

from core.auth import AuthenticatedUser, UserRole, require_role

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/connection-info")
async def mcp_connection_info(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Return MCP server connection details for the settings UI."""
    mcp_port = int(os.getenv("MCP_PORT", "8001"))
    auth_token = os.getenv("MCP_AUTH_TOKEN", "")

    # Always use localhost — Docker internal IPs are unreachable from the host
    base_url = f"http://localhost:{mcp_port}/sse"
    if auth_token:
        base_url += f"?token={auth_token}"

    # Check if MCP server is running (use Docker service name inside containers)
    mcp_host = os.getenv("MCP_HOST", "markflow-mcp")
    mcp_running = False
    tool_count = 7  # We know our tool count statically
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://{mcp_host}:{mcp_port}/health")
            mcp_running = resp.status_code == 200
    except Exception:
        # MCP server might not have a /health endpoint; try SSE endpoint
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://{mcp_host}:{mcp_port}/sse")
                mcp_running = resp.status_code in (200, 405)
        except Exception:
            pass

    return {
        "mcp_url": base_url,
        "mcp_running": mcp_running,
        "tool_count": tool_count,
        "auth_required": bool(auth_token),
    }
