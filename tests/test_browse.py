"""Tests for the directory browser API (GET /api/browse)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.database import init_db


@pytest.fixture(autouse=True)
async def ensure_schema():
    await init_db()


@pytest.fixture
def host_tree(tmp_path):
    """Create a mock /host-like directory tree for testing."""
    host = tmp_path / "host"
    host.mkdir()
    c_drive = host / "c"
    c_drive.mkdir()
    users = c_drive / "Users"
    users.mkdir()
    xerxes = users / "Xerxes"
    xerxes.mkdir()
    work = xerxes / "T86_Work"
    work.mkdir()
    subdir1 = work / "project_a"
    subdir1.mkdir()
    (subdir1 / "file1.txt").write_text("hello")
    (subdir1 / "file2.docx").write_text("doc")
    subdir2 = work / "project_b"
    subdir2.mkdir()
    (work / "readme.md").write_text("# Readme")

    d_drive = host / "d"
    d_drive.mkdir()
    (d_drive / "data").mkdir()

    output_repo = tmp_path / "mnt" / "output-repo"
    output_repo.mkdir(parents=True)
    (output_repo / "converted").mkdir()

    return tmp_path


@pytest.fixture
def patch_roots(host_tree):
    """Patch ALLOWED_BROWSE_ROOTS to use the temp tree."""
    host_path = str(host_tree / "host").replace("\\", "/")
    output_path = str(host_tree / "mnt" / "output-repo").replace("\\", "/")
    new_roots = [host_path, output_path]

    with patch("api.routes.browse.ALLOWED_BROWSE_ROOTS", new_roots):
        yield host_tree


# ── Basic listing tests ──────────────────────────────────────────────────────


class TestBrowseBasic:
    async def test_browse_host_root(self, client, patch_roots):
        host_path = str(patch_roots / "host").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={host_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == host_path
        assert data["is_root"] is True
        names = [e["name"] for e in data["entries"]]
        assert "c" in names
        assert "d" in names

    async def test_browse_drive_directory(self, client, patch_roots):
        c_path = str(patch_roots / "host" / "c").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={c_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == c_path
        assert data["is_root"] is False
        names = [e["name"] for e in data["entries"]]
        assert "Users" in names

    async def test_browse_nested_directory(self, client, patch_roots):
        work_path = str(patch_roots / "host" / "c" / "Users" / "Xerxes" / "T86_Work").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={work_path}")
        assert resp.status_code == 200
        data = resp.json()
        entries = data["entries"]
        # Only directories by default (show_files=false)
        dir_names = [e["name"] for e in entries if e["type"] == "directory"]
        assert "project_a" in dir_names
        assert "project_b" in dir_names
        # No files when show_files is false
        file_names = [e["name"] for e in entries if e["type"] == "file"]
        assert len(file_names) == 0

    async def test_browse_item_count(self, client, patch_roots):
        work_path = str(patch_roots / "host" / "c" / "Users" / "Xerxes" / "T86_Work").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={work_path}")
        data = resp.json()
        project_a = next(e for e in data["entries"] if e["name"] == "project_a")
        assert project_a["item_count"] == 2  # file1.txt, file2.docx


class TestBrowseShowFiles:
    async def test_show_files_true(self, client, patch_roots):
        work_path = str(patch_roots / "host" / "c" / "Users" / "Xerxes" / "T86_Work").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={work_path}&show_files=true")
        assert resp.status_code == 200
        data = resp.json()
        names = [e["name"] for e in data["entries"]]
        assert "readme.md" in names
        assert "project_a" in names

    async def test_show_files_false_excludes_files(self, client, patch_roots):
        work_path = str(patch_roots / "host" / "c" / "Users" / "Xerxes" / "T86_Work").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={work_path}&show_files=false")
        data = resp.json()
        file_entries = [e for e in data["entries"] if e["type"] == "file"]
        assert len(file_entries) == 0

    async def test_dirs_sorted_before_files(self, client, patch_roots):
        work_path = str(patch_roots / "host" / "c" / "Users" / "Xerxes" / "T86_Work").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={work_path}&show_files=true")
        data = resp.json()
        types = [e["type"] for e in data["entries"]]
        # All directories should come before any files
        first_file_idx = next((i for i, t in enumerate(types) if t == "file"), len(types))
        last_dir_idx = max((i for i, t in enumerate(types) if t == "directory"), default=-1)
        assert last_dir_idx < first_file_idx


class TestBrowseNotFound:
    async def test_nonexistent_path(self, client, patch_roots):
        bad_path = str(patch_roots / "host" / "c" / "nonexistent").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={bad_path}")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["error"] == "not_found"


class TestBrowseParentNavigation:
    async def test_parent_from_subdirectory(self, client, patch_roots):
        users_path = str(patch_roots / "host" / "c" / "Users").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={users_path}")
        data = resp.json()
        expected_parent = str(patch_roots / "host" / "c").replace("\\", "/")
        assert data["parent"] == expected_parent

    async def test_parent_null_at_root(self, client, patch_roots):
        host_path = str(patch_roots / "host").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={host_path}")
        data = resp.json()
        assert data["parent"] is None
        assert data["is_root"] is True


class TestBrowseOutputRepo:
    async def test_browse_output_repo(self, client, patch_roots):
        output_path = str(patch_roots / "mnt" / "output-repo").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={output_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_root"] is True
        names = [e["name"] for e in data["entries"]]
        assert "converted" in names

    async def test_browse_output_repo_subfolder(self, client, patch_roots):
        sub_path = str(patch_roots / "mnt" / "output-repo" / "converted").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={sub_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_root"] is False


class TestBrowseDrivesList:
    async def test_drives_in_response(self, client, patch_roots):
        """Drives array is always returned."""
        host_path = str(patch_roots / "host").replace("\\", "/")
        resp = await client.get(f"/api/browse?path={host_path}")
        data = resp.json()
        assert "drives" in data
        assert isinstance(data["drives"], list)

    async def test_mounted_drives_env_var(self, client, patch_roots):
        """MOUNTED_DRIVES env var populates drives list."""
        host_path = str(patch_roots / "host").replace("\\", "/")
        with patch.dict(os.environ, {"MOUNTED_DRIVES": "c,d,e"}):
            resp = await client.get(f"/api/browse?path={host_path}")
        data = resp.json()
        drive_names = [d["name"] for d in data["drives"]]
        assert "C:" in drive_names
        assert "D:" in drive_names
        assert "E:" in drive_names

    async def test_unmounted_drive_shows_false(self, client, patch_roots):
        """A drive letter in MOUNTED_DRIVES but without a directory shows mounted=false."""
        host_path = str(patch_roots / "host").replace("\\", "/")
        with patch.dict(os.environ, {"MOUNTED_DRIVES": "c,d,z"}):
            resp = await client.get(f"/api/browse?path={host_path}")
        data = resp.json()
        z_drive = next((d for d in data["drives"] if d["name"] == "Z:"), None)
        assert z_drive is not None
        assert z_drive["mounted"] is False


class TestBrowsePermissionError:
    async def test_unreadable_directory(self, client, patch_roots):
        """A directory that raises PermissionError returns 403."""
        unreadable = patch_roots / "host" / "c" / "unreadable"
        unreadable.mkdir()

        unreadable_path = str(unreadable).replace("\\", "/")
        with patch("api.routes.browse.os.listdir", side_effect=PermissionError("forbidden")):
            resp = await client.get(f"/api/browse?path={unreadable_path}")
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["error"] == "not_readable"


class TestBrowseNullByte:
    async def test_null_byte_in_path(self, client):
        resp = await client.get("/api/browse?path=/host\x00/c")
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error"] == "invalid_path"
