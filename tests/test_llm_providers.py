"""
Tests for Track B — LLM provider system.

Covers:
  - API key encryption/decryption
  - Provider CRUD operations
  - Masked API keys in list response
  - Verify-draft endpoint
  - Provider activation
  - LLMEnhancer graceful degradation
"""

import os
import pytest

from core.database import (
    create_llm_provider,
    delete_llm_provider,
    get_active_provider,
    get_llm_provider,
    init_db,
    list_llm_providers,
    set_active_provider,
    update_llm_provider,
)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Use a temporary database and set SECRET_KEY for each test."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("core.database.DB_PATH", db_path)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests-32chars!")
    await init_db()
    yield


# ── Crypto tests ──────────────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests-32chars!")
    from core.crypto import encrypt_value, decrypt_value
    original = "sk-ant-api03-secret-key-value"
    encrypted = encrypt_value(original)
    assert encrypted != original
    decrypted = decrypt_value(encrypted)
    assert decrypted == original


def test_encrypt_requires_secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    from core.crypto import encrypt_value
    with pytest.raises(ValueError, match="SECRET_KEY"):
        encrypt_value("test")


def test_mask_api_key():
    from core.crypto import mask_api_key
    assert mask_api_key("sk-ant-api03-longsecretkey") == "sk-ant****"
    assert mask_api_key("short") == "sh****"
    assert mask_api_key(None) is None
    assert mask_api_key("") is None


# ── Provider CRUD tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_provider():
    provider_id = await create_llm_provider(
        name="Test Claude",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="sk-ant-test-key-123",
    )
    assert provider_id

    # Get should return decrypted key
    prov = await get_llm_provider(provider_id)
    assert prov is not None
    assert prov["name"] == "Test Claude"
    assert prov["provider"] == "anthropic"
    assert prov["api_key"] == "sk-ant-test-key-123"
    assert prov["is_active"] == 0


@pytest.mark.asyncio
async def test_list_providers_masks_keys():
    await create_llm_provider(
        name="Claude Masked",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="sk-ant-api03-secret",
    )
    providers = await list_llm_providers()
    assert len(providers) >= 1
    for p in providers:
        if p["name"] == "Claude Masked":
            # Key should be masked
            assert p["api_key"] is not None
            assert "****" in p["api_key"]
            assert p["api_key"] != "sk-ant-api03-secret"


@pytest.mark.asyncio
async def test_update_provider():
    provider_id = await create_llm_provider(
        name="Update Test",
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
    )
    await update_llm_provider(provider_id, model="gpt-4o-mini")
    prov = await get_llm_provider(provider_id)
    assert prov["model"] == "gpt-4o-mini"
    # Original key should still be intact
    assert prov["api_key"] == "sk-test-key"


@pytest.mark.asyncio
async def test_delete_provider():
    provider_id = await create_llm_provider(
        name="Delete Me",
        provider="ollama",
        model="llama3",
    )
    await delete_llm_provider(provider_id)
    prov = await get_llm_provider(provider_id)
    assert prov is None


@pytest.mark.asyncio
async def test_set_active_provider():
    id1 = await create_llm_provider(name="Prov1", provider="anthropic", model="claude-sonnet-4-6")
    id2 = await create_llm_provider(name="Prov2", provider="openai", model="gpt-4o")

    await set_active_provider(id1)
    p1 = await get_llm_provider(id1)
    p2 = await get_llm_provider(id2)
    assert p1["is_active"] == 1
    assert p2["is_active"] == 0

    # Switch active
    await set_active_provider(id2)
    p1 = await get_llm_provider(id1)
    p2 = await get_llm_provider(id2)
    assert p1["is_active"] == 0
    assert p2["is_active"] == 1


@pytest.mark.asyncio
async def test_get_active_provider_none():
    active = await get_active_provider()
    assert active is None


@pytest.mark.asyncio
async def test_get_active_provider_returns_decrypted():
    provider_id = await create_llm_provider(
        name="Active Claude",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="sk-ant-real-key",
    )
    await set_active_provider(provider_id)
    active = await get_active_provider()
    assert active is not None
    assert active["api_key"] == "sk-ant-real-key"


# ── LLMEnhancer graceful degradation tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_enhancer_no_client_returns_input():
    from core.llm_enhancer import LLMEnhancer
    enhancer = LLMEnhancer(None)
    result = await enhancer.correct_ocr_text("garbled text")
    assert result == "garbled text"


@pytest.mark.asyncio
async def test_enhancer_no_client_summary_returns_none():
    from core.llm_enhancer import LLMEnhancer
    enhancer = LLMEnhancer(None)
    result = await enhancer.summarize_document("# My Doc\nSome content")
    assert result is None


@pytest.mark.asyncio
async def test_enhancer_no_client_headings_returns_input():
    from core.llm_enhancer import LLMEnhancer
    enhancer = LLMEnhancer(None)
    blocks = ["Introduction", "Some text", "Conclusion"]
    result = await enhancer.infer_headings(blocks)
    assert result == blocks


@pytest.mark.asyncio
async def test_enhancer_failed_call_returns_input():
    """If LLM call fails, enhancer returns original text."""
    from core.llm_enhancer import LLMEnhancer
    from core.llm_client import LLMClient, LLMResponse
    from unittest.mock import AsyncMock

    client = LLMClient({"provider": "anthropic", "model": "test", "api_key": "x"})
    client.complete = AsyncMock(return_value=LLMResponse(
        text="", provider="anthropic", model="test",
        success=False, error="API error",
    ))
    enhancer = LLMEnhancer(client)
    result = await enhancer.correct_ocr_text("garbled text")
    assert result == "garbled text"


# ── API endpoint tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_providers_api(tmp_path, monkeypatch):
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/llm-providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data


@pytest.mark.asyncio
async def test_registry_api():
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/llm-providers/registry")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic" in data["registry"]
        assert "openai" in data["registry"]


@pytest.mark.asyncio
async def test_create_provider_api():
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/llm-providers", json={
            "name": "API Test Provider",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "api_key": "sk-ant-test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data


@pytest.mark.asyncio
async def test_verify_draft_api():
    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/llm-providers/verify-draft", json={
            "provider": "ollama",
            "model": "llama3",
            "api_base_url": "http://localhost:11434",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        # Ollama likely not running in test env, so success may be False


@pytest.mark.asyncio
async def test_delete_active_provider_requires_force():
    from httpx import AsyncClient, ASGITransport
    from main import app

    # Create and activate a provider
    provider_id = await create_llm_provider(
        name="Force Delete Test",
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    await set_active_provider(provider_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without force — should be 409
        resp = await client.delete(f"/api/llm-providers/{provider_id}")
        assert resp.status_code == 409

        # With force — should succeed
        resp = await client.delete(f"/api/llm-providers/{provider_id}?force=true")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_activate_provider_api():
    provider_id = await create_llm_provider(
        name="Activate API Test",
        provider="anthropic",
        model="claude-sonnet-4-6",
    )

    from httpx import AsyncClient, ASGITransport
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/llm-providers/{provider_id}/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] == provider_id


# ── Provider registry test ───────────────────────────────────────────────────

def test_provider_registry_structure():
    from core.llm_providers import PROVIDER_REGISTRY
    assert "anthropic" in PROVIDER_REGISTRY
    assert "openai" in PROVIDER_REGISTRY
    assert "gemini" in PROVIDER_REGISTRY
    assert "ollama" in PROVIDER_REGISTRY
    assert "custom" in PROVIDER_REGISTRY

    for key, val in PROVIDER_REGISTRY.items():
        assert "display_name" in val
        assert "models" in val
        assert "requires_api_key" in val
