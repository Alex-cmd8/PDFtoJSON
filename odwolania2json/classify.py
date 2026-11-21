"""Klasyfikacja dokumentu na podstawie ważonych reguł z konfiguracji.

Reguła: {pattern: regex, weight: liczba, where: head|any}. `head` = pierwsze linie dokumentu.
Wygrywa typ z najwyższym wynikiem, o ile przekracza swój `min_score`;
w przeciwnym razie dokument jest nierozpoznany (wynik: pusty JSON).
"""
from __future__ import annotations

import re

from .config import Config
from .pdftext import Document

HEAD_LINES = 8


def score_all(doc: Document, cfg: Config) -> dict[str, dict]:
    head = doc.head(HEAD_LINES)
    body = doc.head(400)
    out = {}
    for name, dt in cfg.doc_types.items():
        c = dt.classify
        total, matched = 0.0, []
        for r in c.get("rules", []):
            text = head if r.get("where") == "head" else body
            if re.search(r["pattern"], text, re.I | re.M):
                total += r.get("weight", 1)
                matched.append(r["pattern"])
        out[name] = {"score": total, "min_score": c.get("min_score", 1), "matched": matched}
    return out


def classify(doc: Document, cfg: Config) -> tuple[str | None, dict]:
    scores = score_all(doc, cfg)
    ok = {n: s for n, s in scores.items() if s["score"] >= s["min_score"]}
    best = max(ok, key=lambda n: ok[n]["score"]) if ok else None
    return best, scores
