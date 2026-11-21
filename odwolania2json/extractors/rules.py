"""Ekstraktor generyczny: pola z YAML + szablon wyjścia z YAML."""
from __future__ import annotations

import re

from ..engine import Engine


def render(template, values: dict):
    """Podstawia {pole} w szablonie; '{pole}' jako cała wartość zachowuje typ (liczba, null)."""
    if isinstance(template, dict):
        return {k: render(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, values) for v in template]
    if isinstance(template, str):
        if m := re.fullmatch(r"\{(\w+)\}", template):
            return values.get(m.group(1))
        return template.format(**values)
    return template


def extract(doc, doc_type, cfg):
    engine = Engine(doc_type.fields, doc_type.raw.get("stop_labels"))
    hits = engine.extract_all(doc)
    values = {k: h.value for k, h in hits.items()}
    return render(doc_type.raw["output"], values), {k: h.trace() for k, h in hits.items()}
