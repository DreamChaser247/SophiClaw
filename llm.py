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
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI, APIStatusError, APIConnectionError

log = logging.getLogger("sophiclaw.llm")

# Model availability tracking
MODEL_AVAILABILITY_FILE = "model_availability.json"
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
        # Support both single model string and list of models for fallback
        self.models = [model] if isinstance(model, str) else model
        self.vision_enabled = vision_enabled
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Initialize model availability tracking
        self._availability = self._load_availability()
        
        # openai client — works with any compatible base_url
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "no-key",  # Ollama ignores this but library requires non-empty
        )
        log.info(
            "LLMAdapter ready | base=%s | models=%s | vision=%s",
            base_url,
            ", ".join(self.models),
            vision_enabled,
        )
        self._log_availability_status()
    
    def get_user_preferred_model(self, user_id: int, db) -> Optional[str]:
        """Get a user's preferred model from the database."""
        preferred = db.get_user_model_preference(user_id)
        if preferred and preferred in self.models:
            return preferred
        return None

    # ── Model Availability Tracking ────────────────────────────────────────────

    def _load_availability(self) -> dict[str, datetime]:
        """Load model availability data from file."""
        try:
            path = Path(MODEL_AVAILABILITY_FILE)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # Convert string timestamps to datetime objects
                availability = {}
                for model, timestamp_str in data.items():
                    if isinstance(timestamp_str, str):
                        try:
                            availability[model] = datetime.fromisoformat(timestamp_str)
                        except ValueError:
                            # Skip invalid timestamps
                            pass
                return availability
        except Exception as e:
            log.warning("Could not load model availability: %s", e)
        return {}

    def _save_availability(self):
        """Save model availability data to file."""
        try:
            # Convert datetime objects to ISO format strings
            data = {model: timestamp.isoformat() 
                   for model, timestamp in self._availability.items()}
            Path(MODEL_AVAILABILITY_FILE).write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            log.error("Could not save model availability: %s", e)

    def _is_model_available(self, model: str) -> bool:
        """Check if a model is available (not rate-limited or cooldown expired)."""
        if model not in self._availability:
            return True  # Never been rate-limited
        
        last_rate_limit = self._availability[model]
        cooldown_expired = datetime.now() > last_rate_limit + timedelta(hours=RATE_LIMIT_COOLDOWN_HOURS)
        
        if cooldown_expired:
            # Cooldown period has passed, model is available again
            del self._availability[model]
            self._save_availability()
            return True
        
        return False

    def _mark_model_unavailable(self, model: str):
        """Mark a model as unavailable due to rate limiting."""
        self._availability[model] = datetime.now()
        self._save_availability()
        log.info("Model %s rate-limited, will retry after %d hours", 
                model, RATE_LIMIT_COOLDOWN_HOURS)

    def _log_availability_status(self):
        """Log current availability status of all models."""
        if not self._availability:
            log.info("All models available")
            return
        
        now = datetime.now()
        status_msg = "Model availability: "
        for model, timestamp in self._availability.items():
            cooldown_remaining = timestamp + timedelta(hours=RATE_LIMIT_COOLDOWN_HOURS) - now
            hours_remaining = cooldown_remaining.total_seconds() / 3600
            status_msg += f"{model} (retry in {hours_remaining:.1f}h), "
        log.info(status_msg.rstrip(", "))

    # ── Public API ─────────────────────────────────────────────────────────────

    async def send(self, messages: list[dict], user_id: Optional[int] = None, db = None) -> str:
        """Send a conversation and return the assistant reply as a string."""
        return await self._call(messages, temperature=self.temperature, user_id=user_id, db=db)

    async def send_shadow(self, messages: list[dict], user_id: Optional[int] = None, db = None) -> str:
        """Low-temperature call used for shadow scoring / notes (more deterministic)."""
        return await self._call(messages, temperature=0.2, user_id=user_id, db=db)

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

    async def _call(self, messages: list[dict], temperature: float, user_id: Optional[int] = None, db = None) -> str:
        """Core call with retry on rate-limit and model fallback with cooldown tracking."""
        attempted_models = set()
        
        # If user has a preferred model and we have db access, try it first
        preferred_model = None
        if user_id is not None and db is not None:
            preferred_model = self.get_user_preferred_model(user_id, db)
        
        for model_cycle in range(len(self.models)):
            # Find the next available model
            next_model_index = self._find_next_available_model(attempted_models, preferred_model)
            if next_model_index is None:
                break  # All models tried
                
            current_model = self.models[next_model_index]
            attempted_models.add(next_model_index)
            
            for attempt in range(2):  # Try each model twice
                try:
                    response = await self._client.chat.completions.create(
                        model=current_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=self.max_tokens,
                    )
                    return response.choices[0].message.content or ""

                except APIStatusError as e:
                    if e.status_code == 429 and attempt == 0:
                        log.warning("Rate limited (429) on model %s — retrying in 5 s", current_model)
                        await asyncio.sleep(5)
                        continue
                    
                    # If we get 429 on second attempt, mark model as unavailable
                    if e.status_code == 429:
                        log.warning("Rate limited (429) on model %s — marking as unavailable", current_model)
                        self._mark_model_unavailable(current_model)
                        break
                    
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

        return "❌ Nie udało się uzyskać odpowiedzi po wyczerpaniu wszystkich dostępnych modeli."

    def _find_next_available_model(self, attempted_indices: set[int], preferred_model: Optional[str] = None) -> Optional[int]:
        """Find the next available model index, trying preferred model first if available."""
        # First, try the preferred model if it exists and is available
        if preferred_model and preferred_model in self.models:
            preferred_index = self.models.index(preferred_model)
            if preferred_index not in attempted_indices and self._is_model_available(preferred_model):
                return preferred_index
        
        # Then try other available models
        for i in range(len(self.models)):
            if i not in attempted_indices and self._is_model_available(self.models[i]):
                return i
        
        # If no available models left, try unavailable ones (cooldown might have expired)
        for i in range(len(self.models)):
            if i not in attempted_indices:
                return i
        
        return None  # All models attempted

    def get_model_status(self) -> list[dict]:
        """Get list of all models with their availability status."""
        return [
            {
                "name": model,
                "available": self._is_model_available(model),
                "cooldown_until": self._availability.get(model)
            }
            for model in self.models
        ]

