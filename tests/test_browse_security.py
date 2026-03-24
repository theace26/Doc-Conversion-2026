"""
Security-focused tests for the directory browser API.

These tests verify that path traversal, out-of-bounds access, and injection
attempts are all properly rejected. Non-negotiable.
"""

import os
from unittest.mock import patch

import pytest

from core.database import init_db


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


@pytest.fixture
def host_tree(tmp_path):
    """Create a mock /host-like directory tree for security tests."""
    host = tmp_path / "host"
    host.mkdir()
    c_drive = host / "c"
    c_drive.mkdir()
    (c_drive / "Users").mkdir()
    return tmp_path


@pytest.fixture
def patch_roots(host_tree):
    """Patch ALLOWED_BROWSE_ROOTS to use the temp tree."""
    host_path = str(host_tree / "host").replace("\\", "/")
    output_path = str(host_tree / "mnt" / "output-repo").replace("\\", "/")
    new_roots = [host_path, output_path]
    with patch("api.routes.browse.ALLOWED_BROWSE_ROOTS", new_roots):
        yield host_tree


# ── Path traversal attacks ────────────────────────────────────────────────────


class TestPathTraversal:
    async def test_dot_dot_to_etc_passwd(self, client):
        """/../../../etc/passwd must be rejected."""
        resp = await client.get("/api/browse?path=/../../../etc/passwd")
        assert resp.status_code in (400, 403)

    async def test_dot_dot_from_host(self, client, patch_roots):
        """Traversal from /host/c/../../../../etc must be rejected."""
        base = str(patch_roots / "host" / "c").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={base}/../../../../etc")
        assert resp.status_code in (400, 403)

    async def test_url_encoded_traversal(self, client):
        """%2F..%2F..%2Fetc traversal must be rejected."""
        # FastAPI auto-decodes query params, so this tests the decoded form
        resp = await client.get("/api/browse?path=/host/../../../etc")
        assert resp.status_code in (400, 403)

    async def test_null_byte_injection(self, client):
        """Null byte in path must be rejected."""
        resp = await client.get("/api/browse?path=/host\x00/c")
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error"] == "invalid_path"


# ── Out-of-bounds paths ──────────────────────────────────────────────────────


class TestOutOfBounds:
    async def test_proc_self_environ(self, client):
        """/proc/self/environ must not be browsable."""
        resp = await client.get("/api/browse?path=/proc/self/environ")
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["error"] == "path_not_allowed"

    async def test_app_data_directory(self, client):
        """/app/data (DB directory) must not be browsable."""
        resp = await client.get("/api/browse?path=/app/data")
        assert resp.status_code == 403

    async def test_app_source_directory(self, client):
        """/app (app source) must not be browsable."""
        resp = await client.get("/api/browse?path=/app")
        assert resp.status_code == 403

    async def test_etc_directory(self, client):
        """/etc must not be browsable."""
        resp = await client.get("/api/browse?path=/etc")
        assert resp.status_code == 403

    async def test_root_directory(self, client):
        """/ must not be browsable."""
        resp = await client.get("/api/browse?path=/")
        assert resp.status_code == 403

    async def test_tmp_directory(self, client):
        """/tmp must not be browsable."""
        resp = await client.get("/api/browse?path=/tmp")
        assert resp.status_code == 403


# ── Response content safety ──────────────────────────────────────────────────


class TestResponseSafety:
    async def test_response_never_contains_file_contents(self, client, patch_roots):
        """Browsing a directory with files must not expose file contents."""
        # Create a file with sensitive content
        secret = patch_roots / "host" / "c" / "secret.txt"
        secret.write_text("SUPER_SECRET_API_KEY_12345")

        c_path = str(patch_roots / "host" / "c").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={c_path}&show_files=true")
        assert resp.status_code == 200
        body = resp.text
        assert "SUPER_SECRET_API_KEY_12345" not in body

    async def test_entries_only_contain_metadata(self, client, patch_roots):
        """Each entry should only have name, path, type, readable, item_count."""
        c_path = str(patch_roots / "host" / "c").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={c_path}&show_files=true")
        data = resp.json()
        for entry in data["entries"]:
            # Verify no content or data field
            assert "content" not in entry
            assert "data" not in entry
            assert "text" not in entry
            # Only expected fields
            allowed_keys = {"name", "path", "type", "readable", "item_count"}
            assert set(entry.keys()) == allowed_keys


# ── Symlink escape prevention ────────────────────────────────────────────────


class TestSymlinkEscape:
    async def test_symlink_outside_root_is_skipped(self, client, patch_roots):
        """Symlinks pointing outside allowed roots should be excluded from listings."""
        c_path = patch_roots / "host" / "c"
        # Create a symlink from /host/c/escape → /tmp (outside allowed roots)
        link_path = c_path / "escape"
        try:
            os.symlink("/tmp", str(link_path))
        except (OSError, NotImplementedError):
            pytest.skip("OS does not support symlinks")

        c_str = str(c_path).replace("\\", "/")
        resp = await client.get(f"/api/browse?path={c_str}")
        data = resp.json()
        names = [e["name"] for e in data["entries"]]
        assert "escape" not in names
