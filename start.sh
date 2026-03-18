#!/usr/bin/env bash
# SophiClaw — uruchom bota
set -e

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "❌  Nie znaleziono .venv — uruchom najpierw: ./setup.sh"
    exit 1
fi

if [ ! -f "config.py" ]; then
    echo "❌  Brak config.py — uruchom najpierw: ./setup.sh"
    exit 1
fi

# Check for empty tokens
if grep -q 'DISCORD_BOT_TOKEN = ""' config.py; then
    echo "❌  DISCORD_BOT_TOKEN jest pusty w config.py"
    echo "    Otwórz config.py i uzupełnij token bota Discord."
    exit 1
fi

echo "🐾  Uruchamiam SophiClaw..."
"$VENV_DIR/bin/python" sophiclaw.py
