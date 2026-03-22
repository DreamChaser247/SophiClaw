#!/usr/bin/env bash
# SophiClaw — setup & onboarding
# Run any time: first install, changing provider, or updating config.
set -e

VENV_DIR=".venv"
CONFIG_FILE="config.py"
CONFIG_EXAMPLE="config-example.py"
GOAL_FILE="goal.json"

# ── Colours ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️   $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; }
hr()   { echo -e "${CYAN}────────────────────────────────────────────${RESET}"; }

ask() {
    local prompt="$1" default="$2"
    if [ -n "$default" ]; then
        echo -ne "${BOLD}$prompt${RESET} ${CYAN}[$default]${RESET}: "
    else
        echo -ne "${BOLD}$prompt${RESET}: "
    fi
    read -r input
    REPLY="${input:-$default}"
}

confirm() {
    echo -ne "${BOLD}$1${RESET} ${CYAN}[t/n]${RESET}: "
    read -r yn
    [[ "$yn" =~ ^[TtYy] ]]
}

# ═══════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║        SophiClaw — konfiguracja          ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── Step 1: Python check ───────────────────────────────────────────
hr
echo -e "${BOLD}Krok 1/5 — Python${RESET}"
hr

if ! command -v python3 &>/dev/null; then
    err "Python3 nie jest zainstalowany."
    echo ""
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv"
    echo "  Arch:           sudo pacman -S python"
    echo "  Fedora:         sudo dnf install python3"
    echo ""
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER"

# ── Step 2: venv + deps ────────────────────────────────────────────
hr
echo -e "${BOLD}Krok 2/5 — Środowisko i zależności${RESET}"
hr

if [ ! -d "$VENV_DIR" ]; then
    info "Tworzę wirtualne środowisko..."
    python3 -m venv "$VENV_DIR"
    ok "Środowisko utworzone"
else
    ok "Środowisko już istnieje"
fi

info "Aktualizuję zależności..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet discord.py aiohttp openai matplotlib
ok "Zależności zainstalowane"

# ── Step 3: Discord token ──────────────────────────────────────────
hr
echo -e "${BOLD}Krok 3/5 — Token bota Discord${RESET}"
hr
echo ""
echo "  Gdzie znaleźć token:"
echo "    1. Otwórz https://discord.com/developers/applications"
echo "    2. Utwórz aplikację → zakładka 'Bot' → 'Reset Token'"
echo ""

EXISTING_TOKEN=""
if [ -f "$CONFIG_FILE" ]; then
    EXISTING_TOKEN=$(python3 -c "import config; print(config.DISCORD_BOT_TOKEN)" 2>/dev/null || true)
fi

if [ -n "$EXISTING_TOKEN" ]; then
    warn "Obecny token: ${EXISTING_TOKEN:0:10}..."
    if ! confirm "Zmienić?"; then
        DISCORD_TOKEN="$EXISTING_TOKEN"
        ok "Token bez zmian"
    else
        DISCORD_TOKEN=""
    fi
fi

if [ -z "$DISCORD_TOKEN" ]; then
    while true; do
        ask "Wklej token bota"
        DISCORD_TOKEN="$REPLY"
        [ -n "$DISCORD_TOKEN" ] && break
        warn "Token nie może być pusty."
    done
fi

# ── Step 4: Provider ───────────────────────────────────────────────
hr
echo -e "${BOLD}Krok 4/5 — Model AI${RESET}"
hr
echo ""
echo "  ${BOLD}1. Tryb podstawowy${RESET}   — Google AI Studio (darmowe, zalecane)"
echo "  ${BOLD}2. Tryb zaawansowany${RESET} — własny provider (Ollama, OpenRouter, Grok...)"
echo ""
ask "Wybierz tryb" "1"
MODE="$REPLY"

# Defaults
API_BASE="https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL="gemini-2.5-flash"
VISION_ENABLED="True"
API_KEY=""

# Load existing values
if [ -f "$CONFIG_FILE" ]; then
    EXISTING_KEY=$(python3 -c "import config; print(config.API_KEY)" 2>/dev/null || true)
    EXISTING_BASE=$(python3 -c "import config; print(config.API_BASE)" 2>/dev/null || true)
    EXISTING_MODEL=$(python3 -c "import config; print(config.MODEL)" 2>/dev/null || true)
fi

if [ "$MODE" = "1" ]; then
    echo ""
    echo "  Klucz API Google AI Studio — całkowicie darmowy."
    echo "    → https://aistudio.google.com/apikey  (kliknij 'Create API key')"
    echo ""

    if [ -n "$EXISTING_KEY" ]; then
        warn "Obecny klucz: ${EXISTING_KEY:0:8}..."
        if ! confirm "Zmienić?"; then
            API_KEY="$EXISTING_KEY"
            ok "Klucz bez zmian"
        fi
    fi

    if [ -z "$API_KEY" ]; then
        while true; do
            ask "Wklej klucz API"
            API_KEY="$REPLY"
            [ -n "$API_KEY" ] && break
            warn "Klucz nie może być pusty."
        done
    fi

else
    echo ""
    echo "  Wybierz providera:"
    echo "    ${BOLD}1${RESET}  Google AI Studio    gemini-2.5-flash"
    echo "    ${BOLD}2${RESET}  Ollama (lokalnie)   llava / llama3.2-vision  [bez klucza]"
    echo "    ${BOLD}3${RESET}  OpenRouter          google/gemini-2.5-flash"
    echo "    ${BOLD}4${RESET}  Grok (xAI)          grok-2-vision-1212"
    echo "    ${BOLD}5${RESET}  Groq                meta-llama/llama-4-scout-17b-16e-instruct"
    echo "    ${BOLD}6${RESET}  OpenAI              gpt-4o"
    echo "    ${BOLD}7${RESET}  Własny URL"
    echo ""
    ask "Provider" "1"

    case "$REPLY" in
        1) API_BASE="https://generativelanguage.googleapis.com/v1beta/openai/"; MODEL="gemini-2.5-flash" ;;
        2) API_BASE="http://localhost:11434/v1"; MODEL="llava"
           info "Ollama nie wymaga klucza API." ;;
        3) API_BASE="https://openrouter.ai/api/v1"; MODEL="google/gemini-2.5-flash" ;;
        4) API_BASE="https://api.x.ai/v1"; MODEL="grok-2-vision-1212" ;;
        5) API_BASE="https://api.groq.com/openai/v1"; MODEL="meta-llama/llama-4-scout-17b-16e-instruct" ;;
        6) API_BASE="https://api.openai.com/v1"; MODEL="gpt-4o" ;;
        7) ask "URL API" "${EXISTING_BASE:-}"
           API_BASE="$REPLY" ;;
    esac

    echo ""
    ask "Model" "$MODEL"
    MODEL="$REPLY"

    echo ""
    echo "  Klucz API (Enter aby pominąć — Ollama i lokalne providery nie wymagają):"
    ask "Klucz API" ""
    API_KEY="$REPLY"

    echo ""
    if confirm "Czy model obsługuje zdjęcia (vision)?"; then
        VISION_ENABLED="True"
    else
        VISION_ENABLED="False"
        info "Uczniowie będą proszeni o opisywanie zadań tekstem."
    fi
fi

# ── Step 5: Goal ───────────────────────────────────────────────────
GOAL_TEXT=""; GOAL_LEVEL=""; GOAL_EXTRA=""
if [ -f "$GOAL_FILE" ]; then
    GOAL_TEXT=$(python3 -c "import json; d=json.load(open('$GOAL_FILE')); print(d.get('goal',''))" 2>/dev/null || true)
    GOAL_LEVEL=$(python3 -c "import json; d=json.load(open('$GOAL_FILE')); print(d.get('level',''))" 2>/dev/null || true)
    GOAL_EXTRA=$(python3 -c "import json; d=json.load(open('$GOAL_FILE')); print(d.get('extra',''))" 2>/dev/null || true)
fi
hr
echo -e "${BOLD}Krok 5/5 — Cel nauki (opcjonalne)${RESET}"
hr
echo ""
echo "  Podaj cel ucznia — SophiClaw będzie go uwzględniać w każdej odpowiedzi."
echo "  Możesz to pominąć i uzupełnić później uruchamiając setup.sh ponownie."
echo "  Obecny cel to: ""$GOAL_TEXT"
echo ""

if confirm "Ustawić/zaktualizować cel nauki?"; then
    ask "Cel (np. 'Matura rozszerzona maj 2026')" "$GOAL_TEXT"
    GOAL_TEXT="$REPLY"
    ask "Poziom (np. 'liceum klasa 3')" "$GOAL_LEVEL"
    GOAL_LEVEL="$REPLY"
    ask "Słabe strony / priorytety (opcjonalne)" "$GOAL_EXTRA"
    GOAL_EXTRA="$REPLY"

    python3 -c "
import json
d = {'goal': '''$GOAL_TEXT''', 'level': '''$GOAL_LEVEL''', 'extra': '''$GOAL_EXTRA'''}
json.dump(d, open('$GOAL_FILE', 'w'), ensure_ascii=False, indent=2)
"
    ok "Cel zapisany"
else
    ok "Pominięto"
fi

# ── Write config.py ────────────────────────────────────────────────
cat > "$CONFIG_FILE" <<EOF
# config.py — wygenerowane przez setup.sh
# Uruchom ./setup.sh ponownie, żeby zmienić ustawienia.

DISCORD_BOT_TOKEN = "$DISCORD_TOKEN"

API_BASE = "$API_BASE"
API_KEY  = "$API_KEY"
MODEL    = "$MODEL"

VISION_ENABLED           = $VISION_ENABLED
SESSION_TIMEOUT_SECONDS  = 3600
MAX_CONTEXT              = 12
MAX_TOKENS               = 16384
DB_PATH                  = "db/sophiclaw.db"
LOG_PATH                 = "log.jsonl"
GOAL_PATH                = "goal.json"

REVIEW_EVERY_N_SESSIONS  = 5
EOF

ok "config.py zapisany"

# ── Validate: ensure config.py has all vars from config-example.py ─
hr
echo -e "${BOLD}Weryfikacja config.py${RESET}"
hr

if [ -f "$CONFIG_EXAMPLE" ] && [ -f "$CONFIG_FILE" ]; then
    python3 - <<'PYEOF'
import re, sys

def extract_vars(path):
    """Return dict of {varname: full_line} for all top-level assignments."""
    vars_ = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^([A-Z_][A-Z0-9_]*)\s*=', line)
            if m:
                vars_[m.group(1)] = line.rstrip()
    return vars_

example_vars = extract_vars("config-example.py")
config_vars  = extract_vars("config.py")

missing = {k: v for k, v in example_vars.items() if k not in config_vars}

if not missing:
    print("✅  config.py zawiera wszystkie wymagane zmienne")
    sys.exit(0)

print(f"⚠️   Dodaję brakujące zmienne do config.py: {', '.join(missing)}")
with open("config.py", "a", encoding="utf-8") as f:
    f.write("\n# Dodane automatycznie przez setup.sh\n")
    for name, line in missing.items():
        f.write(line + "\n")
print("✅  config.py zaktualizowany")
PYEOF
else
    warn "Nie znaleziono config-example.py — pomijam weryfikację zmiennych"
fi

# ── Done ───────────────────────────────────────────────────────────
echo ""
hr
echo -e "${GREEN}${BOLD}  Gotowe!  Uruchom bota: ./start.sh${RESET}"
hr
echo ""