"""Per-user UX dispatch helpers.

Reads the ``mf_use_new_ux`` cookie set by the frontend preferences module and
uses it to choose between the new-UX and original-UX HTML files for each page
route.  Falls back to the system-wide ``ENABLE_NEW_UX`` env flag when no
cookie is present so un-authenticated / first-visit requests work as before.

Usage in main.py::

    from core.ux_dispatch import serve_ux_page

    @app.get("/", include_in_schema=False)
    async def root_index(request: Request):
        return serve_ux_page(request, "static/index-new.html", "static/index.html")
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import FileResponse

from core.feature_flags import is_new_ux_enabled


def is_new_ux_for_request(request: Request) -> bool:
    """Per-user UX preference.

    Priority:
      1. ``mf_use_new_ux`` cookie (set by ``static/js/preferences.js``)
         * ``"1"`` → new UX
         * ``"0"`` → original UX
      2. System-wide ``ENABLE_NEW_UX`` env flag (existing behaviour).

    This makes every page route respect the per-user toggle without any async
    DB lookup — the cookie is the already-resolved pref that the browser carries
    on every request.
    """
    cookie = request.cookies.get("mf_use_new_ux")
    if cookie == "1":
        return True
    if cookie == "0":
        return False
    return is_new_ux_enabled()


def serve_ux_page(request: Request, new_path: str, orig_path: str) -> FileResponse:
    """Dispatch between a new-UX file and the original-UX file.

    Args:
        request:   The incoming FastAPI request (used to read the UX cookie).
        new_path:  Relative path to the new-UX HTML file
                   (e.g. ``"static/index-new.html"``).
        orig_path: Relative path to the original-UX HTML file
                   (e.g. ``"static/index.html"``).

    Returns:
        A ``FileResponse`` for whichever file the user's pref selects.
    """
    if is_new_ux_for_request(request):
        return FileResponse(new_path)
    return FileResponse(orig_path)
