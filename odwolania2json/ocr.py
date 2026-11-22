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
    "engine": "easyocr",     # easyocr | tesseract
    "tesseract": {           # silnik Tesseract (Apache 2.0): program systemowy + model języka
        "cmd": None,         # None = z PATH albo domyślna ścieżka instalacji Windows
        "tessdata_dir": "models/tessdata",  # gdy brak katalogu – modele systemowe
        "lang": "pol",
        "psm": 3,            # automatyczny podział strony na bloki
        "scale": 4.0,        # 72 dpi * 4 ≈ 300 dpi (zalecane dla Tesseracta)
        "min_conf": 10,      # 0–100
    },
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
    """Przygotowuje silnik OCR z góry (krok instalacji): pobiera modele EasyOCR albo sprawdza Tesseracta."""
    global _tess
    cfg = settings(cfg)
    if cfg["engine"] == "tesseract":
        if _tesseract(cfg, quiet=True) is None:
            _download_tessdata(cfg)
            _tess = None
        return _tesseract(cfg) is not None
    return _get_reader(cfg) is not None


def _download_tessdata(cfg: dict) -> None:
    """Model języka (tesseract-ocr/tessdata, Apache 2.0) do tessdata_dir, gdy brak go w systemie."""
    import urllib.request

    t = _tcfg(cfg)
    target = ROOT / t["tessdata_dir"]
    target.mkdir(parents=True, exist_ok=True)
    for lang in (t["lang"], "osd"):
        dest = target / f"{lang}.traineddata"
        if dest.exists():
            continue
        url = f"https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"
        for attempt in range(4):
            try:
                log.info("Pobieranie %s", url)
                tmp = dest.with_suffix(".part")
                urllib.request.urlretrieve(url, tmp)
                tmp.replace(dest)
                break
            except OSError as e:
                log.warning("Pobieranie modelu Tesseracta nie powiodło się (%s) – ponawiam", e)
                time.sleep(5 * (attempt + 1))


def available(cfg: dict | None = None) -> bool:
    """Czy wybrany silnik jest zainstalowany (bez ładowania modeli)."""
    import importlib.util

    cfg = settings(cfg)
    if cfg["engine"] == "tesseract":
        return _tesseract(cfg, quiet=True) is not None
    return importlib.util.find_spec("easyocr") is not None


# ------------------------------------------------------------------ Tesseract
_tess = None


def _tcfg(cfg: dict) -> dict:
    return {**DEFAULTS["tesseract"], **(cfg.get("tesseract") or {})}


def _tesseract(cfg: dict, quiet: bool = False) -> tuple[str, list[str]] | None:
    """Ścieżka programu i argumenty wspólne (model języka) albo None, gdy Tesseract niedostępny."""
    global _tess
    if _tess is not None:
        return _tess or None
    import shutil
    import subprocess

    t = _tcfg(cfg)
    cmd = t["cmd"] or shutil.which("tesseract")
    if not cmd and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
        cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    args = []
    tessdata = ROOT / t["tessdata_dir"] if t.get("tessdata_dir") else None
    if tessdata and (tessdata / f"{t['lang']}.traineddata").exists():
        args = ["--tessdata-dir", str(tessdata)]
    ok = False
    if cmd:
        try:
            langs = subprocess.run([cmd, *args, "--list-langs"], capture_output=True, text=True, timeout=30).stdout
            ok = t["lang"] in langs.split()
        except (OSError, subprocess.SubprocessError):
            ok = False
    if not ok:
        if not quiet:
            log.warning("Tesseract z językiem %r niedostępny – skany zostaną pominięte "
                        "(Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-pol)", t["lang"])
        _tess = ()  # zapamiętujemy brak
        return None
    _tess = (cmd, args)
    return _tess


def _whiten_redactions(img):
    """Zamalowuje na biało pola anonimizacji (pełne czarne prostokąty).

    Tesseract „czyta” je jako szum („RB — LD LI LILD”), który trafiałby do nazw stron. Prostokąt
    wykrywamy erozją maski ciemnych pikseli: znika wszystko węższe niż ~1/3 wysokości wiersza
    (kreski liter, linie tabel), zostają tylko pełne ciemne pola.
    """
    from PIL import ImageFilter

    small = img.resize((max(img.width // 4, 1), max(img.height // 4, 1)))
    dark = small.point(lambda p: 255 if p < 70 else 0)
    solid = dark.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(7))
    if not solid.getbbox():
        return img
    mask = solid.resize(img.size)
    out = img.copy()
    out.paste(255, mask=mask)
    return out


def _tesseract_page(pdf_path: Path, page_index: int, cfg: dict) -> list[dict]:
    """OCR strony Tesseractem; wynik TSV (słowa z ramkami) → słowa w układzie współrzędnych PDF."""
    import collections
    import io
    import os
    import subprocess

    import pypdfium2 as pdfium

    tool = _tesseract(cfg)
    if tool is None:
        return []
    cmd, args = tool
    t = _tcfg(cfg)
    scale = t["scale"]
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        img = pdf[page_index].render(scale=scale).to_pil().convert("L")
    finally:
        pdf.close()
    if t.get("remove_redactions", True):
        img = _whiten_redactions(img)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    env = dict(os.environ)
    if cfg.get("threads"):
        env["OMP_THREAD_LIMIT"] = str(cfg["threads"])
    # wynik TSV przez parametr (plik konfiguracyjny „tsv” nie leży w naszym katalogu modeli)
    out = subprocess.run([cmd, "stdin", "stdout", *args, "-l", t["lang"], "--psm", str(t["psm"]),
                          "-c", "tessedit_create_tsv=1"],
                         input=buf.getvalue(), capture_output=True, timeout=300, env=env).stdout
    rows = []
    for line in out.decode("utf-8", errors="replace").splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        if float(f[10]) < t["min_conf"]:
            continue
        rows.append(f)
    # wysokość słowa = wysokość linii (inaczej „a”, „w” wyglądałyby na drobną czcionkę stopki)
    lines = collections.defaultdict(list)
    for f in rows:
        lines[(f[2], f[3], f[4])].append(f)
    words = []
    for ws in lines.values():
        top = min(int(f[7]) for f in ws) / scale
        bottom = max(int(f[7]) + int(f[9]) for f in ws) / scale
        for f in ws:
            x0 = int(f[6]) / scale
            words.append({"text": f[11].strip(), "x0": x0, "x1": x0 + int(f[8]) / scale, "top": top,
                          "bottom": bottom, "size": (bottom - top) * 0.8, "upright": True,
                          "ocr_conf": float(f[10]) / 100})
    return words



def page_words(pdf_path: Path, page_index: int, cfg: dict) -> list[dict]:
    """Słowa strony w formacie zgodnym z pdfplumber.extract_words (x0, x1, top, bottom, text, size).

    Wynik jest cache'owany na dysku (klucz: skrót pliku + strona + ustawienia), więc ponowne
    przetwarzanie tego samego skanu nie powtarza kosztownego OCR.
    """
    import hashlib
    import json

    cache_dir = ROOT / cfg.get("cache_dir", ".ocr_cache")
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:24]
    if cfg["engine"] == "tesseract":
        t = _tcfg(cfg)
        key = f"{digest}_p{page_index}_tess_{t['lang']}_psm{t['psm']}_s{t['scale']}_c{t['min_conf']}_r{int(t.get('remove_redactions', True))}"
    else:
        rt = "".join(f"_{k}{v}" for k, v in sorted(cfg["readtext"].items()))
        key = f"{digest}_p{page_index}_s{cfg['scale']}_c{cfg['min_confidence']}_{'-'.join(cfg['languages'])}{rt}"
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    if cfg["engine"] == "tesseract":
        words = _tesseract_page(pdf_path, page_index, cfg)
        ready = bool(_tess)
    else:
        words = _ocr_page(pdf_path, page_index, cfg)
        ready = _reader is not None
    if words or ready:
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


if __name__ == "__main__":  # python -m odwolania2json.ocr  → pobranie modeli
    import sys
    from .config import load_config

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ok = prepare(load_config().settings.get("ocr"))
    print("Modele OCR gotowe." if ok else "OCR niedostępny.")
    sys.exit(0 if ok else 1)
