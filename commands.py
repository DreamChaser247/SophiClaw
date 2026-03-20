"""
commands.py — SophiClaw slash commands

Registered as a discord.py Cog so they stay out of sophiclaw.py.
Discord will suggest these automatically when users type /.
"""

import discord
from discord import app_commands
from discord.ext import commands


class SophiCommands(commands.Cog):
    """All SophiClaw slash commands in one place."""

    def __init__(self, bot: commands.Bot, db, sessions, run_shadow):
        self.bot        = bot
        self.db         = db
        self._sessions  = sessions      # shared reference to the sessions dict
        self._run_shadow = run_shadow   # coroutine from sophiclaw.py

    # ── /help ──────────────────────────────────────────────────────

    @app_commands.command(name="help", description="Lista komend SophiClaw")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="SophiClaw 🐾 — pomoc",
            description="Wyślij mi pytanie lub zdjęcie zeszytu, a wyjaśnię krok po kroku.",
            color=0x5865F2,
        )
        embed.add_field(name="/help",     value="Ta wiadomość",                        inline=False)
        embed.add_field(name="/summary",  value="Podsumowanie postępów (wszystkie sesje)", inline=False)
        embed.add_field(name="/progress", value="Pasek opanowania każdego tematu",     inline=False)
        embed.add_field(name="/notes",    value="Ostatnie notatki o Twoim rozumieniu", inline=False)
        embed.add_field(name="/last10",   value="Ostatnie 10 ocenionych prób",         inline=False)
        embed.add_field(name="/end",      value="Zakończ sesję i zapisz postępy",      inline=False)
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

    # ── /summary ───────────────────────────────────────────────────

    @app_commands.command(name="summary", description="Podsumowanie Twoich postępów")
    async def summary(self, interaction: discord.Interaction):
        await interaction.response.defer()
        stats = self.db.get_summary_stats()

        embed = discord.Embed(title="📊 Podsumowanie postępów", color=0x57F287)
        embed.add_field(
            name="Ogólne",
            value=(
                f"Łącznie prób: **{stats['total_attempts']}**\n"
                f"Średnia ocena: **{stats['avg_score']:.1f}/6**\n"
                f"Sesji: **{stats['total_sessions']}**"
            ),
            inline=False,
        )
        if stats["strongest_topics"]:
            tops = "\n".join(
                f"• {t['name']} — {t['mastery']:.0f}%"
                for t in stats["strongest_topics"]
            )
            embed.add_field(name="💪 Mocne strony", value=tops, inline=True)
        if stats["weakest_topics"]:
            weak = "\n".join(
                f"• {t['name']} — {t['mastery']:.0f}%"
                for t in stats["weakest_topics"]
            )
            embed.add_field(name="⚠️ Do poprawy", value=weak, inline=True)

        await interaction.followup.send(embed=embed)

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
        # Discord embed value limit is 1024 chars — split if needed
        chunk = ""
        field_n = 1
        for line in lines:
            if len(chunk) + len(line) > 900:
                embed.add_field(name=f"Tematy ({field_n})", value=chunk, inline=False)
                chunk = ""
                field_n += 1
            chunk += line + "\n"
        if chunk:
            embed.add_field(name="Tematy" if field_n == 1 else f"Tematy ({field_n})",
                            value=chunk, inline=False)

        await interaction.followup.send(embed=embed)

    # ── /notes ─────────────────────────────────────────────────────

    @app_commands.command(name="notes", description="Ostatnie notatki o Twoim rozumieniu matematyki")
    async def notes(self, interaction: discord.Interaction):
        await interaction.response.defer()
        notes = self.db.get_recent_notes(8)

        if not notes:
            await interaction.followup.send(
                "Brak notatek — wróć po kilku sesjach! 📝"
            )
            return

        embed = discord.Embed(title="📝 Notatki o postępach", color=0xFEE75C)
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
            name = a.get("topic_name") or a.get("topic_code") or "?"
            date = a["timestamp"][:16].replace("T", " ")
            score = a["score"]
            diff  = a["difficulty"]
            pip   = "🟢" if score >= 4 else ("🟡" if score >= 2 else "🔴")
            lines.append(f"{pip} `{date}` **{name}** — {score}/6 (trudność {diff}/6)")

        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ── /model ────────────────────────────────────────────────────

    @app_commands.command(name="model", description="Pokaż aktualny model i dostępne modele")
    async def model(self, interaction: discord.Interaction):
        """Show current model configuration."""
        await interaction.response.defer(ephemeral=True)
        
        configured_models = getattr(config, "MODEL", ["gemini-3-flash", "gemini-3.1-flash-lite"])
        user_preference = self.db.get_user_model_preference(interaction.user.id)
        
        embed = discord.Embed(
            title="🤖 Aktualny Model",
            description=(
                "Bot używa modeli z automatycznym fallbackiem, jeśli któryś jest niedostępny.\n\n"
                "**Dostępne modele:**"
            ),
            color=0x00FFFF
        )
        
        for i, model in enumerate(configured_models):
            if model == user_preference:
                embed.add_field(name=f"{model} ✓", value="Ustawiony jako preferowany", inline=False)
            else:
                embed.add_field(name=model, value="Dostępny w razie potrzeby", inline=False)
        
        if user_preference:
            embed.set_footer(text=f"Twój preferowany model to: {user_preference}")
        else:
            embed.set_footer(text="Nie masz preferowanego modelu — używamy kolejności z config.py")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
