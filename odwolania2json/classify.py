"""Klasyfikacja dokumentu: ważone reguły z konfiguracji + model językowy w „szarej strefie”.

Reguła: {pattern: regex, weight: liczba, where: head|any}. `head` = pierwsze linie dokumentu.
- wynik >= `min_score` typu → klasyfikują reguły (pewny przypadek);
- najlepszy wynik w szarej strefie (`llm.classify_min_score` <= wynik < min_score) → rozstrzyga model,
  z jawną opcją „inny” dla dokumentów spoza zakresu (orzeczenia, ogłoszenia, decyzje…);
- brak cech (wynik poniżej szarej strefy) → dokument nierozpoznany, pusty JSON, bez modelu.
Szara strefa to głównie skany, w których OCR zniekształca słowa kluczowe („0 D W 0 Ł A N IE”).
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


def _llm_classify(doc: Document, cfg: Config, scores: dict) -> str | None:
    lcfg = cfg.settings.get("llm", {})
    if (lcfg.get("mode_override") or "fallback") == "off":
        return None
    from .extractors.odwolanie import _llm_client

    client = _llm_client(cfg)
    if not client.available:
        return None
    types = "\n".join(f"- {name}: {dt.raw.get('description', name)}" for name, dt in cfg.doc_types.items())
    text = re.sub(r"\s+", " ", doc.text)[: lcfg.get("classify_max_chars", 3000)]
    ans = client.chat_json(lcfg["classify_system_prompt"],
                           lcfg["classify_user_prompt"].format(types=types, text=text))
    scores["_llm"] = {"odpowiedz": ans}
    if not isinstance(ans, dict):
        return None
    typ = str(ans.get("typ") or "").strip().lower()
    return typ if typ in cfg.doc_types else None  # „inny” / cokolwiek spoza listy → nierozpoznany


def classify(doc: Document, cfg: Config) -> tuple[str | None, dict]:
    scores = score_all(doc, cfg)
    ok = {n: s for n, s in scores.items() if s["score"] >= s["min_score"]}
    if ok:
        return max(ok, key=lambda n: ok[n]["score"]), scores
    gray = cfg.settings.get("llm", {}).get("classify_min_score", 2)
    if max(s["score"] for s in scores.values()) >= gray:
        return _llm_classify(doc, cfg, scores), scores
    return None, scores
