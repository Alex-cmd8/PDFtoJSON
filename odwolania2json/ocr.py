"""OCR stron bez warstwy tekstowej (skany) – EasyOCR na CPU.

Strona jest renderowana do obrazu (pypdfium2, zależność pdfplumber), rozpoznawana przez EasyOCR,
a wynik zamieniany na „słowa z pozycją” w układzie współrzędnych PDF – tak samo jak słowa
z warstwy tekstowej. Dzięki temu dalsza ekstrakcja (kolumny, etykiety, sekcje) działa bez zmian.

EasyOCR jest zależnością opcjonalną: bez niej skany dają pusty wynik (z ostrzeżeniem w logu).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger("odwolania2json.ocr")
ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "enabled": True,
    "languages": ["pl"],
    "scale": 3.0,            # 72 dpi * 3 = 216 dpi
    "min_confidence": 0.15,
    "models_dir": "models/easyocr",
    "min_chars_text_layer": 20,  # mniej znaków na stronie = traktujemy jak skan
    "max_pages": 3,          # dane kluczowe są na pierwszych stronach (README UZP); 0 = wszystkie
    "threads": 0,            # wątki CPU dla PyTorch; 0 = wszystkie rdzenie
    "readtext": {},          # parametry detekcji EasyOCR (np. low_text, text_threshold)
}

_reader = None
_unavailable = False


def settings(cfg: dict | None) -> dict:
    return {**DEFAULTS, **(cfg or {})}


def _get_reader(cfg: dict):
    global _reader, _unavailable
    if _reader is not None or _unavailable:
        return _reader
    try:
        import easyocr  # noqa: WPS433 – import opcjonalny
    except ImportError:
        _unavailable = True
        log.warning("EasyOCR nie jest zainstalowany – strony bez tekstu zostaną pominięte "
                    "(pip install -r requirements.txt)")
        return None
    import os
    import torch
    torch.set_num_threads(cfg.get("threads") or os.cpu_count() or 4)
    models = ROOT / cfg["models_dir"]
    models.mkdir(parents=True, exist_ok=True)
    # modele (~100 MB) pobierane przy pierwszym użyciu – chwilowy błąd sieci ponawiamy
    for attempt in range(4):
        try:
            _reader = easyocr.Reader(cfg["languages"], gpu=False, model_storage_directory=str(models),
                                     user_network_directory=str(models), verbose=False)
            return _reader
        except OSError as e:  # URLError, przerwane pobieranie
            if attempt == 3:
                raise
            log.warning("Pobieranie modeli OCR nie powiodło się (%s) – ponawiam", e)
            for part in models.glob("*.zip"):  # niedokończone archiwum
                part.unlink(missing_ok=True)
            time.sleep(5 * (attempt + 1))
    return _reader


def prepare(cfg: dict | None = None) -> bool:
    """Pobiera modele OCR z góry (krok instalacji), żeby pierwsze przetwarzanie nie zależało od sieci."""
    return _get_reader(settings(cfg)) is not None


if __name__ == "__main__":  # python -m odwolania2json.ocr  → pobranie modeli
    import sys
    from .config import load_config

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = prepare(load_config().settings.get("ocr"))
    print("Modele OCR gotowe." if ok else "OCR niedostępny.")
    sys.exit(0 if ok else 1)


def page_words(pdf_path: Path, page_index: int, cfg: dict) -> list[dict]:
    """Słowa strony w formacie zgodnym z pdfplumber.extract_words (x0, x1, top, bottom, text, size).

    Wynik jest cache'owany na dysku (klucz: skrót pliku + strona + ustawienia), więc ponowne
    przetwarzanie tego samego skanu nie powtarza kosztownego OCR.
    """
    import hashlib
    import json

    cache_dir = ROOT / cfg.get("cache_dir", ".ocr_cache")
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:24]
    rt = "".join(f"_{k}{v}" for k, v in sorted(cfg["readtext"].items()))
    key = f"{digest}_p{page_index}_s{cfg['scale']}_c{cfg['min_confidence']}_{'-'.join(cfg['languages'])}{rt}"
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    words = _ocr_page(pdf_path, page_index, cfg)
    if words or _reader is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return words


def _ocr_page(pdf_path: Path, page_index: int, cfg: dict) -> list[dict]:
    reader = _get_reader(cfg)
    if reader is None:
        return []
    import numpy as np
    import pypdfium2 as pdfium

    scale = cfg["scale"]
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        img = pdf[page_index].render(scale=scale).to_pil().convert("RGB")
    finally:
        pdf.close()
    results = reader.readtext(np.array(img), detail=1, paragraph=False, **cfg["readtext"])
    words = []
    for box, text, conf in results:
        text = text.strip()
        if not text or conf < cfg["min_confidence"]:
            continue
        xs = [p[0] / scale for p in box]
        ys = [p[1] / scale for p in box]
        x0, x1, top, bottom = min(xs), max(xs), min(ys), max(ys)
        height = bottom - top
        # EasyOCR zwraca fragmenty linii – dzielimy na słowa proporcjonalnie do liczby znaków
        tokens = text.split()
        total = sum(len(t) for t in tokens) + max(len(tokens) - 1, 0)
        cursor = x0
        for t in tokens:
            w = (x1 - x0) * len(t) / max(total, 1)
            words.append({"text": t, "x0": cursor, "x1": cursor + w, "top": top, "bottom": bottom,
                          "size": height * 0.8, "upright": True, "ocr_conf": float(conf)})
            cursor += w + (x1 - x0) / max(total, 1)
    return words
