@echo off
REM ============================================================
REM  RTO Scraper Agent — Daily Launcher Script
REM  Loads credentials from .env and runs the scraper.
REM  Scheduled via Windows Task Scheduler.
REM ============================================================

cd /d "%~dp0"

if not exist "logs" mkdir logs

for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "%%a=%%b"
)

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set LOGDATE=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

echo [%LOGDATE% %time%] Starting scraper run... >> logs\run_log.txt

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe scraper.py >> "logs\run_%LOGDATE%.log" 2>&1
) else (
    python scraper.py >> "logs\run_%LOGDATE%.log" 2>&1
)

echo [%LOGDATE% %time%] Scraper run completed (exit code: %ERRORLEVEL%) >> logs\run_log.txt
