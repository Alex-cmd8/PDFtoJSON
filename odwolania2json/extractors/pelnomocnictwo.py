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
        # ŚCISŁO: mocodawca = nazwa, po której (przed kolejnym kandydatem) stoją jej identyfikatory;
        # bez tego nic nie zgadujemy – rozstrzygnie model językowy
        if re.search(cfg.get("not_principal_rx", r"^\s*(?:kancelaria|adwokac|radc)"), name, re.I):
            continue  # papier firmowy kancelarii pełnomocnika – to nie mocodawca
        if any(ids[k] for k in ("krs", "nip", "regon")):
            ents.append({"name": name, "ids": ids, "start": s, "end": e, "how": how, "seg": seg})
    # „pod firmą” ma pierwszeństwo przed nazwą tej samej osoby wykrytą inaczej
    out, seen = [], set()
    for ent in ents:
        key = ent["ids"]["nip"] or ent["name"]
        if key in seen:
            continue
        seen.add(key)
        # typ: z WŁASNEGO fragmentu mocodawcy (nie z całej strefy – w konsorcjum są różne typy)
        local = zone[max(0, ent["start"] - 250): ent["end"] + len(ent["seg"])]
        natural = (ent["how"] in ("pod_firma", "wyliczenie") and not ent["ids"]["krs"]) or (
            ent["how"] != "forma_prawna" and not ent["ids"]["krs"]
            and re.search(cfg["natural_person_rx"], local, re.I))
        person = None
        if natural:
            # imię i nazwisko tylko z jawnej formuły tuż przy mocodawcy; inaczej None (model językowy)
            near = zone[max(0, ent["start"] - 250): ent["end"] + 60]
            m = (re.search(r"niżej podpisan\w*\s*,?\s+" + PERSON_RX, near)
                 or re.search(r"(?:^|[\s,(])Ja\s*,\s*" + PERSON_RX, near)
                 or re.search(PERSON_RX + r"\s*,?\s*prowadząc\w* działalność", near))
            person = m.group("person") if m else None
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


def _grant_zones(text: str, cfg: dict) -> list[tuple[int, int]]:
    """Fragmenty ustanawiające pełnomocników: od frazy udzielenia do pierwszego znacznika końca."""
    zones = []
    for p in cfg["grant_phrases_attorney"]:
        for m in re.finditer(p, text, re.I):
            tail = text[m.start():m.start() + 1200]
            ends = [e.start() for q in cfg["grant_end"] if (e := re.search(q, tail[len(m.group(0)):], re.I))]
            zones.append((m.start(), m.start() + len(m.group(0)) + (min(ends) if ends else 600)))
    return zones


def _label_block_text(doc, cfg: dict) -> str:
    """Kolumna/wiersz z etykietą „Pełnomocnik / Pełnomocnicy” (układy tabelaryczne)."""
    rx = re.compile(cfg["attorney_label"], re.I)
    stop = re.compile(cfg["attorney_label_stop"], re.I)
    parts = []
    lines = doc.lines
    for i, line in enumerate(lines):
        for ci, cell in enumerate(line.cells):
            if not rx.fullmatch(cell.text.strip()):
                continue
            parts.extend(c.text for c in line.cells[ci + 1:])
            for j in range(i + 1, min(i + 6, len(lines))):
                nxt = lines[j]
                if stop.match(nxt.cells[0].text):
                    break
                parts.extend(c.text for c in nxt.cells if c.x1 >= cell.x0 - 4)
    return " ".join(parts)


def _pelnomocnicy(doc, text: str, lex: Lexicon, cfg: dict, trace: dict) -> list[dict]:
    zones = _grant_zones(text, cfg)
    sources = [text[a:b] for a, b in zones]
    sources.append(_label_block_text(doc, cfg))
    if m := re.search(cfg["accept_phrase"], text, re.I):  # blok podpisów „Pełnomocnictwo przyjmuję”
        sources.append(text[m.end():])
    found = [(i, pos, n) for i, src in enumerate(sources) for pos, n in lex.attorneys(src)]
    names = dedupe([n for _, _, n in found])
    out = []
    for n in names:
        si, pos, _ = next(f for f in found if f[2] == n)
        src = sources[si]
        # PESEL: w tym samym fragmencie, najbliższy pełnomocnik przed numerem
        pesel = None
        for pm in IDS["pesel"].finditer(src):
            owner = max((q for q, _ in lex.attorneys(src) if q < pm.start()), default=None)
            if owner == pos and pm.start() - pos < 200:
                pesel = re.sub(r"\D", "", pm.group(1))
                break
        out.append({"imie_nazwisko": n, "pesel": pesel})  # tekst – jak w danych referencyjnych
    trace["pelnomocnicy"] = {"regula": "tytuł zawodowy w strefie ustanowienia / bloku „Pełnomocnik” / podpisach",
                             "strefy": [text[a:b][:120] for a, b in zones], "znalezione": names}
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
    pelnomocnicy = _pelnomocnicy(doc, text, lex, opts, trace)
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
    # mocodawca nieodczytany (np. skan z pomieszanymi kolumnami) → pusty szkielet; pola uzupełni
    # model z walidacją w tekście. Pełnomocnictwo zawsze ma co najmniej jednego mocodawcę.
    if not mocodawcy:
        mocodawcy = [{"data": {"imie_nazwisko": None, "krs": None, "nazwa": None, "nip": None, "typ": None},
                      "podpisujacy": []}]
        trace["mocodawca_szkielet"] = True
    return {"mocodawca": mocodawcy, "pelnomocnicy": pelnomocnicy}, trace
