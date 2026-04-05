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
        assert "smb_username" in raw["source"]

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
