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
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    rows: list[list[dict]] = []
    for w in words:
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= y_tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        cells: list[Cell] = []
        for w in row:
            char_w = (w["x1"] - w["x0"]) / max(len(w["text"]), 1)
            gap_limit = max(char_w * 2.2, 6.0)
            if cells and w["x0"] - cells[-1].x1 <= gap_limit:
                cells[-1].text += " " + w["text"]
                cells[-1].x1 = w["x1"]
            else:
                cells.append(Cell(w["x0"], w["x1"], w["text"]))
        lines.append(Line(page_no, row[0]["top"], cells))
    return lines


def load_pdf(path: str | Path) -> Document:
    path = Path(path)
    lines: list[Line] = []
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            for line in _group_lines(words, i):
                if _PAGE_FOOTER.match(line.text):
                    continue
                lines.append(line)
    return Document(path, lines, n)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(load_pdf(sys.argv[1]).text)
