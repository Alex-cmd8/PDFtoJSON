@echo off
REM Odwolania2JSON: interfejs WWW do wgrywania PDF -> http://127.0.0.1:8000
REM Dodatkowe argumenty sa przekazywane dalej, np.:  start_web.bat --llm-mode off
setlocal
cd /d "%~dp0"
REM srodowisko (Python 3.13, zaleznosci) przygotowuje start.bat
call start.bat setup || exit /b 1
start "" http://127.0.0.1:8000
.venv\Scripts\python web.py %*
exit /b %errorlevel%
