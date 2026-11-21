@echo off
REM Odwolania2JSON: przetwarza input\<sprawa>\*.pdf -> output\<sprawa>\*.json
REM Dodatkowe argumenty sa przekazywane dalej, np.:  start.bat --trace trace
setlocal
cd /d "%~dp0"
call :venv || goto :error
REM "start.bat setup" - tylko przygotowanie srodowiska
if /i "%~1"=="setup" exit /b 0
.venv\Scripts\python run.py %*
exit /b %errorlevel%

:venv
if exist .venv\Scripts\python.exe exit /b 0
REM Python 3.13+: najpierw launcher "py", potem "python" z PATH
set "PY="
py -3.13 -c "pass" >nul 2>&1 && set "PY=py -3.13"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 13))" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Wymagany Python 3.13 lub nowszy: https://www.python.org/downloads/
    exit /b 1
)
echo Pierwsze uruchomienie: instalacja zaleznosci (PyTorch CPU, EasyOCR - kilka minut)...
%PY% -m venv .venv || exit /b 1
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt || exit /b 1
echo Pobieranie modeli OCR (~100 MB)...
.venv\Scripts\python -m odwolania2json.ocr
exit /b 0

:error
echo Nie udalo sie przygotowac srodowiska Python 3.13+.
exit /b 1
