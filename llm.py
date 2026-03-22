"""
llm.py — SophiClaw provider-agnostic LLM adapter

Uses the openai Python library as a universal client.
Any OpenAI-compatible endpoint works: Google AI Studio, Ollama,
OpenRouter, Grok, Groq, OpenAI, etc.

sophiclaw.py never imports anything provider-specific — only this module.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, APIConnectionError

log = logging.getLogger("sophiclaw.llm")

MODEL_AVAILABILITY_FILE   = "model_availability.json"
RATE_LIMIT_COOLDOWN_HOURS = 4


class LLMAdapter:
    """
    Thin async wrapper around any OpenAI-compatible API.
    Instantiated once at bot startup from config values.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str | list[str],
        vision_enabled: bool = True,
        temperature: float = 0.65,
        max_tokens: int = 8192,
    ):
        self.models         = [model] if isinstance(model, str) else list(model)
        self.vision_enabled = vision_enabled
        self.temperature    = temperature
        self.max_tokens     = max_tokens
        self._availability  = self._load_availability()
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "no-key",
        )
        log.info(
            "LLMAdapter ready | base=%s | models=%s | vision=%s",
            base_url, ", ".join(self.models), vision_enabled,
        )
        self._log_availability_status()

    def reload(self, base_url: str, api_key: str, model: str | list[str],
               vision_enabled: bool, max_tokens: int) -> list[str]:
        """
        Update adapter in-place from new config values.
        Called by /restart — mutates the existing instance so all references
        in sophiclaw.py (globals, _do_end_session closure, etc.) stay valid.
        Rate-limit state (_availability) is preserved across reloads.
        Returns a list of human-readable change descriptions.
        """
        new_models = [model] if isinstance(model, str) else list(model)
        changes = []

        if new_models != self.models:
            changes.append(f"models: {self.models} → {new_models}")
            self.models = new_models

        if vision_enabled != self.vision_enabled:
            changes.append(f"vision: {self.vision_enabled} → {vision_enabled}")
            self.vision_enabled = vision_enabled

        if max_tokens != self.max_tokens:
            changes.append(f"max_tokens: {self.max_tokens} → {max_tokens}")
            self.max_tokens = max_tokens

        # Always rebuild the client — base_url or api_key may have changed
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "no-key")
        log.info("LLMAdapter reloaded | models=%s | vision=%s", self.models, vision_enabled)
        return changes

    def get_user_preferred_model(self, user_id: int, db) -> Optional[str]:
        preferred = db.get_user_model_preference(user_id)
        if preferred and preferred in self.models:
            return preferred
        return None

    # ── Model availability tracking ────────────────────────────────

    def _load_availability(self) -> dict[str, datetime]:
        try:
            path = Path(MODEL_AVAILABILITY_FILE)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                availability = {}
                for model, ts in data.items():
                    if isinstance(ts, str):
                        try:
                            availability[model] = datetime.fromisoformat(ts)
                        except ValueError:
                            pass
                return availability
        except Exception as e:
            log.warning("Could not load model availability: %s", e)
        return {}

    def _save_availability(self) -> None:
        try:
            data = {m: ts.isoformat() for m, ts in self._availability.items()}
            Path(MODEL_AVAILABILITY_FILE).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            log.error("Could not save model availability: %s", e)

    def _is_model_available(self, model: str) -> bool:
        if model not in self._availability:
            return True
        last = self._availability[model]
        if datetime.now() > last + timedelta(hours=RATE_LIMIT_COOLDOWN_HOURS):
            del self._availability[model]
            self._save_availability()
            return True
        return False

    def _mark_model_unavailable(self, model: str) -> None:
        self._availability[model] = datetime.now()
        self._save_availability()
        log.info("Model %s rate-limited, will retry after %d hours",
                 model, RATE_LIMIT_COOLDOWN_HOURS)

    def _log_availability_status(self) -> None:
        if not self._availability:
            log.info("All models available")
            return
        now = datetime.now()
        parts = []
        for model, ts in self._availability.items():
            h = (ts + timedelta(hours=RATE_LIMIT_COOLDOWN_HOURS) - now).total_seconds() / 3600
            parts.append(f"{model} (retry in {h:.1f}h)")
        log.info("Model availability: %s", ", ".join(parts))

    # ── Public API ─────────────────────────────────────────────────

    async def send(self, messages: list[dict],
                   user_id: Optional[int] = None, db=None) -> str:
        return await self._call(messages, temperature=self.temperature,
                                user_id=user_id, db=db)

    async def send_shadow(self, messages: list[dict],
                          user_id: Optional[int] = None, db=None) -> str:
        return await self._call(messages, temperature=0.2,
                                user_id=user_id, db=db)

    def build_image_content(self, text: str, image_bytes_list: list[bytes]) -> list[dict]:
        if not self.vision_enabled:
            raise ValueError("build_image_content called but vision_enabled=False")
        parts: list[dict] = [{"type": "text", "text": text}]
        for img in image_bytes_list[:3]:
            b64  = base64.b64encode(img).decode("utf-8")
            mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{mime};base64,{b64}"}})
        return parts

    def get_model_status(self) -> list[dict]:
        return [
            {
                "name":          m,
                "available":     self._is_model_available(m),
                "cooldown_until": self._availability.get(m),
            }
            for m in self.models
        ]

    # ── Internal ───────────────────────────────────────────────────

    async def _call(self, messages: list[dict], temperature: float,
                    user_id: Optional[int] = None, db=None) -> str:
        attempted = set()
        preferred = None
        if user_id is not None and db is not None:
            preferred = self.get_user_preferred_model(user_id, db)

        for _ in range(len(self.models)):
            idx = self._find_next_available_model(attempted, preferred)
            if idx is None:
                break
            current = self.models[idx]
            attempted.add(idx)

            for attempt in range(2):
                try:
                    resp = await self._client.chat.completions.create(
                        model=current,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=self.max_tokens,
                    )
                    return resp.choices[0].message.content or ""

                except APIStatusError as e:
                    if e.status_code == 429 and attempt == 0:
                        log.warning("Rate limited (429) on %s — retrying in 5 s", current)
                        await asyncio.sleep(5)
                        continue
                    if e.status_code == 429:
                        log.warning("Rate limited (429) on %s — marking unavailable", current)
                        self._mark_model_unavailable(current)
                        break
                    log.error("API error %s: %s", e.status_code, e.message)
                    return (f"❌ Błąd API (kod {e.status_code}). "
                            "Sprawdź swój klucz API w config.py i spróbuj ponownie.")

                except APIConnectionError:
                    log.error("Connection error on %s", current)
                    return ("❌ Nie można połączyć się z API. "
                            "Sprawdź API_BASE w config.py oraz połączenie internetowe.")

                except Exception as e:
                    log.exception("Unexpected LLM error: %s", e)
                    return f"❌ Nieoczekiwany błąd: {e}"

        return "❌ Nie udało się uzyskać odpowiedzi po wyczerpaniu wszystkich dostępnych modeli."

    def _find_next_available_model(self, attempted: set[int],
                                   preferred: Optional[str] = None) -> Optional[int]:
        if preferred and preferred in self.models:
            i = self.models.index(preferred)
            if i not in attempted and self._is_model_available(preferred):
                return i
        for i in range(len(self.models)):
            if i not in attempted and self._is_model_available(self.models[i]):
                return i
        for i in range(len(self.models)):
            if i not in attempted:
                return i
        return None