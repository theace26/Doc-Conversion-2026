"""Tests for core/gpu_detector.py — GPU detection and execution path resolution."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.gpu_detector import GPUInfo, detect_gpu, get_gpu_info, _probe_hashcat_backend


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton before each test."""
    import core.gpu_detector
    core.gpu_detector._gpu_info = None
    yield
    core.gpu_detector._gpu_info = None


class TestDetection:

    def test_detect_no_gpu(self, tmp_path):
        fake_report = tmp_path / "nonexistent.json"  # doesn't exist
        with patch("core.gpu_detector.shutil.which", return_value=None), \
             patch("core.gpu_detector._HOST_WORKER_REPORT", fake_report):
            info = detect_gpu()
        assert info.execution_path == "none"
        assert info.container_gpu_available is False
        assert info.host_worker_available is False

    @patch("core.gpu_detector.subprocess.run")
    @patch("core.gpu_detector.shutil.which")
    def test_detect_nvidia_container(self, mock_which, mock_run):
        def which_side_effect(name):
            if name == "nvidia-smi":
                return "/usr/bin/nvidia-smi"
            if name == "hashcat":
                return "/usr/bin/hashcat"
            if name == "nvcc":
                return None
            return None
        mock_which.side_effect = which_side_effect

        def run_side_effect(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "nvidia-smi":
                result.returncode = 0
                result.stdout = "NVIDIA GeForce RTX 3080, 10240, 535.104.05"
            elif cmd[0] == "hashcat" and "-I" in cmd:
                result.returncode = 0
                result.stdout = "Backend Device #1: CUDA"
            else:
                result.returncode = 1
                result.stdout = ""
            return result
        mock_run.side_effect = run_side_effect

        with patch("core.gpu_detector._HOST_WORKER_REPORT") as mock_report:
            mock_report.exists.return_value = False
            info = detect_gpu()

        assert info.container_gpu_available is True
        assert info.container_gpu_vendor == "nvidia"
        assert info.container_gpu_name == "NVIDIA GeForce RTX 3080"
        assert info.execution_path == "container"

    def test_detect_host_worker_amd(self, tmp_path):
        caps = {
            "available": True,
            "gpu_vendor": "amd",
            "gpu_name": "AMD Radeon RX 7900 XTX",
            "gpu_vram_mb": 24576,
            "hashcat_backend": "ROCm",
            "hashcat_version": "v6.2.6",
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        assert info.host_worker_available is True
        assert info.host_worker_gpu_vendor == "amd"
        assert info.execution_path == "host"
        assert info.effective_gpu_name == "AMD Radeon RX 7900 XTX"

    def test_detect_host_worker_intel(self, tmp_path):
        caps = {
            "available": True,
            "gpu_vendor": "intel",
            "gpu_name": "Intel Arc A770",
            "gpu_vram_mb": 16384,
            "hashcat_backend": "OpenCL",
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        assert info.execution_path == "host"
        assert info.effective_backend == "OpenCL"

    @patch("core.gpu_detector.subprocess.run")
    @patch("core.gpu_detector.shutil.which")
    def test_nvidia_takes_precedence(self, mock_which, mock_run, tmp_path):
        """Container NVIDIA should win over host AMD."""
        mock_which.side_effect = lambda n: "/usr/bin/" + n if n in ("nvidia-smi", "hashcat") else None

        def run_se(cmd, **kwargs):
            r = MagicMock()
            if cmd[0] == "nvidia-smi":
                r.returncode = 0
                r.stdout = "RTX 4090, 24576, 545.23"
            elif "hashcat" in cmd[0] and "-I" in cmd:
                r.returncode = 0
                r.stdout = "CUDA backend"
            else:
                r.returncode = 1
                r.stdout = ""
            return r
        mock_run.side_effect = run_se

        caps = {"available": True, "gpu_vendor": "amd", "gpu_name": "RX 7900", "hashcat_backend": "ROCm"}
        report = tmp_path / "caps.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report):
            info = detect_gpu()

        assert info.execution_path == "container"  # NVIDIA wins

    def test_capabilities_file_missing(self, tmp_path):
        fake_report = tmp_path / "nonexistent.json"
        with patch("core.gpu_detector._HOST_WORKER_REPORT", fake_report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()
        assert info.host_worker_available is False

    def test_capabilities_file_corrupt(self, tmp_path):
        report = tmp_path / "bad.json"
        report.write_text("{invalid json!!")
        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()
        assert info.host_worker_available is False

    def test_cache_singleton(self, tmp_path):
        fake_report = tmp_path / "nonexistent.json"
        with patch("core.gpu_detector.shutil.which", return_value=None), \
             patch("core.gpu_detector._HOST_WORKER_REPORT", fake_report):
            info1 = detect_gpu()
            info2 = get_gpu_info()
        assert info1 is info2


class TestAppleSiliconDetection:
    """Test Apple Silicon Metal GPU detection via host worker capabilities."""

    def test_worker_capabilities_apple_metal(self, tmp_path):
        """Container correctly parses Apple Silicon worker capabilities."""
        caps = {
            "available": True,
            "gpu_vendor": "apple",
            "gpu_name": "Apple M3 Max (40-core GPU)",
            "gpu_vram_mb": 27648,
            "hashcat_backend": "Metal",
            "hashcat_version": "v6.2.6",
            "host_os": "Darwin",
            "host_machine": "arm64",
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        assert info.host_worker_available is True
        assert info.host_worker_gpu_vendor == "apple"
        assert info.host_worker_gpu_backend == "Metal"
        assert info.execution_path == "host"
        assert info.effective_gpu_name == "Apple M3 Max (40-core GPU)"
        assert info.effective_backend == "Metal"

    def test_apple_metal_is_valid_host_backend(self, tmp_path):
        """Metal backend is recognized as a valid host GPU for execution path."""
        caps = {
            "available": True,
            "gpu_vendor": "apple",
            "gpu_name": "Apple M2",
            "gpu_vram_mb": 12288,
            "hashcat_backend": "Metal",
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        assert info.execution_path == "host"  # not "none" or "container_cpu"

    def test_nvidia_container_beats_apple_host(self, tmp_path):
        """Container NVIDIA should win over Apple Silicon host worker."""
        with patch("core.gpu_detector.shutil.which") as mock_which, \
             patch("core.gpu_detector.subprocess.run") as mock_run:
            mock_which.side_effect = lambda n: "/usr/bin/" + n if n in ("nvidia-smi", "hashcat") else None

            def run_se(cmd, **kwargs):
                r = MagicMock()
                if cmd[0] == "nvidia-smi":
                    r.returncode = 0
                    r.stdout = "RTX 4090, 24576, 545.23"
                elif "hashcat" in cmd[0] and "-I" in cmd:
                    r.returncode = 0
                    r.stdout = "CUDA backend"
                else:
                    r.returncode = 1
                    r.stdout = ""
                return r
            mock_run.side_effect = run_se

            caps = {
                "available": True,
                "gpu_vendor": "apple",
                "gpu_name": "Apple M3 Max",
                "hashcat_backend": "Metal",
            }
            report = tmp_path / "caps.json"
            report.write_text(json.dumps(caps))

            with patch("core.gpu_detector._HOST_WORKER_REPORT", report):
                info = detect_gpu()

        assert info.execution_path == "container"  # NVIDIA wins

    def test_apple_vram_is_unified_memory(self, tmp_path):
        """Apple Silicon VRAM represents unified memory estimate."""
        caps = {
            "available": True,
            "gpu_vendor": "apple",
            "gpu_name": "Apple M4 Pro (20-core GPU)",
            "gpu_vram_mb": 27648,  # 75% of 36 GB
            "hashcat_backend": "Metal",
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        assert info.host_worker_gpu_vram_mb == 27648

    def test_apple_no_backend_falls_to_cpu(self, tmp_path):
        """Apple vendor with no hashcat backend should not resolve as host GPU."""
        caps = {
            "available": True,
            "gpu_vendor": "apple",
            "gpu_name": "Apple M1",
            "gpu_vram_mb": 6144,
            "hashcat_backend": None,  # hashcat too old or not installed
        }
        report = tmp_path / "worker_capabilities.json"
        report.write_text(json.dumps(caps))

        with patch("core.gpu_detector._HOST_WORKER_REPORT", report), \
             patch("core.gpu_detector.shutil.which", return_value=None):
            info = detect_gpu()

        # No container GPU, no valid host backend → falls through
        assert info.execution_path == "none"
