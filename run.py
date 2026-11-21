"""Odwołania2JSON – uruchomienie z linii poleceń.

    python run.py                          # ./input -> ./output
    python run.py --input dane --output out --trace trace
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from odwolania2json.config import DEFAULT_CONFIG_DIR, load_config
from odwolania2json.pipeline import run

ROOT = Path(__file__).resolve().parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ekstrakcja danych z dokumentów odwołań KIO do JSON")
    ap.add_argument("--input", default=str(ROOT / "input"))
    ap.add_argument("--output", default=str(ROOT / "output"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_DIR))
    ap.add_argument("--trace", default=None, help="katalog na ślady ekstrakcji (skąd wzięto każdą wartość)")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING if a.quiet else logging.INFO, format="%(message)s")

    cfg = load_config(a.config)
    summary = run(Path(a.input), Path(a.output), cfg, Path(a.trace) if a.trace else None)
    errors = sum(s["error"] for s in summary)
    print(f"Przetworzono {len(summary)} plików PDF, błędów: {errors}. Wyniki: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
