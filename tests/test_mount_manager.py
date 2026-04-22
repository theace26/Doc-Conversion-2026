"""Tests for mount_manager — config models and command generation."""

import json

import pytest
from core.mount_manager import (
    MountConfig,
    SMBCredentials,
    KerberosConfig,
    MountManager,
)


class TestFstabGeneration:
    """Test fstab entry generation for each protocol."""

    def test_smb_fstab_entry(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert entry.startswith("//192.168.1.17/storage_folder")
        assert "/mnt/source-share" in entry
        assert "cifs" in entry
        assert "ro" in entry
        assert "credentials=/etc/markflow-smb-credentials" in entry
        assert "_netdev" in entry
        assert "x-systemd.automount" in entry

    def test_smb_rw_fstab_entry(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="markflow",
            mount_point="/mnt/markflow-output",
            read_only=False,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "rw" in entry
        assert "ro" not in entry.split("rw")[0]  # no stray 'ro' before 'rw'

    def test_nfsv3_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert entry.startswith("192.168.1.17:/volume1/storage")
        assert "/mnt/source-share" in entry
        assert "nfs" in entry
        assert "nfs4" not in entry
        assert "ro" in entry
        assert "hard" in entry
        assert "intr" in entry
        assert "_netdev" in entry

    def test_nfsv4_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "nfs4" in entry
        assert "sec=krb5" not in entry

    def test_nfsv4_kerberos_fstab_entry(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        entry = mgr.generate_fstab_entry(cfg)

        assert "nfs4" in entry
        assert "sec=krb5" in entry


class TestMountCommandGeneration:
    """Test mount command generation for each protocol."""

    def test_smb_mount_command(self):
        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="test"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t cifs" in cmd
        assert "//192.168.1.17/storage_folder" in cmd
        assert "/mnt/source-share" in cmd

    def test_nfsv3_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t nfs " in cmd
        assert "192.168.1.17:/volume1/storage" in cmd

    def test_nfsv4_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "mount -t nfs4" in cmd

    def test_nfsv4_kerberos_mount_command(self):
        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr = MountManager(config_path="/tmp/test-mounts.json")
        cmd = mgr.generate_mount_command(cfg)

        assert "sec=krb5" in cmd


class TestConfigValidation:
    """Test MountConfig validation."""

    def test_smb_requires_credentials(self):
        with pytest.raises(ValueError, match="SMB.*credentials"):
            MountConfig(
                protocol="smb",
                server="192.168.1.17",
                share_path="share",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()

    def test_nfs_rejects_credentials(self):
        cfg = MountConfig(
            protocol="nfsv3",
            server="192.168.1.17",
            share_path="/export",
            mount_point="/mnt/test",
            read_only=True,
        )
        cfg.validate()  # should not raise

    def test_empty_server_rejected(self):
        with pytest.raises(ValueError, match="[Ss]erver"):
            MountConfig(
                protocol="nfsv3",
                server="",
                share_path="/export",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()

    def test_empty_share_rejected(self):
        with pytest.raises(ValueError, match="[Ss]hare"):
            MountConfig(
                protocol="nfsv3",
                server="192.168.1.17",
                share_path="",
                mount_point="/mnt/test",
                read_only=True,
            ).validate()


class TestConfigPersistence:
    """Test save/load of mount configs to JSON."""

    def test_save_and_load_smb(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        cfg = MountConfig(
            protocol="smb",
            server="192.168.1.17",
            share_path="storage_folder",
            mount_point="/mnt/source-share",
            read_only=True,
            smb_credentials=SMBCredentials(username="markflow", password="secret"),
        )
        mgr.save_config("source", cfg)

        loaded = mgr.load_config()
        assert "source" in loaded
        assert loaded["source"].protocol == "smb"
        assert loaded["source"].server == "192.168.1.17"
        assert loaded["source"].share_path == "storage_folder"
        assert loaded["source"].read_only is True

        # Password should NOT be in the JSON file
        raw = json.loads(config_file.read_text())
        assert "password" not in json.dumps(raw)
        # v2 schema: config lives under shares["source"]
        assert "smb_username" in raw["shares"]["source"]

    def test_save_and_load_nfsv4_kerberos(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        cfg = MountConfig(
            protocol="nfsv4",
            server="192.168.1.17",
            share_path="/volume1/storage",
            mount_point="/mnt/source-share",
            read_only=True,
            kerberos=KerberosConfig(realm="EXAMPLE.COM", keytab_path="/etc/krb5.keytab"),
        )
        mgr.save_config("source", cfg)

        loaded = mgr.load_config()
        assert loaded["source"].protocol == "nfsv4"
        assert loaded["source"].kerberos is not None
        assert loaded["source"].kerberos.realm == "EXAMPLE.COM"

    def test_save_both_roles(self, tmp_path):
        config_file = tmp_path / "mounts.json"
        mgr = MountManager(config_path=str(config_file))

        source = MountConfig(
            protocol="nfsv3", server="10.0.0.1", share_path="/data",
            mount_point="/mnt/source-share", read_only=True,
        )
        output = MountConfig(
            protocol="smb", server="10.0.0.2", share_path="output",
            mount_point="/mnt/markflow-output", read_only=False,
            smb_credentials=SMBCredentials(username="user", password="pass"),
        )
        mgr.save_config("source", source)
        mgr.save_config("output", output)

        loaded = mgr.load_config()
        assert loaded["source"].protocol == "nfsv3"
        assert loaded["output"].protocol == "smb"

    def test_load_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.json"
        mgr = MountManager(config_path=str(config_file))
        loaded = mgr.load_config()
        assert loaded == {}


# -- Universal Storage Manager: multi-mount support --


def test_share_mount_point_sanitizes() -> None:
    from core.mount_manager import MountManager
    assert MountManager.share_mount_point("nas-docs") == "/mnt/shares/nas-docs"
    assert MountManager.share_mount_point("a b") == "/mnt/shares/ab"
    assert MountManager.share_mount_point("archive_01") == "/mnt/shares/archive_01"
    # strips leading/trailing separators
    assert MountManager.share_mount_point("--foo--") == "/mnt/shares/foo"
    with pytest.raises(ValueError):
        MountManager.share_mount_point("///")
    with pytest.raises(ValueError):
        MountManager.share_mount_point("")
    with pytest.raises(ValueError):
        MountManager.share_mount_point("   ")


def test_migrate_v1_to_v2() -> None:
    from core.mount_manager import _migrate_mounts_json
    v1 = {"source": {"protocol": "smb", "server": "x"}}
    v2 = _migrate_mounts_json(v1)
    assert v2["_schema_version"] == 2
    assert "source" in v2["shares"]
    assert v2["shares"]["source"] == {"protocol": "smb", "server": "x"}
    # idempotent
    assert _migrate_mounts_json(v2) == v2


def test_migrate_v1_handles_multiple_roles() -> None:
    from core.mount_manager import _migrate_mounts_json
    v1 = {
        "source": {"protocol": "nfsv3", "server": "a"},
        "output": {"protocol": "smb", "server": "b"},
    }
    v2 = _migrate_mounts_json(v1)
    assert set(v2["shares"].keys()) == {"source", "output"}


def test_migrate_v1_skips_empty_and_private_keys() -> None:
    from core.mount_manager import _migrate_mounts_json
    v1 = {
        "source": {"protocol": "nfsv3", "server": "a"},
        "output": {},  # empty dict should be dropped
        "_meta": {"ignored": True},  # underscore-prefixed is reserved
    }
    v2 = _migrate_mounts_json(v1)
    assert "source" in v2["shares"]
    assert "output" not in v2["shares"]
    assert "_meta" not in v2["shares"]


def test_migrate_non_dict_input() -> None:
    from core.mount_manager import _migrate_mounts_json
    # Defensive: if the JSON file was corrupted into a list, don't crash.
    assert _migrate_mounts_json([]) == {"_schema_version": 2, "shares": {}}


def test_load_auto_migrates_v1_on_disk(tmp_path) -> None:
    """A pre-existing v1 mounts.json loads through load_config() unchanged in shape."""
    config_file = tmp_path / "mounts.json"
    # Write a v1-format file directly
    v1_raw = {
        "source": {
            "protocol": "nfsv3",
            "server": "192.168.1.17",
            "share_path": "/volume1/storage",
            "mount_point": "/mnt/source-share",
            "read_only": True,
        }
    }
    config_file.write_text(json.dumps(v1_raw))

    mgr = MountManager(config_path=str(config_file))
    loaded = mgr.load_config()
    assert "source" in loaded
    assert loaded["source"].protocol == "nfsv3"
    assert loaded["source"].mount_point == "/mnt/source-share"


def test_save_writes_v2_schema(tmp_path) -> None:
    """save_config() writes the v2 schema, not the flat v1 layout."""
    config_file = tmp_path / "mounts.json"
    mgr = MountManager(config_path=str(config_file))

    cfg = MountConfig(
        protocol="nfsv3",
        server="10.0.0.1",
        share_path="/data",
        mount_point="/mnt/source-share",
        read_only=True,
    )
    mgr.save_config("source", cfg)

    raw = json.loads(config_file.read_text())
    assert raw["_schema_version"] == 2
    assert "shares" in raw
    assert "source" in raw["shares"]
    assert raw["shares"]["source"]["protocol"] == "nfsv3"


def test_save_then_load_preserves_named_share(tmp_path) -> None:
    """A named share (not just 'source'/'output') round-trips through save/load."""
    config_file = tmp_path / "mounts.json"
    mgr = MountManager(config_path=str(config_file))

    cfg = MountConfig(
        protocol="nfsv4",
        server="10.0.0.5",
        share_path="/export/archive",
        mount_point="/mnt/shares/archive",
        read_only=True,
        display_name="archive",
    )
    mgr.save_config("archive", cfg)

    loaded = mgr.load_config()
    assert "archive" in loaded
    assert loaded["archive"].protocol == "nfsv4"
    assert loaded["archive"].display_name == "archive"


def test_migrated_file_preserved_until_next_save(tmp_path) -> None:
    """Reading a v1 file must NOT rewrite the file (only save_config() writes)."""
    config_file = tmp_path / "mounts.json"
    v1_raw = {
        "source": {
            "protocol": "nfsv3",
            "server": "192.168.1.17",
            "share_path": "/volume1/storage",
            "mount_point": "/mnt/source-share",
            "read_only": True,
        }
    }
    original = json.dumps(v1_raw)
    config_file.write_text(original)

    mgr = MountManager(config_path=str(config_file))
    mgr.load_config()
    # File on disk unchanged after read-only load
    assert config_file.read_text() == original


def test_mount_named_sets_mount_point_and_display_name() -> None:
    """mount_named() with dry_run=True confirms mount_point override + display_name."""
    mgr = MountManager(config_path="/tmp/test-mount-named.json")
    cfg = MountConfig(
        protocol="nfsv3",
        server="10.0.0.5",
        share_path="/export/archive",
        # Intentionally wrong — mount_named should override this:
        mount_point="/mnt/wrong-path",
        read_only=True,
    )
    result = mgr.mount_named("archive", cfg, dry_run=True)
    assert result.success is True
    assert "/mnt/shares/archive" in result.command
    assert cfg.mount_point == "/mnt/shares/archive"
    assert cfg.display_name == "archive"


def test_mount_named_rejects_invalid_name() -> None:
    mgr = MountManager(config_path="/tmp/test-mount-named.json")
    cfg = MountConfig(
        protocol="nfsv3", server="10.0.0.5", share_path="/x",
        mount_point="/mnt/placeholder", read_only=True,
    )
    with pytest.raises(ValueError):
        mgr.mount_named("///", cfg, dry_run=True)


def test_extended_mountconfig_preserves_display_name_roundtrip() -> None:
    """display_name field roundtrips through to_dict / from_dict."""
    cfg = MountConfig(
        protocol="smb",
        server="10.0.0.2",
        share_path="shared",
        mount_point="/mnt/shares/shared",
        read_only=False,
        smb_credentials=SMBCredentials(username="u", password="p"),
        display_name="Shared Drive",
    )
    d = cfg.to_dict()
    assert d["display_name"] == "Shared Drive"
    cfg2 = MountConfig.from_dict(d)
    assert cfg2.display_name == "Shared Drive"


def test_mountconfig_from_dict_without_display_name_is_none() -> None:
    """Legacy dicts without display_name deserialize with display_name=None (no crash)."""
    d = {
        "protocol": "nfsv3",
        "server": "10.0.0.1",
        "share_path": "/data",
        "mount_point": "/mnt/source-share",
        "read_only": True,
    }
    cfg = MountConfig.from_dict(d)
    assert cfg.display_name is None


# -- Universal Storage Manager: SMB / NFS network discovery --


def test_parse_smbclient_shares_drops_ipc_and_admin() -> None:
    from core.mount_manager import _parse_smbclient_shares
    sample = """
        Sharename       Type      Comment
        ---------       ----      -------
        Documents       Disk      Shared docs
        Backups         Disk
        print$          Disk      Printer Drivers
        IPC$            IPC       IPC Service
        ADMIN$          Disk      Remote Admin
    """
    shares = _parse_smbclient_shares(sample)
    names = [s["name"] for s in shares]
    assert "Documents" in names
    assert "Backups" in names
    # IPC / ADMIN / print$ administrative shares are filtered out
    assert "IPC$" not in names
    assert "ADMIN$" not in names
    assert "print$" not in names


def test_parse_smbclient_shares_captures_comment() -> None:
    from core.mount_manager import _parse_smbclient_shares
    sample = """
        Sharename       Type      Comment
        ---------       ----      -------
        Photos          Disk      Family photos archive
    """
    shares = _parse_smbclient_shares(sample)
    assert shares == [{"name": "Photos", "type": "Disk", "comment": "Family photos archive"}]


def test_parse_smbclient_shares_handles_empty_output() -> None:
    from core.mount_manager import _parse_smbclient_shares
    assert _parse_smbclient_shares("") == []


def test_parse_showmount_output_parses_exports() -> None:
    from core.mount_manager import _parse_showmount_output
    sample = """Export list for 10.0.0.5:
/exports/data    10.0.0.0/24
/exports/media   *
"""
    exports = _parse_showmount_output(sample)
    assert {"path": "/exports/data", "allowed_hosts": "10.0.0.0/24"} in exports
    assert {"path": "/exports/media", "allowed_hosts": "*"} in exports


def test_parse_showmount_output_path_only() -> None:
    from core.mount_manager import _parse_showmount_output
    # A line with no host column should still parse (allowed_hosts = "")
    exports = _parse_showmount_output("Export list for x:\n/exports/lonely\n")
    assert exports == [{"path": "/exports/lonely", "allowed_hosts": ""}]


def test_discover_smb_servers_invalid_subnet_returns_empty() -> None:
    import asyncio
    from core import mount_manager as mm
    result = asyncio.run(mm.discover_smb_servers("not-a-cidr"))
    assert result == []


def test_discover_smb_servers_caps_subnet_size(monkeypatch) -> None:
    """A /16 has 65k hosts — discover_smb_servers must cap at 256 to avoid hammering."""
    import asyncio
    from core import mount_manager as mm
    captured: list[str] = []

    async def fake_probe(ip: str, timeout: float = 1.5):
        captured.append(ip)
        return None

    monkeypatch.setattr(mm, "_probe_smb_host", fake_probe)
    asyncio.run(mm.discover_smb_servers("10.0.0.0/16", timeout=5))
    assert len(captured) == 256


def test_discover_smb_servers_filters_unreachable(monkeypatch) -> None:
    import asyncio
    from core import mount_manager as mm

    async def fake_probe(ip: str, timeout: float = 1.5):
        # Only .1 answers
        if ip.endswith(".1"):
            return {"ip": ip, "hostname": "nas"}
        return None

    monkeypatch.setattr(mm, "_probe_smb_host", fake_probe)
    result = asyncio.run(mm.discover_smb_servers("10.0.0.0/30", timeout=5))
    assert all(r["hostname"] == "nas" for r in result)
    assert all(isinstance(r, dict) for r in result)


def test_discover_smb_shares_handles_missing_smbclient(monkeypatch) -> None:
    """If smbclient binary is missing, return [] without raising."""
    import asyncio
    import subprocess as sp
    from core import mount_manager as mm

    def boom(*a, **kw):
        raise FileNotFoundError("smbclient")

    monkeypatch.setattr(sp, "run", boom)
    result = asyncio.run(mm.discover_smb_shares("10.0.0.5"))
    assert result == []


def test_discover_nfs_exports_handles_timeout(monkeypatch) -> None:
    """showmount timeout returns [] without raising."""
    import asyncio
    import subprocess as sp
    from core import mount_manager as mm

    def boom(*a, **kw):
        raise sp.TimeoutExpired(cmd="showmount", timeout=5)

    monkeypatch.setattr(sp, "run", boom)
    result = asyncio.run(mm.discover_nfs_exports("10.0.0.5"))
    assert result == []


# -- Universal Storage Manager: singleton + remount + health monitoring --


def test_get_mount_manager_returns_singleton() -> None:
    from core.mount_manager import get_mount_manager
    a = get_mount_manager()
    b = get_mount_manager()
    assert a is b


def test_mount_health_dict_is_module_level() -> None:
    from core.mount_manager import mount_health
    assert isinstance(mount_health, dict)


def test_remount_all_saved_returns_empty_when_no_config(tmp_path) -> None:
    """No mounts.json → remount_all_saved returns empty dict, never raises."""
    import asyncio
    from core.mount_manager import remount_all_saved, MountManager
    mgr = MountManager(config_path=str(tmp_path / "nonexistent.json"))
    result = asyncio.run(remount_all_saved(mgr, credential_store=None))
    assert result == {}


def test_remount_all_saved_handles_mount_failure(tmp_path, monkeypatch) -> None:
    """A failing mount call is logged and produces {name: False}, no exception."""
    import asyncio
    from core.mount_manager import (
        remount_all_saved, MountManager, MountConfig, MountResult,
    )
    mgr = MountManager(config_path=str(tmp_path / "mounts.json"))
    cfg = MountConfig(
        protocol="nfsv3", server="10.0.0.1", share_path="/data",
        mount_point="/mnt/shares/data", read_only=True,
    )
    mgr.save_config("data", cfg)

    def fake_mount(self, config, dry_run=False):
        return MountResult(success=False, message="mock failure", command="", fstab_entry="")

    monkeypatch.setattr(MountManager, "mount", fake_mount)
    result = asyncio.run(remount_all_saved(mgr, credential_store=None))
    assert result == {"data": False}


def test_check_mount_health_populates_dict(tmp_path, monkeypatch) -> None:
    """check_mount_health probes share + writes to module-level mount_health."""
    import asyncio
    from core.mount_manager import (
        check_mount_health, mount_health, MountManager, MountConfig,
    )
    mount_health.clear()
    mgr = MountManager(config_path=str(tmp_path / "mounts.json"))
    cfg = MountConfig(
        protocol="nfsv3", server="10.0.0.1", share_path="/data",
        mount_point=str(tmp_path),  # use tmp_path so listdir succeeds
        read_only=True,
    )
    mgr.save_config("source", cfg)
    asyncio.run(check_mount_health(mgr))
    assert "source" in mount_health
    assert mount_health["source"]["ok"] is True
    assert mount_health["source"]["error"] is None


def test_check_mount_health_records_failure_for_missing_path(tmp_path) -> None:
    import asyncio
    from core.mount_manager import (
        check_mount_health, mount_health, MountManager, MountConfig,
    )
    mount_health.clear()
    mgr = MountManager(config_path=str(tmp_path / "mounts.json"))
    cfg = MountConfig(
        protocol="nfsv3", server="10.0.0.1", share_path="/data",
        mount_point=str(tmp_path / "absent"),
        read_only=True,
    )
    mgr.save_config("source", cfg)
    asyncio.run(check_mount_health(mgr))
    assert mount_health["source"]["ok"] is False
    assert mount_health["source"]["error"]


def test_check_mount_health_prunes_stale_entries(tmp_path) -> None:
    """Removing a share from config drops its entry from mount_health on next probe."""
    import asyncio
    from core.mount_manager import (
        check_mount_health, mount_health, MountManager,
    )
    mount_health.clear()
    mount_health["ghost"] = {"ok": True, "last_check": "x", "error": None}
    # No mounts.json on disk → no shares → ghost should be pruned
    mgr = MountManager(config_path=str(tmp_path / "no.json"))
    asyncio.run(check_mount_health(mgr))
    assert "ghost" not in mount_health
