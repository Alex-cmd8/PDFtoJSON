#!/usr/bin/env sh
# Odwołania2JSON (Linux/macOS): input/<sprawa>/*.pdf -> output/<sprawa>/*.json
#   ./start.sh                 # przetwarzanie folderu input/
#   ./start.sh web             # interfejs WWW: http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    PY=$(command -v python3.13 || command -v python3 || command -v python)
    "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 13))' || { echo "Wymagany Python 3.13+"; exit 1; }
    echo "Pierwsze uruchomienie: instalacja zależności (PyTorch CPU, EasyOCR – kilka minut)..."
    "$PY" -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -q -r requirements.txt
    echo "Pobieranie modeli OCR (~100 MB)..."
    .venv/bin/python -m odwolania2json.ocr || true
fi
if [ "$1" = "web" ]; then
    shift
    exec .venv/bin/python web.py "$@"
fi
exec .venv/bin/python run.py "$@"
