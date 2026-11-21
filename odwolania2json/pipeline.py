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
    return result, trace


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
