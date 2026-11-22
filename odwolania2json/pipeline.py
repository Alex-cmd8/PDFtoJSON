"""Przetwarzanie: input/<sprawa>/*.pdf  →  output/<sprawa>/<nazwa>.json"""
from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

from .classify import classify
from .config import Config
from .extractors import get_extractor
from .pdftext import load_pdf

log = logging.getLogger("odwolania2json")


def process_pdf(pdf: Path, cfg: Config) -> tuple[dict, dict]:
    """Zwraca (wynik JSON, ślad ekstrakcji)."""
    doc = load_pdf(pdf, cfg.settings.get("ocr"))
    doc_type, scores = classify(doc, cfg)
    trace = {"file": str(pdf), "doc_type": doc_type, "classification": scores, "fields": {},
             "ocr_pages": getattr(doc, "ocr_pages", 0)}
    if doc_type is None:
        return {}, trace
    dt = cfg.doc_types[doc_type]
    result, field_trace = get_extractor(dt.extractor)(doc, dt, cfg)
    trace["fields"] = field_trace
    # pola puste po ścisłych regułach → model językowy (tylko z oparciem w tekście)
    from .llm_fill import fill
    result = fill(result, doc, dt, cfg, trace)
    if getattr(doc, "ocr_pages", 0):
        result = _ocr_corrections(result, dt.raw.get("ocr_corrections") or [], trace)
    return result, trace


def _ocr_corrections(result: dict, rules: list, trace: dict) -> dict:
    """Poprawki znanych zniekształceń OCR (konfiguracja `ocr_corrections` w YAML typu)."""
    from .llm_fill import _get, _set
    for r in rules:
        v = _get(result, r["path"])
        if r["kind"] == "leading_minus_as_2" and isinstance(v, (int, float)):
            known = {float(k) for k in r["known"]}
            s = f"{v:.2f}"
            if v not in known and s.startswith("2") and len(s) > 4 and float(s[1:]) in known:
                _set(result, r["path"], float(s[1:]))
                trace.setdefault("ocr_corrections", []).append({r["path"]: [v, float(s[1:])]})
    return result


def environment_warnings(cfg: Config) -> list[str]:
    """Czego brakuje do pełnej jakości (wypisywane przy starcie – brak nie zatrzymuje programu)."""
    import os

    out = []
    lcfg = cfg.settings.get("llm", {})
    key = lcfg.get("api_key_env", "MISTRAL_API_KEY")
    if lcfg.get("mode_override") != "off" and not os.environ.get(key) and not lcfg.get("allow_anonymous"):
        out.append(f"Brak klucza API ({key} w pliku .env) – model językowy wyłączony, działają same reguły. "
                   "Skany i nietypowe sformułowania będą miały mniej uzupełnionych pól.")
    ocfg = cfg.settings.get("ocr", {})
    if ocfg.get("enabled", True):
        from . import ocr

        if not ocr.available(ocfg):
            eng = ocr.settings(ocfg)["engine"]
            how = ("Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-pol; Windows: winget install "
                   "UB-Mannheim.TesseractOCR" if eng == "tesseract" else "pip install -r requirements.txt")
            out.append(f"OCR ({eng}) niedostępny – skany (PDF bez warstwy tekstowej) dadzą pusty wynik. {how}")
    return out


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(input_dir: Path, output_dir: Path, cfg: Config, trace_dir: Path | None = None) -> list[dict]:
    summary = []
    pdfs = sorted(p for p in input_dir.rglob("*") if p.suffix.lower() == ".pdf")
    for pdf in pdfs:
        rel = pdf.relative_to(input_dir).with_suffix(".json")
        try:
            result, trace = process_pdf(pdf, cfg)
        except Exception as e:  # jeden zły plik nie zatrzymuje całej partii
            log.error("Błąd przetwarzania %s: %s", pdf, e)
            result, trace = {}, {"file": str(pdf), "error": traceback.format_exc()}
        _write_json(output_dir / rel, result)
        if trace_dir:
            _write_json(trace_dir / rel, trace)
        summary.append({"file": str(rel), "doc_type": trace.get("doc_type"), "error": "error" in trace})
        log.info("%-60s -> %s", rel, trace.get("doc_type"))
    return summary
