"""
llm.py — SophiClaw provider-agnostic LLM adapter

Uses the openai Python library as a universal client.
Any OpenAI-compatible endpoint works: Google AI Studio, Ollama,
OpenRouter, Grok, Groq, OpenAI, etc.

sophiclaw.py never imports anything provider-specific — only this module.
"""

import asyncio
import base64
import logging
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, APIConnectionError

log = logging.getLogger("sophiclaw.llm")


class LLMAdapter:
    """
    Thin async wrapper around any OpenAI-compatible API.
    Instantiated once at bot startup from config values.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        vision_enabled: bool = True,
        temperature: float = 0.65,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.vision_enabled = vision_enabled
        self.temperature = temperature
        self.max_tokens = max_tokens

        # openai client — works with any compatible base_url
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "no-key",  # Ollama ignores this but library requires non-empty
        )
        log.info(
            "LLMAdapter ready | base=%s | model=%s | vision=%s",
            base_url,
            model,
            vision_enabled,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def send(self, messages: list[dict]) -> str:
        """Send a conversation and return the assistant reply as a string."""
        return await self._call(messages, temperature=self.temperature)

    async def send_shadow(self, messages: list[dict]) -> str:
        """Low-temperature call used for shadow scoring / notes (more deterministic)."""
        return await self._call(messages, temperature=0.2)

    # ── Multimodal helpers ─────────────────────────────────────────────────────

    def build_image_content(self, text: str, image_bytes_list: list[bytes]) -> list[dict]:
        """
        Build an OpenAI-format multimodal content list.
        Encodes images as base64 data URIs (works with all providers that support vision).

        Returns a list suitable for use as the 'content' field of a user message.
        """
        if not self.vision_enabled:
            raise ValueError("build_image_content called but vision_enabled=False")

        parts: list[dict] = [{"type": "text", "text": text}]
        for img_bytes in image_bytes_list[:3]:  # max 3 images
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            # Detect JPEG vs PNG by magic bytes
            mime = "image/png" if img_bytes[:4] == b"\x89PNG" else "image/jpeg"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        return parts

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _call(self, messages: list[dict], temperature: float) -> str:
        """Core call with one retry on rate-limit."""
        for attempt in range(2):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=self.max_tokens,
                )
                return response.choices[0].message.content or ""

            except APIStatusError as e:
                if e.status_code == 429 and attempt == 0:
                    log.warning("Rate limited (429) — retrying in 5 s")
                    await asyncio.sleep(5)
                    continue
                log.error("API error %s: %s", e.status_code, e.message)
                return (
                    f"❌ Błąd API (kod {e.status_code}). "
                    "Sprawdź swój klucz API w config.py i spróbuj ponownie."
                )

            except APIConnectionError as e:
                log.error("Connection error: %s", e)
                return (
                    "❌ Nie można połączyć się z API. "
                    "Sprawdź API_BASE w config.py oraz połączenie internetowe."
                )

            except Exception as e:  # noqa: BLE001
                log.exception("Unexpected LLM error: %s", e)
                return f"❌ Nieoczekiwany błąd: {e}"

        return "❌ Nie udało się uzyskać odpowiedzi po ponownej próbie."
