"""
providers.py — SophiClaw known provider registry

Hardcoded map of provider name → API base URL + known model suggestions.
Used by /setup to let users pick a provider before entering a model name.
"""

from dataclasses import dataclass, field


@dataclass
class Provider:
    name: str
    base_url: str
    needs_key: bool
    models: list[str]
    notes: str = ""


PROVIDERS: list[Provider] = [
    Provider(
        name="Google AI Studio",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        needs_key=True,
        models=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
                "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"],
        notes="darmowy tier, zalecany",
    ),
    Provider(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        needs_key=True,
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini", "o4-mini"],
    ),
    Provider(
        name="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        needs_key=True,
        models=["grok-3", "grok-3-mini", "grok-2-vision-1212", "grok-2-1212"],
    ),
    Provider(
        name="Mistral",
        base_url="https://api.mistral.ai/v1",
        needs_key=True,
        models=["mistral-large-latest", "mistral-small-latest", "devstral-small-latest",
                "codestral-latest", "mistral-medium-latest"],
    ),
    Provider(
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        needs_key=True,
        models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "meta-llama/llama-4-maverick-17b-128e-instruct",
                "moonshotai/kimi-k2-instruct"],
        notes="bardzo szybki",
    ),
    Provider(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        needs_key=True,
        models=["google/gemini-2.5-flash", "anthropic/claude-sonnet-4-5",
                "anthropic/claude-haiku-4-5", "openai/gpt-4o",
                "meta-llama/llama-3.3-70b-instruct", "deepseek/deepseek-r1"],
        notes="agregator — dostęp do modeli Anthropic i innych",
    ),
    Provider(
        name="Ollama (lokalnie)",
        base_url="http://localhost:11434/v1",
        needs_key=False,
        models=["llava", "llama3.2-vision", "qwen2.5-math", "deepseek-r1", "gemma3"],
        notes="brak klucza API, działa offline",
    ),
]

PROVIDER_BY_NAME: dict[str, Provider] = {p.name: p for p in PROVIDERS}
