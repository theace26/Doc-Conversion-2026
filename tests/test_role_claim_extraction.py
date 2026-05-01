import pytest
from core.auth import extract_role, Role


def test_role_admin_from_claims():
    assert extract_role({"sub": "x@local46.org", "role": "admin"}) == Role.ADMIN


def test_role_operator_from_claims():
    assert extract_role({"sub": "x", "role": "operator"}) == Role.OPERATOR


def test_role_member_from_claims():
    assert extract_role({"sub": "x", "role": "member"}) == Role.MEMBER


def test_role_missing_defaults_to_member():
    """Defensive: if UnionCore omits role, treat as member (lowest privilege)."""
    assert extract_role({"sub": "x"}) == Role.MEMBER


def test_role_unknown_value_defaults_to_member():
    """Defensive: unknown role string -> member."""
    assert extract_role({"sub": "x", "role": "superuser"}) == Role.MEMBER


def test_role_case_insensitive():
    assert extract_role({"sub": "x", "role": "ADMIN"}) == Role.ADMIN


def test_role_hierarchy_comparison():
    """IntEnum: admin >= operator >= member for visibility gates."""
    assert Role.ADMIN >= Role.OPERATOR
    assert Role.OPERATOR >= Role.MEMBER
    assert Role.ADMIN >= Role.MEMBER
    assert not (Role.MEMBER >= Role.ADMIN)


def test_role_non_string_defaults_to_member():
    """Defensive: non-string role claims (int, list, dict) -> member, not crash.

    Some JWT issuers encode role as an integer or array; the function must fail
    closed, never raise.
    """
    assert extract_role({"sub": "x", "role": 2}) == Role.MEMBER
    assert extract_role({"sub": "x", "role": ["admin"]}) == Role.MEMBER
    assert extract_role({"sub": "x", "role": {"name": "admin"}}) == Role.MEMBER
    assert extract_role({"sub": "x", "role": None}) == Role.MEMBER
