#!/usr/bin/env bash
# Przetwarzanie na serwerze oceny: /opt/solution/input/**/*.pdf → /opt/solution/output/**/*.json
# Bez interakcji; kończy się po przetworzeniu wszystkich plików.
set -euo pipefail

SOL="${SOLUTION_DIR:-/opt/solution}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
IN="${O2J_INPUT:-$SOL/input}"
OUT="${O2J_OUTPUT:-$SOL/output}"
TRACE="${O2J_TRACE:-$SOL/trace}"     # ślad ekstrakcji (skąd pochodzi każda wartość) – poza output/

# klucz API modelu językowego (Mistral AI, UE)
if [ -f "$SOL/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$SOL/.env"
    set +a
fi

mkdir -p "$OUT"
cd "$REPO"
start=$(date +%s)
.venv/bin/python run.py --input "$IN" --output "$OUT" --trace "$TRACE" -q
echo "Czas: $(( $(date +%s) - start )) s. Wyniki: $OUT"
