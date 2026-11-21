"""Rejestr ekstraktorów.

`extractor: rules` w YAML używa generycznego silnika (bez kodu).
Inna nazwa ładuje moduł `odwolania2json.extractors.<nazwa>` z funkcją
`extract(doc, doc_type, cfg) -> (wynik: dict, ślad: dict)`.
"""
from __future__ import annotations

import importlib


def get_extractor(name: str):
    mod = importlib.import_module(f"{__name__}.{name}")
    return mod.extract
