import discord
import aiohttp
import asyncio
import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import config
import database
import llm
import prompts

class SophiClaw(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.llm_adapter = llm.LLMAdapter(
            base_url=config.API_BASE,
            api_key=config.API_KEY,
            model=config.MODEL,
            vision_enabled=config.VISION_ENABLED
        )
        self.db = database.Database(config.DB_PATH)
        self.sessions = {}
        self.goal = self._load_goal()

    def _load_goal(self) -> Optional[Dict[str, str]]:
        try:
            with open(config.GOAL_PATH, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _build_system_prompt(self) -> str:
        base = prompts.BASE_PROMPT
        if self.goal:
            goal_block = f"""
=== CEL UCZNIA ===
Cel: {self.goal.get('goal', '')}
Poziom: {self.goal.get('level', '')}
Dodatkowe info: {self.goal.get('extra', '')}
==================
"""
            return base + goal_block
        return base

    async def on_ready(self):
        print("SophiClaw ready — uczniowie mogą wysyłać zdjęcia zeszytów!" if config.VISION_ENABLED else "SophiClaw ready — tryb tekstowy (vision wyłączone)")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        user_id = str(message.author.id)
        if user_id not in self.sessions or (datetime.now().timestamp() - self.sessions[user_id]['last_activity']) > config.SESSION_TIMEOUT_SECONDS:
            self.sessions[user_id] = {
                'last_activity': datetime.now().timestamp(),
                'session_id': self.db.add_session(user_id, int(datetime.now().timestamp())),
                'messages': []
            }

        self.sessions[user_id]['last_activity'] = datetime.now().timestamp()
        session = self.sessions[user_id]

        if message.content.startswith('/'):
            await self._handle_command(message, session)
            return

        images = []
        if message.attachments:
            if not config.VISION_ENABLED:
                await message.reply("Twój aktualnie skonfigurowany model nie obsługuje zdjęć. Opisz zadanie tekstem, a chętnie pomogę! 📝")
                return
            for attachment in message.attachments:
                if attachment.content_type.startswith('image/'):
                    async with aiohttp.ClientSession() as http_session:
                        async with http_session.get(attachment.url) as resp:
                            images.append(await resp.read())

        content = message.content
        if images:
            content = llm.LLMAdapter.build_image_content(content, images)
        else:
            content = [{"type": "text", "text": content}]

        system_prompt = self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + session['messages'][-config.MAX_CONTEXT:] + [{"role": "user", "content": content}]

        response = await self.llm_adapter.send(messages)
        await message.reply(response)

        session['messages'].append({"role": "user", "content": content})
        session['messages'].append({"role": "assistant", "content": response})

        with open(config.LOG_PATH, 'a') as f:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "content": content,
                "response": response,
                "session_id": session['session_id']
            }
            f.write(json.dumps(log_entry) + '\n')

    async def _handle_command(self, message: discord.Message, session: Dict[str, Any]):
        if message.content.startswith('/end'):
            await self._end_session(message, session)
        elif message.content.startswith('/summary'):
            await self._send_summary(message, session)
        elif message.content.startswith('/notes'):
            await self._send_notes(message, session)
        elif message.content.startswith('/progress'):
            await self._send_progress(message, session)

    async def _end_session(self, message: discord.Message, session: Dict[str, Any]):
        self.db.end_session(session['session_id'], int(datetime.now().timestamp()))

        shadow_messages = [{"role": "system", "content": self._build_system_prompt()}] + session['messages']
        shadow1 = await self.llm_adapter.send_shadow([{"role": "system", "content": "Przeanalizuj tę sesję matematyczną. Zwróć TYLKO tablicę JSON:\n[{\"topic\": \"...\", \"difficulty\": 1-6, \"score\": 0-6}]\nUwzględnij zadania ze zdjęć, jeśli były przesłane."}] + shadow_messages)
        shadow2 = await self.llm_adapter.send_shadow([{"role": "system", "content": "Napisz 1-2 zdania po polsku o tym, jak uczeń rozumie materiał z tej sesji.\nSkup się na rozumieniu konceptów i typowych błędach w rozumowaniu."}] + shadow_messages)

        try:
            attempts = json.loads(shadow1)
            for attempt in attempts:
                self.db.add_attempt(session['session_id'], attempt['topic'], attempt['difficulty'], attempt['score'])
        except json.JSONDecodeError:
            print("Warning: Failed to parse shadow prompt 1 JSON")

        self.db.add_note(session['session_id'], shadow2)
        del self.sessions[str(message.author.id)]
        await message.reply("Sesja zakończona. Dziękuję za naukę! 📚")

    async def _send_summary(self, message: discord.Message, session: Dict[str, Any]):
        notes = self.db.get_session_notes(session['session_id'])
        attempts = self.db.get_session_attempts(session['session_id'])
        summary = "Podsumowanie sesji:\n"
        if notes:
            summary += "\nNotatki:\n" + "\n".join(notes) + "\n"
        if attempts:
            summary += "\nPróby:\n" + "\n".join([f"{a['topic']}: trudność {a['difficulty']}, wynik {a['score']}" for a in attempts])
        await message.reply(summary)

    async def _send_notes(self, message: discord.Message, session: Dict[str, Any]):
        notes = self.db.get_session_notes(session['session_id'])
        if notes:
            await message.reply("\n".join(notes))
        else:
            await message.reply("Brak notatek dla tej sesji.")

    async def _send_progress(self, message: discord.Message, session: Dict[str, Any]):
        attempts = self.db.get_session_attempts(session['session_id'])
        if attempts:
            avg_score = sum(a['score'] for a in attempts) / len(attempts)
            avg_difficulty = sum(a['difficulty'] for a in attempts) / len(attempts)
            progress = f"Postęp: średni wynik {avg_score:.1f}, średnia trudność {avg_difficulty:.1f}"
            await message.reply(progress)
        else:
            await message.reply("Brak danych o postępie dla tej sesji.")

if __name__ == "__main__":
    client = SophiClaw()
    try:
        client.run(config.DISCORD_BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print()
        print("❌  Brak wymaganych uprawnień (Privileged Intents).")
        print()
        print("   Jak to naprawić (zajmuje ~1 minutę):")
        print("   1. Otwórz https://discord.com/developers/applications")
        print("   2. Wybierz swoją aplikację → zakładka 'Bot'")
        print("   3. Włącz 'MESSAGE CONTENT INTENT'")
        print("   4. Kliknij 'Save Changes'")
        print("   5. Uruchom bota ponownie: ./start.sh")
        print()
    except discord.errors.LoginFailure:
        print()
        print("❌  Nieprawidłowy token Discord.")
        print("   Uruchom ./setup.sh i podaj poprawny token.")
        print()