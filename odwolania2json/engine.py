"""Generyczny silnik reguł „etykieta → wartość” sterowany konfiguracją YAML.

Specyfikacja pola (YAML):
    nazwa_pola:
      type: date | amount | account | nip | regon | krs | pesel | ted | bzp | email | token | text
      labels: [regex, ...]     # etykiety zakotwiczone na początku komórki, w kolejności priorytetu
      patterns: [regex, ...]   # wzorce w ciągłym tekście z grupą (?P<v>...) lub znacznikiem {v}
      lookahead: 4             # ile linii w dół szukać wartości w kolumnie etykiety
      multiline: true          # (text) dołączaj linie kontynuacji
      nth: 0                   # zapasowo: n-te wystąpienie wartości danego typu w dokumencie
      default: null

Każda znaleziona wartość ma ślad (źródło: strona, linia, reguła) – transparentność ekstrakcji.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .normalize import TYPES
from .pdftext import Cell, Document, Line

LABEL_TAIL = r"\s*(?:\.{2,}|…+)?\s*[:.]?\s*"


@dataclass
class Hit:
    value: Any
    rule: str
    page: int | None = None
    snippet: str = ""

    def trace(self) -> dict:
        return {"value": self.value, "rule": self.rule, "page": None if self.page is None else self.page + 1,
                "snippet": self.snippet[:200]}


def _type(spec: dict):
    rx, norm = TYPES[spec.get("type", "text")]
    return re.compile(rx, re.I), norm


def _find_in(text: str, spec: dict):
    rx, norm = _type(spec)
    if spec.get("type", "text") == "text":
        v = norm(text)
        return v
    for m in rx.finditer(text):
        v = norm(m.group("v"))
        if v is not None:
            return v
    return None


def _overlap(a: Cell, b: Cell, slack: float = 4.0) -> bool:
    return a.x0 - slack <= b.x1 and b.x0 - slack <= a.x1


class Engine:
    def __init__(self, fields: dict[str, dict], stop_labels: list[str] | None = None):
        self.fields = fields
        all_labels = [l for f in fields.values() for l in f.get("labels", [])] + (stop_labels or [])
        # „to jest etykieta” tylko gdy po niej (i max 2 słowach) jest dwukropek, kropki prowadzące
        # albo koniec komórki – inaczej np. „opłata skarbowa…” w tytule wyglądałoby jak etykieta „Opłata”.
        alt = "|".join(f"(?:{l})" for l in all_labels)
        self._any_label = re.compile(rf"^\s*(?:{alt})(?:\s+[\w.]+){{0,2}}?\s*(?::|\.{{2,}}|…|$)", re.I) if all_labels else None

    def is_label(self, text: str) -> bool:
        return bool(self._any_label and self._any_label.match(text))

    # ------------------------------------------------------------------ labels
    def _by_label(self, doc: Document, spec: dict, name: str) -> Hit | None:
        lookahead = spec.get("lookahead", 4)
        for label in spec.get("labels", []):
            lrx = re.compile(r"^\s*(?:" + label + r")" + LABEL_TAIL, re.I)
            occ = []
            for li, line in enumerate(doc.lines):
                for ci, cell in enumerate(line.cells):
                    if m := lrx.match(cell.text):
                        occ.append((li, ci, cell.text[m.end():].strip()))
            # para „etykieta wartość” w jednej linii ma pierwszeństwo przed nagłówkiem kolumny tabeli
            # (np. „Kwota” w nagłówku wyciągu vs „Kwota 17,00 PLN” w szczegółach operacji)
            for below in (False, True):
                for li, ci, rest in occ:
                    hit = self._value_after(doc, li, ci, rest, spec, lookahead, below)
                    if hit is not None:
                        v, src_line, extra = hit
                        return Hit(v, f"label:{label}{extra}", src_line.page, src_line.text)
        return None

    def _value_after(self, doc, li, ci, rest, spec, lookahead, below=True):
        line = doc.lines[li]
        label_cell = line.cells[ci]
        is_text = spec.get("type", "text") == "text"
        if is_text:
            if not below:
                return None  # tekst: jedno przejście (logika poniżej obejmuje oba przypadki)
            # układ dwukolumnowy „TYTUŁ | NUMER TRANSAKCJI”: wartość przycinamy do granicy kolumny obok
            xlim = None
            if ci + 1 < len(line.cells) and self.is_label(line.cells[ci + 1].text):
                xlim = line.cells[ci + 1].x0
            parts, start_x = [], None
            if rest:
                parts.append(rest)
                start_x = label_cell.x0
            elif ci + 1 < len(line.cells) and not self.is_label(line.cells[ci + 1].text):
                parts.append(line.cells[ci + 1].text)
                start_x = line.cells[ci + 1].x0
                # wartość wielolinijkowa wyśrodkowana względem etykiety: linie NAD etykietą
                # w kolumnie wartości (bez niczego w kolumnie etykiet)
                up = li - 1
                while up >= 0 and up >= li - 4:
                    prev = doc.lines[up]
                    if (len(prev.cells) == 1 and abs(prev.cells[0].x0 - start_x) <= 8
                            and prev.cells[0].x0 > label_cell.x1 and not self.is_label(prev.text)):
                        parts.insert(0, prev.cells[0].text)
                        up -= 1
                    else:
                        break
            j = li + 1
            if not parts:  # wartość pod etykietą
                while j < len(doc.lines) and j <= li + 2:
                    nxt = doc.lines[j]
                    cells = [c for c in nxt.cells if _overlap(c, label_cell, 20)] or nxt.cells
                    if cells and not self.is_label(cells[0].text):
                        parts.append(cells[0].text_before(xlim))
                        start_x = cells[0].x0
                        j += 1
                        break
                    j += 1
            if not parts:
                return None
            if spec.get("multiline", True):
                limit = spec.get("max_lines", 6)
                while j < len(doc.lines) and limit > 0:
                    nxt = doc.lines[j]
                    cands = [c for c in nxt.cells if abs(c.x0 - start_x) <= 8 or abs(c.x0 - label_cell.x0) <= 8]
                    if not cands or self.is_label(cands[0].text) or self.is_label(nxt.text):
                        break
                    parts.append(cands[0].text_before(xlim))
                    j += 1
                    limit -= 1
            v = _find_in(" ".join(parts), spec)
            return (v, line, "") if v is not None else None

        # wartości atomowe: reszta komórki → kolejne komórki linii → (2. przejście) kolumna poniżej
        if not below:
            if rest and (v := _find_in(rest, spec)) is not None:
                return v, line, ""
            for c in line.cells[ci + 1:]:
                if self.is_label(c.text):
                    break
                if (v := _find_in(c.text, spec)) is not None:
                    return v, line, ""
            return None
        for j in range(li + 1, min(li + 1 + lookahead, len(doc.lines))):
            nxt = doc.lines[j]
            for c in nxt.cells:
                if _overlap(c, label_cell, 4) or (len(line.cells) == 1 and c is nxt.cells[0]):
                    if (v := _find_in(c.text, spec)) is not None:
                        return v, nxt, " (kolumna)"
        return None

    # ---------------------------------------------------------------- patterns
    def _by_pattern(self, flat: str, spec: dict) -> Hit | None:
        rx_v, norm = TYPES[spec.get("type", "text")]
        inner = rx_v.replace("(?P<v>", "(?:")
        for p in spec.get("patterns", []):
            rx = re.compile(p.replace("{v}", f"(?P<v>{inner})"), re.I | re.S)
            for m in rx.finditer(flat):
                v = norm(m.group("v"))
                if v is not None:
                    return Hit(v, f"pattern:{p}", None, flat[max(0, m.start() - 40): m.end() + 40])
        return None

    def _nth(self, flat: str, spec: dict) -> Hit | None:
        rx, norm = _type(spec)
        vals = [v for m in rx.finditer(flat) if (v := norm(m.group("v"))) is not None]
        n = spec["nth"]
        if len(vals) > n:
            return Hit(vals[n], f"nth:{n}", None, "")
        return None

    def extract_field(self, doc: Document, name: str, flat: str | None = None) -> Hit:
        spec = self.fields[name]
        flat = flat if flat is not None else re.sub(r"\s+", " ", doc.text)
        hit = self._by_label(doc, spec, name) or self._by_pattern(flat, spec)
        if hit is None and "nth" in spec:
            hit = self._nth(flat, spec)
        return hit or Hit(spec.get("default"), "default")

    def extract_all(self, doc: Document) -> dict[str, Hit]:
        flat = re.sub(r"\s+", " ", doc.text)
        return {n: self.extract_field(doc, n, flat) for n in self.fields}
