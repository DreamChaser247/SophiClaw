# SophiClaw 🐾

Local-first Discord math tutor for Polish students.  
Philosophy: **understanding comes before results**.

---

## Quick start

```bash
pip install discord.py aiohttp openai
cp config.example.py config.py   # then edit config.py
python sophiclaw.py
```

## config.py — switching providers

Only three lines change between providers:

| Provider | API_BASE | MODEL |
|---|---|---|
| **Google AI Studio** (default, free) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` |
| **Ollama** (local) | `http://localhost:11434/v1` | `llava` / `llama3.2-vision` |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `google/gemini-2.5-flash` |
| **Grok** (xAI) | `https://api.x.ai/v1` | `grok-2-vision-1212` |
| **Groq** | `https://api.groq.com/openai/v1` | `meta-llama/llama-4-scout-17b-16e-instruct` |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o` |

Set `VISION_ENABLED = False` if your model doesn't support images.

## goal.json (optional)

Create `goal.json` to give SophiClaw context about the student:

```json
{
  "goal": "Przygotowanie do matury rozszerzonej z matematyki (maj 2026).",
  "level": "liceum klasa 3",
  "extra": "Szczególnie słaby z trygonometrii."
}
```

## Commands

| Command | Description |
|---|---|
| `/help` | List all commands |
| `/summary` | Overall progress stats |
| `/progress` | Topic mastery bars |
| `/notes` | Recent LLM notes about understanding |
| `/last10` | Last 10 scored attempts |
| `/end` | End session and save progress |

## File structure

```
sophiclaw.py        main bot
config.py           your settings (never commit)
config.example.py   template
database.py         SQLite layer
llm.py              provider-agnostic LLM adapter
goal.json           student goal (never commit)
sophiclaw.db        local progress database
log.jsonl           conversation log
```
