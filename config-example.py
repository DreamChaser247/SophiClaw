# ╔══════════════════════════════════════════════════════════════════╗
# ║              SophiClaw — configuration template                 ║
# ║  Copy this file to config.py and fill in your values.           ║
# ║  Never commit config.py to git (it contains secrets).           ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── Discord ────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"

# ── LLM Provider ──────────────────────────────────────────────────
# SophiClaw uses any OpenAI-compatible API. Change the three lines
# below to switch providers — nothing else needs to change.
#
# ┌─────────────────────┬────────────────────────────────────────────────────────────────┬──────────────────────────────────┐
# │ Provider            │ API_BASE                                                       │ MODEL (examples)                 │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ Google AI Studio    │ https://generativelanguage.googleapis.com/v1beta/openai/       │ gemini-2.5-flash                 │
# │ (free tier)         │                                                                │ gemini-2.0-flash                 │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ Ollama (local)      │ http://localhost:11434/v1                                      │ llava / llama3.2-vision          │
# │                     │ API_KEY = "ollama"  (any non-empty string)                     │ qwen2.5-math / deepseek-r1       │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ OpenRouter          │ https://openrouter.ai/api/v1                                   │ google/gemini-2.5-flash          │
# │                     │                                                                │ anthropic/claude-sonnet-4-5      │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ Grok (xAI)          │ https://api.x.ai/v1                                            │ grok-2-vision-1212               │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ Groq                │ https://api.groq.com/openai/v1                                 │ meta-llama/llama-4-scout-17b-... │
# ├─────────────────────┼────────────────────────────────────────────────────────────────┼──────────────────────────────────┤
# │ OpenAI              │ https://api.openai.com/v1                                      │ gpt-4o / gpt-4o-mini             │
# └─────────────────────┴────────────────────────────────────────────────────────────────┴──────────────────────────────────┘

API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
API_KEY  = "YOUR_API_KEY_HERE"
MODEL    = "gemini-2.5-flash"

# ── Vision support ─────────────────────────────────────────────────
# Set True if your model can understand images (photos of notebooks).
# If False, the bot will ask students to type their question instead.
VISION_ENABLED = True

# ── Behaviour ──────────────────────────────────────────────────────
SESSION_TIMEOUT_SECONDS = 3600   # new session after 1 h of silence
MAX_CONTEXT             = 12     # how many past turns to keep
DB_PATH                 = "sophiclaw.db"
LOG_PATH                = "log.jsonl"
GOAL_PATH               = "goal.json"
