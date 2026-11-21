@echo off
REM Odwolania2JSON: interfejs WWW do wgrywania PDF -> http://127.0.0.1:8000
REM Dodatkowe argumenty sa przekazywane dalej, np.:  start_web.bat --port 8080 --llm-mode off
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
    .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
)
start "" http://127.0.0.1:8000
.venv\Scripts\python web.py %*
exit /b %errorlevel%
:error
echo Nie udalo sie przygotowac srodowiska Python 3.13+.
exit /b 1
