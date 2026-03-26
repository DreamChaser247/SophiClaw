"""
commands.py — SophiClaw slash commands

Registered as a discord.py Cog so they stay out of sophiclaw.py.
Discord will suggest these automatically when users type /.
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI, APIStatusError, APIConnectionError

import prompts
import config_writer
from providers import PROVIDERS, PROVIDER_BY_NAME
from review import run_review, read_current_summary

log = logging.getLogger("sophiclaw.commands")


# ── helpers ────────────────────────────────────────────────────────

def _split_chunks(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunk = text[:limit]
        split_at = chunk.rfind("\n")
        if split_at > limit // 2:
            chunk = chunk[:split_at]
        chunks.append(chunk)
        text = text[len(chunk):].lstrip("\n")
    return chunks


async def _send_summary(send_fn, body: str, generated_now: bool,
                        timestamp_line: str | None = None) -> None:
    header = "📋 **Analiza postępów**\n\n" if generated_now else "📋 **Ostatnia analiza postępów**\n\n"
    for i, chunk in enumerate(_split_chunks(body)):
        await send_fn((header if i == 0 else "") + chunk)
    if timestamp_line:
        await send_fn(f"_{timestamp_line.strip('_')}_")
    if generated_now:
        await send_fn("💾 Zapisano do `progress_summary.md`")


async def _safe_defer(interaction: discord.Interaction, ephemeral: bool = False) -> bool:
    """
    Acknowledge the interaction within Discord's 3-second window.
    Returns False (and silently exits) if the token has already expired
    (error 10062 — stale interaction from a reconnect or double-click).
    """
    try:
        await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.errors.NotFound:
        log.warning("Stale interaction ignored for command (10062)")
        return False
    except discord.errors.InteractionResponded:
        # Already responded (e.g. double-invocation) — still safe to followup
        return True


async def _safe_send(interaction: discord.Interaction, *args, **kwargs) -> bool:
    """
    Send the initial interaction response (non-deferred commands).
    Returns False if the token has expired.
    """
    try:
        await interaction.response.send_message(*args, **kwargs)
        return True
    except discord.errors.NotFound:
        log.warning("Stale interaction ignored (10062)")
        return False
    except discord.errors.InteractionResponded:
        return True


# ══════════════════════════════════════════════════════════════════
# /setup — multi-step UI flow
# ══════════════════════════════════════════════════════════════════

class SetupTopicSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="Wybierz co chcesz skonfigurować…",
        options=[
            discord.SelectOption(
                label="Modele AI", value="models", emoji="🤖",
                description="Dodaj lub usuń model z listy fallback",
            ),
        ],
    )
    async def topic_select(self, interaction: discord.Interaction,
                           select: discord.ui.Select):
        await interaction.response.edit_message(
            content="**Konfiguracja modeli AI** — co chcesz zrobić?",
            view=SetupActionSelect(),
        )


class SetupActionSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="Wybierz akcję…",
        options=[
            discord.SelectOption(label="Dodaj model", value="add", emoji="➕",
                                 description="Sprawdź i dodaj nowy model"),
            discord.SelectOption(label="Usuń model(e)", value="remove", emoji="➖",
                                 description="Zaznacz które modele usunąć"),
        ],
    )
    async def action_select(self, interaction: discord.Interaction,
                            select: discord.ui.Select):
        if select.values[0] == "remove":
            current = config_writer.get_model_list()
            if not current:
                await interaction.response.edit_message(
                    content="❌ Brak modeli w config.py.", view=None)
                return
            await interaction.response.edit_message(
                content="**Usuń modele** — zaznacz które chcesz usunąć:",
                view=SetupRemoveSelect(current),
            )
        else:
            await interaction.response.edit_message(
                content="**Dodaj model** — najpierw wybierz providera:",
                view=SetupProviderSelect(),
            )


class SetupRemoveSelect(discord.ui.View):
    def __init__(self, current_models: list[str]):
        super().__init__(timeout=120)
        options = [discord.SelectOption(label=m, value=m) for m in current_models[:25]]
        sel: discord.ui.Select = self.children[0]  # type: ignore
        sel.options    = options
        sel.max_values = len(options)

    @discord.ui.select(
        placeholder="Wybierz modele do usunięcia…",
        min_values=1,
        max_values=1,
        options=[discord.SelectOption(label="–", value="–")],
    )
    async def remove_select(self, interaction: discord.Interaction,
                            select: discord.ui.Select):
        try:
            remaining = config_writer.remove_models(select.values)
        except ValueError as e:
            await interaction.response.edit_message(content=f"❌ {e}", view=None)
            return

        removed_str   = ", ".join(f"`{m}`" for m in select.values)
        remaining_str = ", ".join(f"`{m}`" for m in remaining) if remaining else "_(brak)_"
        await interaction.response.edit_message(
            content=(
                f"✅ Usunięto: {removed_str}\n"
                f"Pozostałe modele: {remaining_str}\n\n"
                "_Zmiany wejdą w życie przy następnym restarcie bota._"
            ),
            view=None,
        )


class SetupProviderSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        options = [
            discord.SelectOption(
                label=p.name,
                value=p.name,
                description=(p.notes or p.base_url)[:100],
            )
            for p in PROVIDERS
        ]
        sel: discord.ui.Select = self.children[0]  # type: ignore
        sel.options = options

    @discord.ui.select(
        placeholder="Wybierz providera…",
        options=[discord.SelectOption(label="–", value="–")],
    )
    async def provider_select(self, interaction: discord.Interaction,
                              select: discord.ui.Select):
        provider = PROVIDER_BY_NAME[select.values[0]]
        await interaction.response.send_modal(AddModelModal(provider))


class AddModelModal(discord.ui.Modal):
    model_name = discord.ui.TextInput(
        label="Nazwa modelu",
        placeholder="np. gemini-2.5-flash",
        min_length=3,
        max_length=120,
    )
    known_models = discord.ui.TextInput(
        label="Znane modele tego providera (tylko podgląd)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, provider):
        super().__init__(title=f"Dodaj model — {provider.name}")
        self._provider = provider
        self.model_name.placeholder = (
            provider.models[0] if provider.models else "wpisz nazwę modelu…"
        )
        self.known_models.default = "\n".join(provider.models) if provider.models else "–"

    async def on_submit(self, interaction: discord.Interaction):
        name = self.model_name.value.strip()
        await interaction.response.defer(ephemeral=True, thinking=True)

        current = config_writer.get_model_list()
        if name in current:
            await interaction.followup.send(
                f"ℹ️ Model `{name}` jest już na liście.", ephemeral=True
            )
            return

        ok, err = await _validate_model(self._provider, name)

        if not ok:
            known = "\n".join(f"  • {m}" for m in self._provider.models)
            await interaction.followup.send(
                f"❌ Model `{name}` nie odpowiedział poprawnie ({err}).\n\n"
                f"Sprawdź czy nazwa jest dokładna.\n"
                f"Znane modele {self._provider.name}:\n{known}",
                ephemeral=True,
            )
            return

        try:
            new_list = config_writer.add_model(name)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Błąd zapisu config.py: {e}", ephemeral=True
            )
            return

        new_list_str = ", ".join(f"`{m}`" for m in new_list)
        await interaction.followup.send(
            f"✅ Model `{name}` odpowiedział poprawnie i został dodany.\n"
            f"Aktualna lista: {new_list_str}\n\n"
            "_Zmiany wejdą w życie przy następnym restarcie bota._",
            ephemeral=True,
        )


async def _validate_model(provider, model_name: str) -> tuple[bool, str]:
    try:
        import config  # type: ignore
        api_key = getattr(config, "API_KEY", "") or "no-key"
    except Exception:
        api_key = "no-key"

    client = AsyncOpenAI(base_url=provider.base_url, api_key=api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompts.MODEL_VALIDATION_PROMPT}],
                temperature=0,
                max_tokens=5,
            ),
            timeout=15,
        )
        content = (resp.choices[0].message.content or "").strip()
        return (True, "") if content else (False, "pusta odpowiedź")
    except APIStatusError as e:
        return False, f"HTTP {e.status_code}"
    except APIConnectionError:
        return False, "błąd połączenia"
    except asyncio.TimeoutError:
        return False, "timeout (15 s)"
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════
# Main Cog
# ══════════════════════════════════════════════════════════════════

class SophiCommands(commands.Cog):

    def __init__(self, bot: commands.Bot, db, sessions, run_shadow, llm_adapter):
        self.bot         = bot
        self.db          = db
        self._sessions   = sessions
        self._run_shadow = run_shadow
        self._llm        = llm_adapter

    # ── /help ──────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Lista komend SophiClaw")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="SophiClaw 🐾 — pomoc",
            description="Wyślij mi pytanie lub zdjęcie zeszytu, a wyjaśnię krok po kroku.",
            color=0x5865F2,
        )
        embed.add_field(name="/help",      value="Ta wiadomość",                            inline=False)
        embed.add_field(name="/setup",     value="Skonfiguruj listę modeli AI",             inline=False)
        embed.add_field(name="/model",     value="Pokaż status modeli i cooldowny",         inline=False)
        embed.add_field(name="/summarise", value="Generuj nową analizę postępów (~30 sek)", inline=False)
        embed.add_field(name="/summary",   value="Pokaż ostatnio wygenerowaną analizę",     inline=False)
        embed.add_field(name="/progress",  value="Pasek opanowania każdego tematu",         inline=False)
        embed.add_field(name="/notes",     value="Ostatnie notatki o Twoim rozumieniu",     inline=False)
        embed.add_field(name="/last10",    value="Ostatnie 10 ocenionych prób",             inline=False)
        embed.add_field(name="/end",       value="Zakończ sesję i zapisz postępy",          inline=False)
        embed.add_field(name="/restart",   value="Przeładuj konfigurację (bez restartu)",   inline=False)
        embed.set_footer(text="Możesz też po prostu pisać — nie musisz używać komend.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setup ─────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Skonfiguruj listę modeli AI")
    async def setup(self, interaction: discord.Interaction):
        current = config_writer.get_model_list()
        current_str = ", ".join(f"`{m}`" for m in current) if current else "_(brak)_"
        await interaction.response.send_message(
            f"⚙️ **Konfiguracja SophiClaw**\n"
            f"Aktualne modele: {current_str}\n\n"
            f"Co chcesz skonfigurować?",
            view=SetupTopicSelect(),
            ephemeral=True,
        )

    # ── /model ─────────────────────────────────────────────────────

    @app_commands.command(name="model", description="Pokaż status modeli i cooldowny")
    async def model(self, interaction: discord.Interaction, model_name: str = None):
        if not await _safe_defer(interaction, ephemeral=True):
            return

        if model_name:
            if model_name in self._llm.models:
                user_id = interaction.user.id
                self.db.set_user_model_preference(user_id, model_name)
                await interaction.followup.send(
                    f"✅ Model `{model_name}` ustawiony jako domyślny dla Ciebie.",
                    ephemeral=True
                )
                return
            else:
                available_models = ", ".join(f"`{m}`" for m in self._llm.models)
                await interaction.followup.send(
                    f"❌ Model `{model_name}` nie znajduje się na liście dostępnych modeli: {available_models}",
                    ephemeral=True
                )
                return

        status = self._llm.get_model_status()
        embed = discord.Embed(title="Status modeli", color=0x5865F2)
        pref = self.db.get_user_model_preference(interaction.user.id)
        embed.add_field(name="Twój domyślny model", value=f"`{pref}`" if pref else "_(brak)_", inline=False)
        for m in status:
            if m["available"]:
                value = "✅ dostępny"
            else:
                until = m["cooldown_until"]
                value = f"⏳ cooldown do {until.strftime('%H:%M')}" if until else "⏳ cooldown"
            embed.add_field(name=m["name"], value=value, inline=False)
        embed.set_footer(text="Użyj /model <nazwa> żeby ustawić domyślny model\nUżyj /setup żeby dodać lub usunąć modele")
        await interaction.followup.send(embed=embed)

    # ── /end ───────────────────────────────────────────────────────

    @app_commands.command(name="end", description="Zakończ bieżącą sesję i zapisz postępy")
    async def end(self, interaction: discord.Interaction):
        # Look up state BEFORE touching Discord — don't pop yet
        state = self._sessions.get(interaction.user.id)
        if not state:
            if not await _safe_send(interaction, "Nie masz aktywnej sesji.", ephemeral=True):
                return
            return

        # Acknowledge first, then remove from dict
        if not await _safe_send(interaction, "✅ Kończę sesję i zapisuję postępy…"):
            return

        # Now it's safe to pop — Discord already confirmed receipt
        self._sessions.pop(interaction.user.id, None)
        await self._run_shadow(state, interaction.user.id)
        await interaction.followup.send("💾 Gotowe! Postępy zapisane.")

    # ── /summarise ─────────────────────────────────────────────────

    @app_commands.command(name="summarise",
                          description="Generuj nową analizę postępów — LLM przegląda wszystkie notatki")
    async def summarise(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction):
            return
        await interaction.followup.send(
            "🔍 Analizuję Twoje postępy… to może potrwać do 30 sekund.")
        summary = await run_review(self.db, self._llm)
        if summary.startswith("❌"):
            await interaction.followup.send(summary)
            return
        await _send_summary(interaction.followup.send, summary, generated_now=True)

    # ── /summary ───────────────────────────────────────────────────

    @app_commands.command(name="summary",
                          description="Pokaż ostatnio wygenerowaną analizę postępów")
    async def summary(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction):
            return
        result = read_current_summary()
        if result is None:
            await interaction.followup.send(
                "Brak zapisanej analizy. Użyj `/summarise`, żeby wygenerować pierwszą.")
            return
        body, timestamp_line = result
        await _send_summary(interaction.followup.send, body, generated_now=False,
                            timestamp_line=timestamp_line)

    # ── /progress ──────────────────────────────────────────────────

    @app_commands.command(name="progress", description="Opanowanie każdego tematu matematyki")
    async def progress(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction):
            return
        active = [t for t in self.db.get_topic_mastery() if t["attempt_count"]]
        if not active:
            await interaction.followup.send(
                "Brak danych — rozwiąż kilka zadań najpierw! 📚")
            return
        embed = discord.Embed(title="📈 Opanowanie tematów", color=0x5865F2)
        chunk, field_n = "", 1
        for t in active:
            bar  = "🟩" * round(t["mastery"] / 10) + "⬜" * (10 - round(t["mastery"] / 10))
            line = f"{bar} **{t['name']}** — {t['mastery']:.0f}% ({t['attempt_count']} prób)\n"
            if len(chunk) + len(line) > 900:
                embed.add_field(name=f"Tematy ({field_n})", value=chunk, inline=False)
                chunk, field_n = "", field_n + 1
            chunk += line
        if chunk:
            embed.add_field(
                name="Tematy" if field_n == 1 else f"Tematy ({field_n})",
                value=chunk, inline=False,
            )
        await interaction.followup.send(embed=embed)

    # ── /notes ─────────────────────────────────────────────────────

    @app_commands.command(name="notes",
                          description="Ostatnie notatki o Twoim rozumieniu matematyki")
    async def notes(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction):
            return
        notes = self.db.get_recent_notes(8)
        if not notes:
            await interaction.followup.send(
                "Brak notatek — wróć po kilku sesjach! 📝")
            return
        embed = discord.Embed(title="📝 Notatki z sesji", color=0xFEE75C)
        for n in notes:
            embed.add_field(name=n["created_at"][:10], value=n["content"], inline=False)
        await interaction.followup.send(embed=embed)

    # ── /last10 ────────────────────────────────────────────────────

    @app_commands.command(name="last10", description="Ostatnie 10 ocenionych prób")
    async def last10(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction):
            return
        attempts = self.db.get_last_attempts(10)
        if not attempts:
            await interaction.followup.send("Brak historii prób.")
            return
        embed = discord.Embed(title="🕐 Ostatnie 10 prób", color=0xEB459E)
        lines = []
        for a in attempts:
            name = a.get("topic_name") or a.get("topic_code") or "?"
            date = a["timestamp"][:16].replace("T", " ")
            pip  = "🟢" if a["score"] >= 4 else ("🟡" if a["score"] >= 2 else "🔴")
            lines.append(
                f"{pip} `{date}` **{name}** — {a['score']}/6 (trudność {a['difficulty']}/6)"
            )
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ── /restart ───────────────────────────────────────────────────

    @app_commands.command(name="restart",
                          description="Przeładuj konfigurację bez restartu procesu")
    async def restart(self, interaction: discord.Interaction):
        if not await _safe_defer(interaction, ephemeral=True):
            return

        import importlib
        import config as config_module
        importlib.reload(config_module)

        import sophiclaw as main_module
        changes = main_module.llm_adapter.reload(
            base_url       = getattr(config_module, "API_BASE", ""),
            api_key        = getattr(config_module, "API_KEY", ""),
            model          = getattr(config_module, "MODEL", "gemini-2.5-flash"),
            vision_enabled = getattr(config_module, "VISION_ENABLED", True),
            max_tokens     = getattr(config_module, "MAX_TOKENS", 8192),
        )

        main_module.REVIEW_EVERY_N = getattr(config_module, "REVIEW_EVERY_N_SESSIONS", 5)

        model_str = ", ".join(f"`{m}`" for m in main_module.llm_adapter.models)
        if changes:
            changes_str = "\n".join(f"  • {c}" for c in changes)
            msg = f"✅ Konfiguracja przeładowana.\n{changes_str}\n\nAktualne modele: {model_str}"
        else:
            msg = f"✅ Konfiguracja przeładowana — bez zmian.\nModele: {model_str}"

        await interaction.followup.send(msg, ephemeral=True)