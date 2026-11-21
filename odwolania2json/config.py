"""Ładowanie konfiguracji typów dokumentów (jeden plik YAML = jeden typ)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass
class DocType:
    name: str
    raw: dict
    path: Path

    @property
    def extractor(self) -> str:
        return self.raw.get("extractor", "rules")

    @property
    def fields(self) -> dict:
        return self.raw.get("fields", {})

    @property
    def classify(self) -> dict:
        return self.raw.get("classify", {})


@dataclass
class Config:
    doc_types: dict[str, DocType]
    settings: dict = field(default_factory=dict)
    dictionaries: dict = field(default_factory=dict)


def load_config(config_dir: str | Path = DEFAULT_CONFIG_DIR) -> Config:
    config_dir = Path(config_dir)
    types = {}
    for f in sorted((config_dir / "document_types").glob("*.y*ml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if raw.get("enabled", True):
            types[raw["name"]] = DocType(raw["name"], raw, f)
    settings_file = config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
    settings = settings or {}
    llm_file = config_dir / "llm.yaml"
    if llm_file.exists():
        settings["llm"] = yaml.safe_load(llm_file.read_text(encoding="utf-8")) or {}
    ocr_file = config_dir / "ocr.yaml"
    if ocr_file.exists():
        settings["ocr"] = yaml.safe_load(ocr_file.read_text(encoding="utf-8")) or {}
    dicts = {}
    for f in sorted((config_dir / "dictionaries").glob("*.y*ml")) if (config_dir / "dictionaries").exists() else []:
        dicts[f.stem] = yaml.safe_load(f.read_text(encoding="utf-8"))
    return Config(types, settings or {}, dicts)
