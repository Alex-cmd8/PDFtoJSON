#!/usr/bin/env bash
# Instalacja Odwołania2JSON na serwerze oceny (Ubuntu 24.04, bez GPU) – jednorazowo, przed oceną.
#
#   cd /opt/solution && git clone https://github.com/Alex-cmd8/PDFtoJSON.git repo
#   bash /opt/solution/repo/deploy/setup_vm.sh
#
# Wszystko (Python 3.13, zależności, modele) trafia do /opt/solution/repo; potem przetwarzanie
# nie pobiera niczego poza zapytaniami do API modelu językowego.
set -euo pipefail

SOL="${SOLUTION_DIR:-/opt/solution}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "== [1/5] Pakiety systemowe: Tesseract OCR z językiem polskim"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tesseract-ocr tesseract-ocr-pol python3-venv >/dev/null
tesseract --version | head -1

echo "== [2/5] Python 3.13 i zależności (uv – menedżer wersji Pythona, licencja MIT/Apache 2.0)"
if [ ! -x .tools/bin/uv ]; then
    python3 -m venv .tools
    .tools/bin/pip install -q uv
fi
export UV_PYTHON_INSTALL_DIR="$REPO/.python"   # interpreter wewnątrz projektu
.tools/bin/uv python install 3.13
rm -rf .venv
.tools/bin/uv venv -q --python 3.13 .venv
.tools/bin/uv pip install -q --python .venv/bin/python -r requirements.txt
.venv/bin/python --version

echo "== [3/5] OCR: sprawdzenie Tesseracta i modelu języka polskiego"
.venv/bin/python -m odwolania2json.ocr

echo "== [4/5] $SOL/RUN.md, katalogi input/ i output/"
mkdir -p "$SOL/input" "$SOL/output"
sed "s#__REPO__#$REPO#g; s#__SOL__#$SOL#g" deploy/RUN.md > "$SOL/RUN.md"
chmod +x deploy/run.sh
if [ -f "$SOL/.env" ] && grep -q '^MISTRAL_API_KEY=.\+' "$SOL/.env"; then
    echo "Klucz API: $SOL/.env – OK"
else
    echo "UWAGA: brak MISTRAL_API_KEY w $SOL/.env – bez niego działają same reguły (bez modelu językowego)."
    echo "       Utwórz plik:  echo 'MISTRAL_API_KEY=...' > $SOL/.env && chmod 600 $SOL/.env"
fi

echo "== [5/5] Test na przykładzie organizatorów (szablon-aplikacja) – bez zmiany $SOL/input i output"
TEST_OUT="$(mktemp -d)"
O2J_INPUT="$REPO/szablon-aplikacja/input" O2J_OUTPUT="$TEST_OUT" O2J_TRACE="$TEST_OUT/../o2j_test_trace" \
    sudo -E bash deploy/run.sh
ls -R "$TEST_OUT"
NEG="$TEST_OUT/case1/negatywny przyklad.json"
ODW="$TEST_OUT/case1/przyklad odwolanie.json"
if [ "$(cat "$NEG")" = "{}" ] && grep -q '"OdwolanieKIO"' "$ODW"; then
    echo "TEST OK: negatyw → {}, odwołanie rozpoznane."
else
    echo "TEST NIEUDANY – sprawdź wynik powyżej."; exit 1
fi
sudo rm -rf "$TEST_OUT" "$TEST_OUT/../o2j_test_trace"
echo
echo "Gotowe. Komenda oceny (z $SOL/RUN.md):  sudo bash $REPO/deploy/run.sh"
