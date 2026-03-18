@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo.
echo  ==========================================
echo         SophiClaw -- konfiguracja
echo  ==========================================
echo.

:: ── Step 1: Python ────────────────────────────────────────────────
echo [1/5] Sprawdzam Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [BLAD] Python nie jest zainstalowany.
    echo.
    echo  Pobierz ze strony: https://www.python.org/downloads/
    echo  Podczas instalacji zaznacz "Add Python to PATH" ^^!
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER%

:: ── Step 2: venv + deps ───────────────────────────────────────────
echo.
echo [2/5] Srodowisko i zaleznosci...
if not exist ".venv\" (
    echo  Tworze wirtualne srodowisko...
    python -m venv .venv
    if errorlevel 1 ( echo  [BLAD] Nie udalo sie utworzyc venv. & pause & exit /b 1 )
    echo  [OK] Srodowisko utworzone
) else (
    echo  [OK] Srodowisko juz istnieje
)
echo  Instaluje zaleznosci...
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet discord.py aiohttp openai matplotlib
if errorlevel 1 ( echo  [BLAD] Instalacja nie powiodla sie. & pause & exit /b 1 )
echo  [OK] Zaleznosci zainstalowane

:: ── Step 3: Discord token ─────────────────────────────────────────
echo.
echo [3/5] Token bota Discord
echo  ----------------------------------------
echo  Gdzie znalezc token:
echo    1. https://discord.com/developers/applications
echo    2. Stworz aplikacje ^> zakladka "Bot" ^> "Reset Token"
echo  ----------------------------------------
echo.

set EXISTING_TOKEN=
if exist "config.py" (
    for /f "tokens=*" %%l in ('
        .venv\Scripts\python -c "import config; print(config.DISCORD_BOT_TOKEN)" 2^>nul
    ') do set EXISTING_TOKEN=%%l
)

if not "!EXISTING_TOKEN!"=="" (
    set SHORT_TOKEN=!EXISTING_TOKEN:~0,10!
    echo  Obecny token: !SHORT_TOKEN!...
    set /p CHANGE_TOKEN= Zmienic? [t/n]: 
    if /i "!CHANGE_TOKEN!"=="n" (
        set DISCORD_TOKEN=!EXISTING_TOKEN!
        echo  [OK] Token bez zmian
        goto :token_done
    )
)
:token_input
set /p DISCORD_TOKEN= Wklej token bota: 
if "!DISCORD_TOKEN!"=="" ( echo  Token nie moze byc pusty. & goto :token_input )
:token_done

:: ── Step 4: Provider ──────────────────────────────────────────────
echo.
echo [4/5] Model AI
echo  ----------------------------------------
echo   1. Tryb podstawowy   -- Google AI Studio (darmowe, zalecane)
echo   2. Tryb zaawansowany -- wlasny provider
echo  ----------------------------------------
set /p MODE= Wybierz tryb [1]: 
if "!MODE!"=="" set MODE=1

set API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/
set MODEL=gemini-2.5-flash
set VISION_ENABLED=True
set API_KEY=

if "!MODE!"=="1" (
    echo.
    echo  Klucz API Google AI Studio -- calkowicie darmowy.
    echo    https://aistudio.google.com/apikey  (kliknij "Create API key")
    echo.

    set EXISTING_KEY=
    if exist "config.py" (
        for /f "tokens=*" %%l in ('
            .venv\Scripts\python -c "import config; print(config.API_KEY)" 2^>nul
        ') do set EXISTING_KEY=%%l
    )
    if not "!EXISTING_KEY!"=="" (
        set SHORT_KEY=!EXISTING_KEY:~0,8!
        echo  Obecny klucz: !SHORT_KEY!...
        set /p CHANGE_KEY= Zmienic? [t/n]: 
        if /i "!CHANGE_KEY!"=="n" (
            set API_KEY=!EXISTING_KEY!
            echo  [OK] Klucz bez zmian
            goto :key_done
        )
    )
    :key_input
    set /p API_KEY= Wklej klucz API: 
    if "!API_KEY!"=="" ( echo  Klucz nie moze byc pusty. & goto :key_input )
    :key_done

) else (
    echo.
    echo  Wybierz providera:
    echo    1  Google AI Studio    gemini-2.5-flash
    echo    2  Ollama (lokalnie)   llava  [bez klucza]
    echo    3  OpenRouter          google/gemini-2.5-flash
    echo    4  Grok (xAI)          grok-2-vision-1212
    echo    5  Groq                meta-llama/llama-4-scout-17b-16e-instruct
    echo    6  OpenAI              gpt-4o
    echo    7  Wlasny URL
    echo.
    set /p PROVIDER= Provider [1]: 
    if "!PROVIDER!"=="" set PROVIDER=1

    if "!PROVIDER!"=="1" ( set API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/ & set MODEL=gemini-2.5-flash )
    if "!PROVIDER!"=="2" ( set API_BASE=http://localhost:11434/v1 & set MODEL=llava & echo  [INFO] Ollama nie wymaga klucza. )
    if "!PROVIDER!"=="3" ( set API_BASE=https://openrouter.ai/api/v1 & set MODEL=google/gemini-2.5-flash )
    if "!PROVIDER!"=="4" ( set API_BASE=https://api.x.ai/v1 & set MODEL=grok-2-vision-1212 )
    if "!PROVIDER!"=="5" ( set API_BASE=https://api.groq.com/openai/v1 & set MODEL=meta-llama/llama-4-scout-17b-16e-instruct )
    if "!PROVIDER!"=="6" ( set API_BASE=https://api.openai.com/v1 & set MODEL=gpt-4o )
    if "!PROVIDER!"=="7" ( set /p API_BASE= URL API: )

    echo.
    set /p MODEL_INPUT= Model [!MODEL!]: 
    if not "!MODEL_INPUT!"=="" set MODEL=!MODEL_INPUT!

    echo.
    echo  Klucz API (Enter aby pominac -- Ollama i lokalne providery nie wymagaja):
    set /p API_KEY= Klucz API: 

    echo.
    set /p VISION_Q= Czy model obsluguje zdjecia? [t/n]: 
    if /i "!VISION_Q!"=="n" (
        set VISION_ENABLED=False
        echo  [INFO] Uczniowie beda proszeni o opisywanie tekstem.
    )
)

:: ── Step 5: Goal ──────────────────────────────────────────────────
echo.
echo [5/5] Cel nauki (opcjonalne)
echo  ----------------------------------------
echo  Podaj cel ucznia -- SophiClaw bedzie go uwzgledniac w sesjach.
echo  Mozesz pominac i ustawic pozniej uruchamiajac setup.bat ponownie.
echo  ----------------------------------------
echo.

set GOAL_TEXT=
set GOAL_LEVEL=
set GOAL_EXTRA=
if exist "goal.json" (
    for /f "tokens=*" %%l in ('.venv\Scripts\python -c "import json; d=json.load(open(\"goal.json\")); print(d.get(\"goal\",\"\"))" 2^>nul') do set GOAL_TEXT=%%l
    for /f "tokens=*" %%l in ('.venv\Scripts\python -c "import json; d=json.load(open(\"goal.json\")); print(d.get(\"level\",\"\"))" 2^>nul') do set GOAL_LEVEL=%%l
    for /f "tokens=*" %%l in ('.venv\Scripts\python -c "import json; d=json.load(open(\"goal.json\")); print(d.get(\"extra\",\"\"))" 2^>nul') do set GOAL_EXTRA=%%l
)

set /p SET_GOAL= Ustawic/zaktualizowac cel nauki? [t/n]: 
if /i "!SET_GOAL!"=="t" (
    set /p GOAL_TEXT= Cel [!GOAL_TEXT!]: 
    set /p GOAL_LEVEL= Poziom [!GOAL_LEVEL!]: 
    set /p GOAL_EXTRA= Slabe strony / priorytety: 

    .venv\Scripts\python -c "import json; json.dump({'goal':'!GOAL_TEXT!','level':'!GOAL_LEVEL!','extra':'!GOAL_EXTRA!'}, open('goal.json','w'), ensure_ascii=False, indent=2)"
    echo  [OK] Cel zapisany
) else (
    echo  [OK] Pominieto
)

:: ── Write config.py ───────────────────────────────────────────────
(
echo # config.py -- wygenerowane przez setup.bat
echo # Uruchom setup.bat ponownie, zeby zmienic ustawienia.
echo.
echo DISCORD_BOT_TOKEN = "!DISCORD_TOKEN!"
echo.
echo API_BASE = "!API_BASE!"
echo API_KEY  = "!API_KEY!"
echo MODEL    = "!MODEL!"
echo.
echo VISION_ENABLED          = !VISION_ENABLED!
echo SESSION_TIMEOUT_SECONDS = 3600
echo MAX_CONTEXT             = 12
echo DB_PATH                 = "db/sophiclaw.db"
echo LOG_PATH                = "log.jsonl"
echo GOAL_PATH               = "goal.json"
) > config.py

echo.
echo  [OK] config.py zapisany
echo.
echo  ==========================================
echo    Gotowe^^!  Uruchom bota: start.bat
echo  ==========================================
echo.
pause
