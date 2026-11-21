"""Typy wartości: wzorzec wyszukiwania + normalizacja do formatu wyjściowego.

Każdy typ to para (regex z grupą `v`, funkcja normalizująca). Nowe typy można
dopisać tutaj; konfiguracja YAML odwołuje się do nich po nazwie (`type: date`).
"""
from __future__ import annotations

import re
from typing import Callable

MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}
_MON_RX = "|".join(MONTHS)

DATE_RX = (
    rf"(?P<v>(?:\d{{1,2}}\s+(?:{_MON_RX})\s+\d{{4}})"
    r"|(?:\d{4}-\d{2}-\d{2})"
    r"|(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}))"
)


def norm_date(s: str) -> str | None:
    s = s.strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        y, mo, d = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s):
        d, mo, y = map(int, m.groups())
    elif m := re.fullmatch(rf"(\d{{1,2}})\s+({_MON_RX})\s+(\d{{4}})", s):
        d, mo, y = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    else:
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# kwota z separatorem tysięcy (z groszami lub bez: „15 000 zł”, „2.500 PLN”) albo zwykła liczba
AMOUNT_RX = r"(?P<v>\d{1,3}(?:[  .]\d{3})+(?:,\d{2})?|\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{2})|\d+(?:[.,]\d{2})?)(?=\s*(?:PLN|zł|zl|$|\s|\.|,|\)))"


def norm_amount(s: str) -> float | None:
    s = s.replace(" ", " ").strip()
    if m := re.fullmatch(r"(\d{1,3}(?:[ .]\d{3})*)(?:[.,](\d{2}))?", s):
        whole = re.sub(r"[ .]", "", m.group(1))
        return float(f"{whole}.{m.group(2) or '00'}")
    if m := re.fullmatch(r"(\d+)(?:[.,](\d{2}))?", s):
        return float(f"{m.group(1)}.{m.group(2) or '00'}")
    return None


# rachunek: 26 cyfr, opcjonalnie z prefiksem PL i odstępami (także przełamaniami linii)
ACCOUNT_RX = r"(?P<v>(?:PL)?\s?\d{2}(?:\s?\d{4}){6})(?!\d)"


def norm_account(s: str) -> str | None:
    d = re.sub(r"\D", "", s)
    return d if len(d) == 26 else None


def norm_digits(n: int) -> Callable[[str], str | None]:
    def f(s: str) -> str | None:
        d = re.sub(r"\D", "", s)
        return d if len(d) == n else None
    return f


def _strip_quotes(s: str) -> str:
    """Zdejmuje cudzysłów otaczający całą wartość, ale nie zamykający cudzysłów wewnętrzny
    („Dostawa … „Rejon Północ”” → „Dostawa … „Rejon Północ””, a nie „… „Rejon Północ”)."""
    def opens(t): return t.count("„") + t.count("“")
    s = s.strip()
    # para otaczająca, jeśli środek pozostaje zrównoważony
    if len(s) > 1 and s[0] in "„“\"" and s[-1] in "”\"":
        inner = s[1:-1]
        if opens(inner) == inner.count("”"):
            s = inner.strip()
    # pojedynczy, niesparowany cudzysłów na brzegu
    while s and s[0] in "„“" and opens(s) > s.count("”"):
        s = s[1:].strip()
    while s and s[-1] == "”" and s.count("”") > opens(s):
        s = s[:-1].strip()
    if s.count('"') % 2 == 1:
        s = s.strip('"').strip()
    return s


def norm_text(s: str) -> str | None:
    s = re.sub(r"\s+", " ", s).strip()
    # przeniesienie wyrazu na końcu linii: „wdro- żeniem” → „wdrożeniem” (tylko gdy dalej mała litera)
    s = re.sub(r"(\w)- ([a-ząćęłńóśźż])", r"\1\2", s)
    s = _strip_quotes(s)
    s = re.sub(r"[.;,]$", "", s).strip()
    s = _strip_quotes(s)
    return s or None


def norm_token(s: str) -> str | None:
    s = s.strip().rstrip(".,;:)")
    return s or None


TED_RX = r"(?P<v>\d{4}\s*/\s*S\s*\d{1,3}\s*-\s*\d{5,7}|\d{5,7}\s*-\s*\d{4})"


def norm_ted(s: str) -> str | None:
    s = re.sub(r"\s+", "", s)
    if m := re.fullmatch(r"(\d{4})/S\d{1,3}-(\d{5,7})", s):
        return f"{m.group(2)}-{m.group(1)}"
    if m := re.fullmatch(r"(\d{5,7})-(\d{4})", s):
        return f"{m.group(1)}-{m.group(2)}"
    return None


BZP_RX = r"(?P<v>\d{4}\s*/\s*BZP\s*\d{6,8}(?:\s*/\s*\d{1,2})?)"


def norm_bzp(s: str) -> str | None:
    return re.sub(r"\s+", "", s) or None


EMAIL_RX = r"(?P<v>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)"

TYPES: dict[str, tuple[str, Callable[[str], object]]] = {
    "date": (DATE_RX, norm_date),
    "amount": (AMOUNT_RX, norm_amount),
    "account": (ACCOUNT_RX, norm_account),
    "nip": (r"(?P<v>\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}|\d{10})(?!\d)", norm_digits(10)),
    "regon": (r"(?P<v>\d{9}(?:\d{5})?)(?!\d)", lambda s: s if len(s) in (9, 14) else None),
    "krs": (r"(?P<v>\d{10})(?!\d)", norm_digits(10)),
    "pesel": (r"(?P<v>\d{11})(?!\d)", norm_digits(11)),
    "ted": (TED_RX, norm_ted),
    "bzp": (BZP_RX, norm_bzp),
    "email": (EMAIL_RX, lambda s: s.rstrip(".")),
    # identyfikator: musi zawierać cyfrę (żeby nie złapać słowa po etykiecie)
    "token": (r"(?P<v>(?=[\w./-]*\d)[A-Za-z0-9][\w./-]*[A-Za-z0-9])", norm_token),
    "text": (r"(?P<v>.+)", norm_text),
}
