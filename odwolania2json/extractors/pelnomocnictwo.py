"""Ekstraktor pełnomocnictwa: mocodawcy (także konsorcjum), podpisujący, pełnomocnicy."""
from __future__ import annotations

import re

from .common import IDS, Lexicon, PERSON_RX, dedupe, flat, ids_in, is_person_line


def _zone_end(text: str, phrases: list[str]) -> int:
    ends = [m.start() for p in phrases if (m := re.search(p, text, re.I))]
    return min(ends) if ends else len(text)


def _mocodawcy(text: str, lex: Lexicon, cfg: dict, trace: dict) -> list[dict]:
    zone = text[: _zone_end(text, cfg["grant_phrases"])]
    # nazwy kandydatów: forma prawna albo „pod firmą X,”
    cands = [(s, e, n, "forma_prawna") for s, e, n in lex.companies(zone)]
    # „pod firmą X,” – nazwa może zawierać cudzysłowy („PHU „ŻUBR” Jan Nowak”), kończy ją przecinek
    for m in re.finditer(r"pod firm[ąa]\s+(?P<n>[^,(]+?)\s*(?:,|\(|z siedzib)", zone):
        cands.append((m.start("n"), m.end("n"), m.group("n").strip(), "pod_firma"))
    # wyliczenie członków konsorcjum „1) X, ul. …” – także przedsiębiorca bez formy prawnej
    for m in re.finditer(r"(?:^|[\s;:])\d\)\s*(?P<n>[^,;()]{3,120}?),\s*(?:ul\.|al\.|pl\.|os\.|z siedzib)", zone):
        s, e = m.start("n"), m.end("n")
        if not any(cs < e and s < ce for cs, ce, _, _ in cands):
            cands.append((s, e, m.group("n").strip(), "wyliczenie"))
    cands.sort()
    # zostawiamy kandydatów, po których (przed kolejnym kandydatem) jest identyfikator
    ents = []
    for i, (s, e, name, how) in enumerate(cands):
        nxt = cands[i + 1][0] if i + 1 < len(cands) else len(zone)
        seg = zone[e:nxt][:400]
        ids = ids_in(seg)
        if any(ids[k] for k in ("krs", "nip", "regon")) or not ents and i == len(cands) - 1:
            ents.append({"name": name, "ids": ids, "start": s, "how": how, "seg": seg})
    if not ents and cands:
        s, e, name, how = cands[0]
        ents.append({"name": name, "ids": ids_in(zone[e:e + 400]), "start": s, "how": how, "seg": ""})
    # „pod firmą” ma pierwszeństwo przed nazwą tej samej osoby wykrytą inaczej
    out, seen = [], set()
    for ent in ents:
        key = ent["ids"]["nip"] or ent["name"]
        if key in seen:
            continue
        seen.add(key)
        natural = ent["how"] in ("pod_firma", "wyliczenie") or (
            not ent["ids"]["krs"] and re.search(cfg["natural_person_rx"], zone, re.I))
        person = None
        if natural and ent["how"] == "wyliczenie":
            # firma przedsiębiorcy zawiera jego imię i nazwisko (art. 43⁴ KC) – zwykle na końcu
            person = " ".join(ent["name"].split()[-2:])
        elif natural:
            m = re.search(r"niżej podpisan\w*\s+" + PERSON_RX, zone) or re.search(PERSON_RX + r"\s*,?\s*prowadząc\w* działalność", zone)
            person = m.group("person") if m else None
            if not person:  # ostatnie dwa słowa nazwy firmy
                person = " ".join(ent["name"].split()[-2:])
        out.append({
            "data": {
                "imie_nazwisko": person if natural else None,
                "krs": ent["ids"]["krs"],
                "nazwa": ent["name"],
                "nip": ent["ids"]["nip"],
                "typ": "osoba_fizyczna" if natural else "osoba_prawna",
            },
            "podpisujacy": [],
        })
        trace.setdefault("mocodawca", []).append({"nazwa": ent["name"], "regula": ent["how"], "kontekst": ent["seg"][:150]})
    return out


def _pelnomocnicy(text: str, lex: Lexicon, trace: dict) -> list[dict]:
    found = lex.attorneys(text)
    # PESEL przypisujemy do najbliższego wcześniejszego pełnomocnika
    pesels = [(m.start(), re.sub(r"\D", "", m.group(1))) for m in IDS["pesel"].finditer(text)]
    names = dedupe([n for _, n in found])
    out = []
    for n in names:
        pos = next(p for p, x in found if x == n)
        # PESEL należy do najbliższego pełnomocnika PRZED nim (nie do pierwszego w promieniu 200 znaków)
        pesel = next((v for p, v in pesels if 0 < p - pos < 200
                      and max((q for q, _ in found if q < p), default=-1) == pos), None)
        out.append({"imie_nazwisko": n, "pesel": pesel})  # tekst – jak w danych referencyjnych (i bez utraty wiodącego zera)
    trace["pelnomocnicy"] = {"regula": "tytuł zawodowy + imię i nazwisko", "znalezione": names}
    return out


def _signatories(doc, lex: Lexicon, attorneys: set[str], mocodawcy: list[dict], cfg: dict) -> list[tuple[str | None, str]]:
    """Osoby pod liniami kropek (podpisy). Zwraca (nagłówek „W imieniu X”, osoba)."""
    lines = doc.lines
    accept_rx = re.compile(cfg["accept_phrase"], re.I)
    dotted_rx = re.compile(r"[.…_]{6,}")

    def same_col(a, b, slack=40):
        return a.x0 - slack <= b.x1 and b.x0 - slack <= a.x1

    def is_dotted(c):
        return bool(dotted_rx.fullmatch(c.text.replace(" ", "")))

    memo: dict[tuple[int, int], str | None] = {}

    def header_for(i: int, dc) -> str | None:
        """Nagłówek bloku podpisu: szukamy w górę w tej samej kolumnie (max 6 linii)."""
        key = (i, round(dc.x0))
        if key in memo:
            return memo[key]
        res = None
        for j in range(i - 1, max(i - 7, -1), -1):
            cell = next((c for c in lines[j].cells if same_col(c, dc)), None)
            if cell is None:
                continue
            if accept_rx.search(cell.text):
                res = "__accept__"
                break
            if m := re.match(r"(?:W imieniu|Za)\s+(.+?):?$", cell.text):
                res = m.group(1)
                break
            if re.match(r"Mocodawc\w*\s*:?$", cell.text, re.I):
                break
            if is_dotted(cell):
                res = header_for(j, cell)
                break
        memo[key] = res
        return res

    out = []
    for i, line in enumerate(lines):
        for dc in (c for c in line.cells if is_dotted(c)):
            head = header_for(i, dc)
            # pierwsza linia pod kropkami w tej kolumnie, która jest imieniem i nazwiskiem
            for j in range(i + 1, min(i + 4, len(lines))):
                cell = next((c for c in lines[j].cells if same_col(c, dc, 20)), None)
                if cell is None:
                    continue
                if m := re.match(r"(?:Za|W imieniu)\s+(.+?):?$", cell.text):
                    head = m.group(1)
                    continue
                titled = lex.attorneys(cell.text)
                person = titled[0][1] if titled else is_person_line(cell.text)
                if person:
                    if head != "__accept__" and not titled and person not in attorneys:
                        out.append((head, person))
                    break
    return out


def extract(doc, doc_type, cfg):
    lex = Lexicon(cfg.dictionaries.get("lexicon", {}))
    opts = doc_type.raw.get("options", {})
    text = flat(doc.text)
    trace: dict = {}
    mocodawcy = _mocodawcy(text, lex, opts, trace)
    pelnomocnicy = _pelnomocnicy(text, lex, trace)
    attorneys = {p["imie_nazwisko"] for p in pelnomocnicy}
    sigs = _signatories(doc, lex, attorneys, mocodawcy, opts)
    for head, person in sigs:
        target = mocodawcy[0] if mocodawcy else None
        if head and len(mocodawcy) > 1:
            hk = head.casefold()
            target = next((m for m in mocodawcy if m["data"]["nazwa"].casefold()[:12] in hk or hk[:12] in m["data"]["nazwa"].casefold()), target)
        if target is not None and person not in [p["imie_nazwisko"] for p in target["podpisujacy"]]:
            target["podpisujacy"].append({"imie_nazwisko": person})
    trace["podpisujacy"] = [{"naglowek": h, "osoba": p} for h, p in sigs]
    return {"mocodawca": mocodawcy, "pelnomocnicy": pelnomocnicy}, trace
