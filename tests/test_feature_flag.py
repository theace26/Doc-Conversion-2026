import pytest
from core.feature_flags import is_new_ux_enabled


def test_new_ux_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_NEW_UX", raising=False)
    assert is_new_ux_enabled() is False


def test_new_ux_enabled_when_set_true(monkeypatch):
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    assert is_new_ux_enabled() is True


def test_new_ux_disabled_when_set_false(monkeypatch):
    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    assert is_new_ux_enabled() is False


@pytest.mark.parametrize("val", ["1", "yes", "True", "TRUE", "on"])
def test_new_ux_truthy_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_NEW_UX", val)
    assert is_new_ux_enabled() is True


@pytest.mark.parametrize("val", ["0", "no", "False", "off", "", "  "])
def test_new_ux_falsy_values(monkeypatch, val):
    monkeypatch.setenv("ENABLE_NEW_UX", val)
    assert is_new_ux_enabled() is False


def test_flag_reads_env_at_each_call(monkeypatch):
    """Pins the no-caching contract: mid-session toggle works in both
    directions (spec §13: 'mid-session toggle works in both directions').

    A future @lru_cache or module-level read would silently break this.
    """
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    assert is_new_ux_enabled() is True
    monkeypatch.setenv("ENABLE_NEW_UX", "false")
    assert is_new_ux_enabled() is False
    monkeypatch.setenv("ENABLE_NEW_UX", "true")
    assert is_new_ux_enabled() is True
