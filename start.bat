@echo off
chcp 65001 >nul

if not exist ".venv\" (
    echo [BLAD] Nie znaleziono .venv — uruchom najpierw setup.bat
    pause
    exit /b 1
)

if not exist "config.py" (
    echo [BLAD] Brak config.py — uruchom najpierw setup.bat
    pause
    exit /b 1
)

:: Check for empty token (simple grep equivalent)
findstr /c:"DISCORD_BOT_TOKEN = \"\"" config.py >nul 2>&1
if not errorlevel 1 (
    echo [BLAD] DISCORD_BOT_TOKEN jest pusty w config.py
    echo        Otworz config.py i uzupelnij token bota Discord.
    pause
    exit /b 1
)

echo Uruchamiam SophiClaw...
.venv\Scripts\python sophiclaw.py

:: If bot crashes, don't close window immediately
if errorlevel 1 (
    echo.
    echo Bot zatrzymal sie z bledem.
    pause
)
