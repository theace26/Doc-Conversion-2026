"""
Known LLM providers with their models and API shapes.

PROVIDER_REGISTRY is a static dict describing each supported provider.
The frontend uses GET /api/llm-providers/registry to get this data
so it can build provider/model dropdowns without hardcoding.
"""

PROVIDER_REGISTRY: dict[str, dict] = {
    "anthropic": {
        "display_name": "Claude (Anthropic)",
        "models": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ],
        "default_model": "claude-sonnet-4-6",
        "api_base_url": "https://api.anthropic.com",
        "requires_api_key": True,
        "docs_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "display_name": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o",
        "api_base_url": "https://api.openai.com",
        "requires_api_key": True,
        "docs_url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "display_name": "Gemini (Google)",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
        "default_model": "gemini-1.5-flash",
        "api_base_url": "https://generativelanguage.googleapis.com",
        "requires_api_key": True,
        "docs_url": "https://aistudio.google.com/app/apikey",
    },
    "ollama": {
        "display_name": "Ollama (Local)",
        "models": [],  # populated dynamically by pinging /api/tags
        "default_model": "",
        "api_base_url": "http://localhost:11434",
        "requires_api_key": False,
        "docs_url": "https://ollama.com/download",
    },
    "custom": {
        "display_name": "Custom (OpenAI-compatible)",
        "models": [],  # user enters manually
        "default_model": "",
        "api_base_url": "",
        "requires_api_key": False,
        "docs_url": None,
    },
}
