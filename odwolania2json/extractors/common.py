"""Wspólne heurystyki: nazwy podmiotów, osoby, identyfikatory (KRS/NIP/REGON/PESEL)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

UP = "A-ZĄĆĘŁŃÓŚŹŻ"
LO = "a-ząćęłńóśźż"
NAME_WORD = rf"[{UP}][{LO}]+(?:-[{UP}][{LO}]+)?"
# imię + nazwisko (nazwisko dwuczłonowe tylko z łącznikiem) – trzecie słowo to zwykle funkcja/kolejna osoba
PERSON_RX = rf"(?P<person>{NAME_WORD}\s+{NAME_WORD})(?![{LO}])"

IDS = {
    # dopuszczamy „KRS pod nr / pod numerem 0000…” oraz prefiks kraju w NIP („NIP: PL5271037727”)
    "krs": re.compile(r"\bKRS\W{0,3}(?:pod\s+)?(?:nr|numerem)?\W{0,2}(\d{10})(?!\d)"),
    "nip": re.compile(r"\bNIP\W{0,3}(?:nr\W{0,2})?(?:PL\s?)?(\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}|\d{3}[- ]?\d{2}[- ]?\d{2}[- ]?\d{3})(?!\d)"),
    "regon": re.compile(r"\bREGON\W{0,3}(?:nr\W{0,2})?(\d{3}[- ]?\d{3}[- ]?\d{3}(?:[- ]?\d{5})?)(?!\d)"),
    "pesel": re.compile(r"\bPESEL\W{0,3}(?:nr\W{0,2})?(\d{11})(?!\d)"),
}


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ids_in(text: str) -> dict[str, str | None]:
    out = {}
    for k, rx in IDS.items():
        m = rx.search(text)
        out[k] = re.sub(r"\D", "", m.group(1)) if m else None
    return out


# „PEŁNOMOCNICTWO (PROCESOWE)” na początku nazwy – także „P E Ł N O …” i „PEŁ NO MOCNICTW0” z OCR
_TITLE_PREFIX = re.compile(
    r"^\s*(?:P\s*E\s*[ŁL]\s*N\s*[O0]\s*M\s*[O0]\s*C\s*N\s*I\s*C\s*T\s*W\s*[O0]"
    r"(?:\s*P\s*R\s*[O0]\s*C\s*E\s*S\s*[O0]\s*W\s*E)?)\s+", re.I)


class Lexicon:
    def __init__(self, raw: dict):
        self.legal_forms = raw.get("legal_forms", [])
        self.titles = raw.get("attorney_titles", [])
        self.stop = {s.casefold() for s in raw.get("name_start_stopwords", [])}
        lf = "|".join(f"(?:{x})" for x in self.legal_forms)
        # nazwa z formą prawną; dopuszczamy „sp. z o.o. sp.k.” itp.
        self.company_end_rx = re.compile(rf"(?:{lf})(?=$|[\s,;:)(]|\.)", re.I)
        tl = "|".join(f"(?:{x})" for x in self.titles)
        # między tytułem zawodowym a nazwiskiem może stać stopień naukowy („adw. dr hab. Jan Nowak”)
        degrees = r"(?:(?:dr|prof|hab|inż|mgr)\.?\s*)*"
        self.attorney_rx = re.compile(rf"(?<![{LO}{UP}])(?:{tl})\s*{degrees}{PERSON_RX}")

    # ---------------------------------------------------------------- podmioty
    # (forma prawna bez kropki na końcu – zwykle zgubiona przez OCR lub koniec linii)
    def companies(self, text: str) -> list[tuple[int, int, str]]:
        """Zwraca (start, koniec, nazwa) dla każdej nazwy zakończonej formą prawną."""
        out = []
        for m in self.company_end_rx.finditer(text):
            end = m.end()
            start = self._walk_back(text, m.start())
            if start is None:
                continue
            name = text[start:end].strip(" ,;")
            # tytuł pisma przyklejony do nazwy (także rozstrzelony / z „0” zamiast „O” po OCR)
            if tm := _TITLE_PREFIX.match(name):
                start += tm.end()
                name = text[start:end].strip(" ,;")
            if len(name) > 3:
                out.append((start, end, _full_stop(name)))
        return out

    def _walk_back(self, text: str, pos: int) -> int | None:
        """Cofa się od formy prawnej po słowach nazwy (wielka litera / cyfra / łączniki)."""
        tokens = list(re.finditer(r"\S+", text[:pos]))
        start = None
        # łączniki dozwolone wewnątrz nazwy („… w m. st. Warszawie Spółka …”)
        connectors = {"i", "&", "w", "-", "im.", "na", "dla", "nr", "m.", "st."}
        for t in reversed(tokens):
            w = t.group(0)
            # nazwa w cudzysłowie („„BIOARCUS” Spółka z o.o.”) – cudzysłów nie przerywa nazwy
            core = w.strip(",;:()„”\"")
            if core in connectors and not w.endswith((",", ":", ";", ")")):  # małe „w” to łącznik, nie stoper „W imieniu”
                continue
            if not core or w.endswith((":", ";", ")")) or w.startswith("(") or core.casefold() in self.stop:
                break
            if core[0].isupper() or core[0].isdigit() or core in connectors:
                if w.endswith(",") and start is not None:
                    break
                start = t.start()
                continue
            break
        if start is None:
            return None
        # ostatnia litera nagłówka rozstrzelonego („P E Ł N O M O C N I C T W O Balttec …”)
        m = re.match(rf"[{UP}]\s+", text[start:pos])
        if m and re.search(rf"(?:\b[{UP}]\s+){{2}}$", text[:start]):
            start += m.end()
        # nazwa nie zaczyna się od łącznika
        while True:
            m = re.match(r"(?:i|&|w|na|dla|nr|-)\s+", text[start:pos])
            if not m:
                break
            start += m.end()
        return start

    def attorneys(self, text: str) -> list[tuple[int, str]]:
        return [(m.start(), m.group("person")) for m in self.attorney_rx.finditer(text)]


def dedupe(names):
    seen, out = set(), []
    for n in names:
        k = n.casefold()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


def is_person_line(s: str) -> str | None:
    s = s.strip()
    m = re.fullmatch(PERSON_RX + r"\s*,?.*", s)
    if not m:
        return None
    person = m.group("person")
    # odrzucamy nazwy firm i nagłówki
    if re.search(r"\b(?:sp\.|S\.A|Zarząd|Prezes|Dyrektor|Wspólnik|Prokurent|Mocodawca|Pełnomocni)", person):
        return None
    return person


_ABBR_END = re.compile(r"(?:\bS\.A|\bS\.K\.A|\bsp\.\s?[jkp]|\bsp\. z o\.o)$", re.I)


def _full_stop(name: str) -> str:
    """Kanoniczny zapis formy prawnej na końcu nazwy.

    OCR: „Sp. z 0.0” / „Sp: z0.0-” → „Sp. z o.o.”; myślnik zamiast kropki („S.A-”); skrót zawsze
    kończy się kropką („S.A” → „S.A.”, „sp. k” → „sp. k.”).
    """
    name = re.sub(r"\b(sp)[.:,]?\s?z\s?[0o][.,]\s?[0o][.,-]?$", lambda m: m.group(1) + ". z o.o.", name, flags=re.I)
    name = re.sub(r"(\b(?:S\.A|S\.K\.A|sp\.\s?[jkp]))-$", r"\1.", name, flags=re.I)
    return name + "." if _ABBR_END.search(name) else name


def fix_legal_form(name: str | None) -> str | None:
    return _full_stop(name.strip()) if name else name
