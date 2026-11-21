@echo off
REM Odwolania2JSON: przetwarza input\<sprawa>\*.pdf -> output\<sprawa>\*.json
REM Dodatkowe argumenty sa przekazywane dalej, np.:  start.bat --trace trace
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
    .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
)
.venv\Scripts\python run.py %*
exit /b %errorlevel%
:error
echo Nie udalo sie przygotowac srodowiska Python 3.13+.
exit /b 1
