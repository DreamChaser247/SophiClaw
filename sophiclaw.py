"""
sophiclaw.py — SophiClaw Discord math tutor
Run: python sophiclaw.py  (or ./start.sh)
"""

import asyncio
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

import config
import database
import llm
import latex_render
import prompts
from commands import SophiCommands
from review import end_session

# ── Logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-22s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sophiclaw")

# ── Startup validation ─────────────────────────────────────────────

if not getattr(config, "DISCORD_BOT_TOKEN", ""):
    raise SystemExit("❌  DISCORD_BOT_TOKEN is empty in config.py — run ./setup.sh")

# ── Singletons ─────────────────────────────────────────────────────

db = database.Database(getattr(config, "DB_PATH", "db/sophiclaw.db"))
db.connect()

llm_adapter = llm.LLMAdapter(
    base_url=getattr(config, "API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    api_key=getattr(config, "API_KEY", ""),
    model=getattr(config, "MODEL", "gemini-2.5-flash"),
    vision_enabled=getattr(config, "VISION_ENABLED", True),
    max_tokens=getattr(config, "MAX_TOKENS", 8192),
)

SESSION_TIMEOUT = getattr(config, "SESSION_TIMEOUT_SECONDS", 3600)
MAX_CONTEXT     = getattr(config, "MAX_CONTEXT", 12)
LOG_PATH        = Path(getattr(config, "LOG_PATH", "log.jsonl"))
REVIEW_EVERY_N  = getattr(config, "REVIEW_EVERY_N_SESSIONS", 5)

# ── Goal loading ───────────────────────────────────────────────────

def _load_goal() -> str:
    path = Path(getattr(config, "GOAL_PATH", "goal.json"))
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        goal  = data.get("goal", "").strip()
        level = data.get("level", "").strip()
        extra = data.get("extra", "").strip()
        if not goal:
            return ""
        block = "\n=== CEL UCZNIA ===\n"
        if goal:  block += f"Cel: {goal}\n"
        if level: block += f"Poziom: {level}\n"
        if extra: block += f"Dodatkowe info: {extra}\n"
        block += "==================\n"
        return block
    except Exception as e:
        log.warning("Could not load goal.json: %s", e)
        return ""

SYSTEM_PROMPT = prompts.BASE_PROMPT + _load_goal()

# ── Session state ──────────────────────────────────────────────────

_sessions: dict[int, dict] = {}

# Module-level wrappers — defined here so both _get_or_create_session
# and _timeout_checker can reference them without closure tricks.
# They are plain async functions, not closures, so they're safe to call
# from any coroutine in this module.

async def _do_end_session(state: dict, user_id: int) -> None:
    await end_session(db, llm_adapter, state, REVIEW_EVERY_N, user_id)


def _get_or_create_session(user_id: int) -> dict:
    now   = datetime.now(timezone.utc)
    state = _sessions.get(user_id)

    if state:
        idle = (now - state["last_active"]).total_seconds()
        if idle > SESSION_TIMEOUT:
            log.info("Session timeout for user %d", user_id)
            asyncio.create_task(_do_end_session(state, user_id))
            state = None

    if not state:
        sid = str(uuid.uuid4())[:8]
        db.add_session(sid)
        state = {"session_id": sid, "last_active": now, "history": []}
        _sessions[user_id] = state

    state["last_active"] = now
    return state


# ── Logging ────────────────────────────────────────────────────────

def _log(role: str, content: str, session_id: str, has_image: bool = False) -> None:
    entry = {
        "ts":      datetime.now(timezone.utc).isoformat(),
        "session": session_id,
        "role":    role,
        "content": ("[image] " + content) if has_image else content,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Message sending ────────────────────────────────────────────────

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


async def _send_response(message: discord.Message, text: str) -> None:
    first = True

    async def send(content: Optional[str] = None, file: Optional[discord.File] = None):
        nonlocal first
        if first:
            await message.reply(content=content, file=file)
            first = False
        else:
            await message.channel.send(content=content, file=file)

    if not latex_render.has_latex(text):
        for chunk in _split_chunks(text):
            await send(content=chunk)
        return

    parts = latex_render.split_message(text)
    text_buffer = ""

    async def flush_text():
        nonlocal text_buffer
        content = text_buffer.strip()
        text_buffer = ""
        if not content:
            return
        for chunk in _split_chunks(content):
            await send(content=chunk)

    for part in parts:
        if part["type"] == "text":
            text_buffer += part["content"]
        elif part["type"] == "latex":
            await flush_text()
            png = latex_render.render_latex(part["content"])
            if png:
                await send(file=discord.File(
                    fp=io.BytesIO(png),
                    filename="formula.png",
                    description=part["content"][:100],
                ))
            else:
                text_buffer += f"\n`{part['content']}`\n"

    await flush_text()


# ── Bot setup ──────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    # Pass _do_end_session as the run_shadow callable for /end command —
    # it has the right signature: (state) -> None
    await bot.add_cog(SophiCommands(bot, db, _sessions, _do_end_session, llm_adapter))
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash command(s)", len(synced))
    except Exception as e:
        log.warning("Failed to sync slash commands: %s", e)

    vision_note = "uczniowie mogą wysyłać zdjęcia 📸" if llm_adapter.vision_enabled \
                  else "tryb tekstowy (VISION_ENABLED=False)"
    print(f"\n✅  SophiClaw ready — {vision_note}")
    print(f"    Model        : {', '.join(llm_adapter.models)}")
    print(f"    DB           : {db.path}")
    print(f"    Auto-review  : co {REVIEW_EVERY_N} sesji")
    print(f"    Komendy      : /help /setup /model /summarise /summary /progress /notes /last10 /end /restart\n")
    _timeout_checker.start()


@tasks.loop(minutes=5)
async def _timeout_checker() -> None:
    now = datetime.now(timezone.utc)
    stale = [
        (uid, s) for uid, s in list(_sessions.items())
        if (now - s["last_active"]).total_seconds() > SESSION_TIMEOUT
    ]
    for uid, state in stale:
        await _do_end_session(state)   # module-level — always reachable
        del _sessions[uid]


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.content.startswith("/"):
        return

    uid  = message.author.id
    text = message.content.strip()

    state = _get_or_create_session(uid)
    sid   = state["session_id"]
    db.increment_turns(sid)

    images: list[bytes] = []
    has_image = False

    if message.attachments:
        image_atts = [
            a for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ]
        if image_atts:
            if not llm_adapter.vision_enabled:
                await message.reply(
                    "📝 Twój model nie obsługuje zdjęć.\n"
                    "Opisz zadanie tekstem, a chętnie pomogę!"
                )
                return
            async with aiohttp.ClientSession() as http:
                for att in image_atts[:3]:
                    async with http.get(att.url) as resp:
                        if resp.status == 200:
                            images.append(await resp.read())
            has_image = True

    if has_image:
        user_content = llm_adapter.build_image_content(
            text or "Proszę sprawdź moje rozwiązanie ze zdjęcia.", images
        )
    else:
        if not text:
            return
        user_content = text

    state["history"].append({"role": "user", "content": user_content})
    state["history"] = state["history"][-MAX_CONTEXT:]

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + state["history"]

    async with message.channel.typing():
        reply = await llm_adapter.send(msgs, user_id=uid, db=db)

    state["history"].append({"role": "assistant", "content": reply})
    state["history"] = state["history"][-MAX_CONTEXT:]

    _log("user",      text,  sid, has_image=has_image)
    _log("assistant", reply, sid)

    await _send_response(message, reply)
    await bot.process_commands(message)


# ── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_BOT_TOKEN, log_handler=None)
    except discord.errors.PrivilegedIntentsRequired:
        print()
        print("❌  Brak wymaganych uprawnień (Privileged Intents).")
        print("   1. https://discord.com/developers/applications")
        print("   2. Wybierz aplikację → zakładka 'Bot'")
        print("   3. Włącz 'MESSAGE CONTENT INTENT' → Save Changes")
        print("   4. ./start.sh")
        print()
    except discord.errors.LoginFailure:
        print()
        print("❌  Nieprawidłowy token Discord — uruchom ./setup.sh")
        print()