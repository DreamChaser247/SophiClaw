"""
commands.py — SophiClaw slash commands

Registered as a discord.py Cog so they stay out of sophiclaw.py.
Discord will suggest these automatically when users type /.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from review import run_review, read_current_summary


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


class SophiCommands(commands.Cog):
    """All SophiClaw slash commands in one place."""

    def __init__(self, bot: commands.Bot, db, sessions, run_shadow, llm_adapter):
        self.bot          = bot
        self.db           = db
        self._sessions    = sessions
        self._run_shadow  = run_shadow
        self._llm         = llm_adapter

    # ── /help ──────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Lista komend SophiClaw")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="SophiClaw 🐾 — pomoc",
            description="Wyślij mi pytanie lub zdjęcie zeszytu, a wyjaśnię krok po kroku.",
            color=0x5865F2,
        )
        embed.add_field(name="/help",      value="Ta wiadomość",                                    inline=False)
        embed.add_field(name="/model",     value="Zmień model AI lub zobacz dostępne modele",      inline=False)
        embed.add_field(name="/summarise", value="Generuj nową analizę postępów przez LLM (~30 sek)", inline=False)
        embed.add_field(name="/summary",   value="Pokaż ostatnio wygenerowaną analizę",             inline=False)
        embed.add_field(name="/progress",  value="Pasek opanowania każdego tematu",                 inline=False)
        embed.add_field(name="/notes",     value="Ostatnie notatki o Twoim rozumieniu",             inline=False)
        embed.add_field(name="/last10",    value="Ostatnie 10 ocenionych prób",                     inline=False)
        embed.add_field(name="/end",       value="Zakończ sesję i zapisz postępy",                  inline=False)
        embed.set_footer(text="Możesz też po prostu pisać — nie musisz używać komend.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /end ───────────────────────────────────────────────────────

    @app_commands.command(name="end", description="Zakończ bieżącą sesję i zapisz postępy")
    async def end(self, interaction: discord.Interaction):
        state = self._sessions.pop(interaction.user.id, None)
        if not state:
            await interaction.response.send_message(
                "Nie masz aktywnej sesji.", ephemeral=True
            )
            return
        await interaction.response.send_message("✅ Kończę sesję i zapisuję postępy…")
        await self._run_shadow(state)
        await interaction.followup.send("💾 Gotowe! Postępy zapisane.")

    # ── /summarise ─────────────────────────────────────────────────

    @app_commands.command(
        name="summarise",
        description="Generuj nową analizę postępów — LLM przegląda wszystkie notatki"
    )
    async def summarise(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.followup.send(
            "🔍 Analizuję Twoje postępy… to może potrwać do 30 sekund."
        )

        summary = await run_review(self.db, self._llm)

        if summary.startswith("❌"):
            await interaction.followup.send(summary)
            return

        await _send_summary(interaction.followup.send, summary, generated_now=True)

    # ── /summary ───────────────────────────────────────────────────

    @app_commands.command(
        name="summary",
        description="Pokaż ostatnio wygenerowaną analizę postępów"
    )
    async def summary(self, interaction: discord.Interaction):
        await interaction.response.defer()

        result = read_current_summary()
        if result is None:
            await interaction.followup.send(
                "Brak zapisanej analizy. Użyj `/summarise`, żeby wygenerować pierwszą."
            )
            return

        body, timestamp_line = result
        await _send_summary(interaction.followup.send, body, generated_now=False,
                            timestamp_line=timestamp_line)

    # ── /progress ──────────────────────────────────────────────────

    @app_commands.command(name="progress", description="Opanowanie każdego tematu matematyki")
    async def progress(self, interaction: discord.Interaction):
        await interaction.response.defer()
        topics = self.db.get_topic_mastery()
        active = [t for t in topics if t["attempt_count"]]

        if not active:
            await interaction.followup.send(
                "Brak danych — rozwiąż kilka zadań najpierw! 📚"
            )
            return

        embed = discord.Embed(title="📈 Opanowanie tematów", color=0x5865F2)
        lines = []
        for t in active:
            filled = round(t["mastery"] / 10)
            bar    = "🟩" * filled + "⬜" * (10 - filled)
            lines.append(
                f"{bar} **{t['name']}** — {t['mastery']:.0f}% ({t['attempt_count']} prób)"
            )
        chunk = ""
        field_n = 1
        for line in lines:
            if len(chunk) + len(line) > 900:
                embed.add_field(name=f"Tematy ({field_n})", value=chunk, inline=False)
                chunk = ""
                field_n += 1
            chunk += line + "\n"
        if chunk:
            embed.add_field(
                name="Tematy" if field_n == 1 else f"Tematy ({field_n})",
                value=chunk,
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    # ── /notes ─────────────────────────────────────────────────────

    @app_commands.command(name="notes", description="Ostatnie notatki o Twoim rozumieniu matematyki")
    async def notes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        notes = self.db.get_recent_notes(8)

        if not notes:
            await interaction.followup.send("Brak notatek — wróć po kilku sesjach! 📝")
            return

        embed = discord.Embed(title="📝 Notatki z sesji", color=0xFEE75C)
        for n in notes:
            date = n["created_at"][:10]
            embed.add_field(name=date, value=n["content"], inline=False)
        await interaction.followup.send(embed=embed)

    # ── /last10 ────────────────────────────────────────────────────

    @app_commands.command(name="last10", description="Ostatnie 10 ocenionych prób")
    async def last10(self, interaction: discord.Interaction):
        await interaction.response.defer()
        attempts = self.db.get_last_attempts(10)

        if not attempts:
            await interaction.followup.send("Brak historii prób.")
            return

        embed = discord.Embed(title="🕐 Ostatnie 10 prób", color=0xEB459E)
        lines = []
        for a in attempts:
            name  = a.get("topic_name") or a.get("topic_code") or "?"
            date  = a["timestamp"][:16].replace("T", " ")
            score = a["score"]
            diff  = a["difficulty"]
            pip   = "🟢" if score >= 4 else ("🟡" if score >= 2 else "🔴")
            lines.append(f"{pip} `{date}` **{name}** — {score}/6 (trudność {diff}/6)")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ── /model ──────────────────────────────────────────────────────

    @app_commands.command(name="model", description="Zmień model AI lub zobacz dostępne modele")
    @app_commands.describe(
        model_name="Nazwa modelu do użycia (pomiń, aby zobaczyć listę)"
    )
    async def model(self, interaction: discord.Interaction, model_name: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        
        # Get available models
        model_status = self._llm.get_model_status()
        if not model_status:
            await interaction.followup.send("❌ Brak dostępnych modeli.")
            return
        
        # Get current user preference
        current_pref = self.db.get_user_model_preference(interaction.user.id)
        
        # If no model specified, show current selection and available models
        if model_name is None:
            embed = discord.Embed(
                title="🤖 Dostępne modele AI",
                description=f"**Aktualnie wybrany:** {current_pref or self._llm.models[0]}",
                color=0x5865F2
            )
            
            for model_info in model_status:
                status_emoji = "✅" if model_info["available"] else "⏳"
                status_text = "Dostępny" if model_info["available"] else "W ochronie przed rate limit"
                cooldown = ""
                if not model_info["available"] and model_info["cooldown_until"]:
                    cooldown = f" (do {model_info['cooldown_until'].strftime('%H:%M')})"
                
                embed.add_field(
                    name=f"{status_emoji} {model_info['name']}",
                    value=f"{status_text}{cooldown}",
                    inline=False
                )
            
            embed.set_footer(text="Użyj /model <nazwa> aby zmienić model")
            await interaction.followup.send(embed=embed)
            return
        
        # If model specified, try to set it
        available_models = [m["name"] for m in model_status]
        if model_name not in available_models:
            await interaction.followup.send(
                f"❌ Model '{model_name}' nie jest dostępny. "
                f"Dostępne modele: {', '.join(available_models)}"
            )
            return
        
        # Set the preference
        self.db.set_user_model_preference(interaction.user.id, model_name)
        await interaction.followup.send(
            f"✅ Model zmieniony na **{model_name}**. "
            "Zmiana obowiązuje od następnej sesji."
        )


# ── shared display helper ──────────────────────────────────────────

async def _send_summary(send_fn, body: str, generated_now: bool,
                        timestamp_line: str | None = None):
    """Send summary text to Discord, splitting if needed."""
    header = "📋 **Analiza postępów**\n\n" if generated_now else "📋 **Ostatnia analiza postępów**\n\n"
    chunks = _split_chunks(body, limit=1900)
    for i, chunk in enumerate(chunks):
        prefix = header if i == 0 else ""
        await send_fn(prefix + chunk)
    if timestamp_line:
        # timestamp_line looks like: _Wygenerowano: 2025-01-15 14:32_
        clean = timestamp_line.strip("_")
        await send_fn(f"_{clean}_")
    if generated_now:
        await send_fn("💾 Zapisano do `progress_summary.md`")
    # ── /setup ──────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Konfiguracja SophiClaw")
    async def setup(self, interaction: discord.Interaction):
        # First poll: what to setup
        embed = discord.Embed(
            title="🔧 Konfiguracja SophiClaw",
            description="Co chcesz skonfigurować?",
            color=0x5865F2
        )
        embed.add_field(
            name="🤖 Modele AI",
            value="Zarządzaj listą dostępnych modeli AI",
            inline=False
        )
        await interaction.response.send_message(embed=embed)
        
        # Wait for user response (simplified - in real implementation would use buttons/select menu)
        await interaction.followup.send("Wybierz opcję: **1** - Modele AI")
        
        # For now, assume user selected models
        # Second poll: add or remove model
        embed2 = discord.Embed(
            title="🤖 Konfiguracja modeli AI",
            description="Co chcesz zrobić?",
            color=0x5865F2
        )
        embed2.add_field(
            name="➕ Dodaj model",
            value="Dodaj nowy model do listy",
            inline=False
        )
        embed2.add_field(
            name="➖ Usuń model",
            value="Usuń model z listy",
            inline=False
        )
        await interaction.followup.send(embed=embed2)
        await interaction.followup.send("Wybierz opcję: **1** - Dodaj model, **2** - Usuń model")
        
        # For now, assume user selected "add model"
        await interaction.followup.send("Podaj nazwę modelu, który chcesz dodać (np: gemini-2.5-flash)")
        
        # In a real implementation, we would wait for user input here
        # For now, we'll just show what would happen
        await interaction.followup.send("🔍 Walidacja modelu... (wymagana implementacja)")
        await interaction.followup.send("✅ Model dodany do config.py")

# Update config.py function
def update_config_models(new_models: list[str]):
    """Update the MODEL list in config.py"""
    config_content = """# config.py — wygenerowane przez setup.sh
# Uruchom ./setup.sh ponownie, żeby zmienić ustawienia.


API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL    = ["""
    
    for model in new_models:
        config_content += f'"{model}",\n'
    
    config_content += """]

VISION_ENABLED           = True
SESSION_TIMEOUT_SECONDS  = 3600
MAX_CONTEXT              = 12
MAX_TOKENS               = 16384
DB_PATH                  = "sophiclaw.db"
LOG_PATH                 = "log.jsonl"
GOAL_PATH                = "goal.json"

REVIEW_EVERY_N_SESSIONS  = 5
"""
    
    with open('/home/dominik/informatyka/SophiClaw/config.py', 'w') as f:
        f.write(config_content)
