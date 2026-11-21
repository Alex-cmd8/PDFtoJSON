"""PDF -> tekst z zachowaniem układu.

Linie składamy sami ze słów (pdfplumber), dzięki czemu:
* duża przerwa pozioma między słowami = granica kolumny (oznaczana jako "   "),
* każda linia zna swoje "komórki" z pozycją X, co pozwala czytać układy dwukolumnowe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

COL_SEP = "   "  # separator kolumn w tekście linii
_PAGE_FOOTER = re.compile(r"^\s*Strona\s+\d+\s+z\s+\d+\s*$", re.I)


@dataclass
class Cell:
    x0: float
    x1: float
    text: str
    # słowa komórki z pozycją X – pozwalają przyciąć komórkę do granicy kolumny
    words: list = field(default_factory=list)

    def text_before(self, xlim: float | None) -> str:
        if xlim is None or not self.words:
            return self.text
        return " ".join(t for x0, x1, t in self.words if x0 < xlim - 2)


@dataclass
class Line:
    page: int
    top: float
    cells: list[Cell] = field(default_factory=list)

    @property
    def text(self) -> str:
        return COL_SEP.join(c.text for c in self.cells)

    @property
    def x0(self) -> float:
        return self.cells[0].x0 if self.cells else 0.0


@dataclass
class Document:
    path: Path
    lines: list[Line]
    n_pages: int

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def head(self, n_lines: int = 60) -> str:
        return "\n".join(l.text for l in self.lines[:n_lines])


def _group_lines(words: list[dict], page_no: int, y_tol: float = 3.0) -> list[Line]:
    """Grupuje słowa w linie po środku wysokości (tolerancja y_tol – dla OCR zależna od wysokości liter)."""
    def center(w):
        return (w["top"] + w.get("bottom", w["top"])) / 2

    words = sorted(words, key=lambda w: (center(w), w["x0"]))
    rows: list[list[dict]] = []
    centers: list[float] = []
    for w in words:
        c = center(w)
        if rows and abs(centers[-1] - c) <= y_tol:
            rows[-1].append(w)
            centers[-1] = sum(center(x) for x in rows[-1]) / len(rows[-1])
        else:
            rows.append([w])
            centers.append(c)
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        cells: list[Cell] = []
        for w in row:
            char_w = (w["x1"] - w["x0"]) / max(len(w["text"]), 1)
            gap_limit = max(char_w * 2.2, 6.0)
            if cells and w["x0"] - cells[-1].x1 <= gap_limit:
                cells[-1].text += " " + w["text"]
                cells[-1].words.append((w["x0"], w["x1"], w["text"]))
                cells[-1].x1 = w["x1"]
            else:
                cells.append(Cell(w["x0"], w["x1"], w["text"], [(w["x0"], w["x1"], w["text"])]))
        lines.append(Line(page_no, min(w["top"] for w in row), cells))
    return lines


def load_pdf(path: str | Path, ocr_cfg: dict | None = None) -> Document:
    """Tekst PDF; strony bez warstwy tekstowej (skany) przechodzą przez OCR (odwolania2json.ocr)."""
    from . import ocr

    path = Path(path)
    ocfg = ocr.settings(ocr_cfg)
    lines: list[Line] = []
    ocr_pages = 0
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False,
                                       extra_attrs=["size"])
            y_tol = 3.0
            if (sum(len(w["text"]) for w in words) < ocfg["min_chars_text_layer"] and ocfg["enabled"]
                    and (not ocfg.get("max_pages") or i < ocfg["max_pages"])):
                words = ocr.page_words(path, i, ocfg)
                ocr_pages += 1
                if words:  # linie skanu: tolerancja względem wysokości liter (krzywe skanowanie)
                    hs = sorted(w["bottom"] - w["top"] for w in words)
                    y_tol = max(3.0, 0.45 * hs[len(hs) // 2])
            # znak wodny („KOPIA”, „WZÓR”) – litery wielokrotnie większe niż tekst strony
            if words:
                sizes = sorted(w["size"] for w in words)
                median = sizes[len(sizes) // 2]
                words = [w for w in words if w["size"] <= 2.5 * median and w.get("upright", True)]
                # żywa pagina / stopka: drobniejsza czcionka w marginesie strony (np. „Odwołanie – sprawa …”)
                margin = 0.06 * page.height
                words = [w for w in words
                         if not ((w["top"] < margin or w["top"] > page.height - margin) and w["size"] < 0.9 * median)]
            for line in _group_lines(words, i, y_tol):
                if _PAGE_FOOTER.match(line.text):
                    continue
                lines.append(line)
    doc = Document(path, lines, n)
    doc.ocr_pages = ocr_pages
    return doc


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(load_pdf(sys.argv[1]).text)
