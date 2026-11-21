"""Ekstraktor odwołania do KIO: strony, pełnomocnik, zamówienie, zaskarżona czynność."""
from __future__ import annotations

import re

from ..engine import Engine
from ..normalize import DATE_RX, norm_date
from .common import Lexicon, PERSON_RX, flat, ids_in

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# ------------------------------------------------------------------ sekcje stron
def _sections(lines: list[str], opts: dict) -> list[tuple[str, str, list[str]]]:
    """Dzieli początek pisma na sekcje (typ, linia nagłówka, linie treści)."""
    hdr = {k: re.compile(v, re.I) for k, v in opts["section_headers"].items()}
    out: list[tuple[str, str, list[str]]] = []
    cur = None
    for ln in lines:
        kind = next((k for k, rx in hdr.items() if rx.match(ln)), None)
        if kind:
            cur = (kind, ln, [])
            out.append(cur)
            if kind == "inne" and re.match(r"(?:O\s?D\s?W|Działając)", ln, re.I):
                break
        elif cur is not None:
            cur[2].append(ln)
    return out


def _entities(header: str, body: list[str], opts: dict) -> list[dict]:
    non_name = re.compile(opts["non_name_line"], re.I)
    sub_rx = re.compile(opts["entity_subheader"], re.I)
    ents: list[dict] = []
    name_buf: list[str] = []
    sub = None
    inline = re.sub(r"^[^:]*:\s*", "", header, count=1).strip() if ":" in header else ""
    if inline and not re.search(r"konsorcjum|wykonawc|składzie", inline, re.I):
        name_buf.append(inline)
    after_sub = False
    for ln in body:
        if sub_rx.match(ln):
            sub, name_buf, after_sub = ln, [], True
            continue
        if re.search(r"składzie\s*:?$|^Konsorcjum", ln, re.I):
            continue
        if non_name.match(ln):
            if name_buf:
                ents.append({"name": " ".join(name_buf), "sub": sub, "lines": []})
                name_buf = []
            if ents:
                ents[-1]["lines"].append(ln)
            after_sub = False
            continue
        if (ents and ents[-1]["lines"] and not name_buf and not after_sub
                and _is_continuation(ents[-1]["lines"][-1], ln)):
            ents[-1]["lines"].append(ln)
            continue
        name_buf.append(ln)
    for e in ents:
        e["text"] = flat(" ".join(e["lines"]))
        e["ids"] = ids_in(e["text"])
    return ents


def _is_continuation(prev: str, ln: str) -> bool:
    """Linia zawinięta z poprzedniej (np. dalszy ciąg adresu korespondencyjnego)."""
    prev = prev.strip()
    if "@" in prev or re.match(r"(?:tel\.|e-mail|KRS|NIP|REGON)", prev, re.I):
        return False
    return bool(re.search(r"(?:,|ul\.|al\.|\b[a-ząćęłńóśźż]+)$", prev)) or bool(re.match(r"\d", ln))


# --------------------------------------------------------------------- pełnomocnik
def _attorney(ent_text: str, lex: Lexicon) -> dict:
    m = re.search(r"reprezentowan\w*\s+przez\s*:?\s*(.*?)(?=adres do korespondencji|tel\.|e-mail|$)", ent_text, re.I)
    if not m:
        return {"przez": 0, "imie_nazwisko": None, "nazwa": None, "mail": None}
    rep = m.group(1)
    found = lex.attorneys(rep)
    if found:
        person = found[0][1]
    else:
        pm = re.search(PERSON_RX, rep)
        person = pm.group("person") if pm else None
    nazwa = None
    if am := re.search(r"adres do korespondencji\s*:?\s*(.+?)(?:,\s*(?:ul\.|al\.|pl\.|os\.)|,\s*\d{2}-\d{3}|$)", ent_text, re.I):
        nazwa = am.group(1).strip(" ,")
    tail = ent_text[m.start():]
    em = EMAIL_RX.search(tail)
    return {"przez": 1, "imie_nazwisko": person, "nazwa": nazwa, "mail": em.group(0) if em else None}


# ------------------------------------------------------------- zaskarżona czynność
def _action(text: str, opts: dict, dictionary: list[dict], trace: dict) -> tuple[str | None, int | None, str | None]:
    for tier in opts["action_triggers"]:
        rxs = [re.compile(p.replace("{date}", DATE_RX), re.I) for p in tier]
        # wszystkie trafienia poziomu, w kolejności występowania w tekście
        matches = sorted((m for rx in rxs for m in rx.finditer(text)), key=lambda m: m.start())
        for m in matches:
            rest = text[m.end():]
            end = re.search(r"\.\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])", rest)
            sentence = rest[: end.start() if end else 300]
            for item in dictionary:
                if any(re.search(p, sentence, re.I) for p in item["patterns"]):
                    trace["czynnosc"] = {"regula": f"wyzwalacz: {m.re.pattern[:60]}",
                                         "zdanie": (m.group(0) + sentence)[:300], "id": item["id"]}
                    return norm_date(m.group("v")), item["id"], item["opis"]
    # zapasowo: pierwszy zarzut + pierwsza data „w dniu/z dnia”
    zm = re.search(r"zarzut\w*\s*(?:nr\s*)?1\b(.{0,400})", text, re.I | re.S)
    if zm:
        seg = zm.group(1)
        for item in dictionary:
            if any(re.search(p, seg, re.I) for p in item["patterns"]):
                dm = re.search(r"(?:w dniu|z dnia)\s+" + DATE_RX, text, re.I)
                trace["czynnosc"] = {"regula": "zarzut nr 1 (zapasowo)", "zdanie": seg[:300], "id": item["id"]}
                return (norm_date(dm.group("v")) if dm else None), item["id"], item["opis"]
    trace["czynnosc"] = {"regula": "brak dopasowania"}
    return None, None, None


def _header(doc, opts: dict) -> tuple[str | None, str | None]:
    """Linia „Miejscowość, dnia DD.MM.RRRR” na pierwszej stronie (cała komórka = miejscowość + data)."""
    rx = re.compile(rf"^\s*(?P<city>[A-ZĄĆĘŁŃÓŚŹŻ][\w\- ]{{1,40}}?),?\s+(?:dnia\s+)?{DATE_RX}"
                    r"\s*(?:r\.|roku)?\s*\.?\s*$", re.I)
    for line in doc.lines:
        if line.page > opts.get("header_max_page", 0):
            break
        for cell in line.cells:
            if m := rx.match(cell.text):
                return m.group("city").strip(), norm_date(m.group("v"))
    return None, None


def _header_zone(text: str, opts: dict) -> str:
    """Fragment pisma z danymi zamówienia: od „dotyczy” do początku uzasadnienia/żądań."""
    start = re.search(opts["zone_start"], text, re.I)
    s = start.start() if start else 0
    end = re.search(opts["zone_end"], text[s + 10:], re.I)
    return text[s: s + 10 + end.start()] if end else text[s: s + 3000]


def _party(ent: dict, extra: dict) -> dict:
    return {"krs": ent["ids"]["krs"], "nazwa": ent["name"], "nip": ent["ids"]["nip"], "regon": ent["ids"]["regon"], **extra}


def extract(doc, doc_type, cfg):
    opts = doc_type.raw.get("options", {})
    lex = Lexicon(cfg.dictionaries.get("lexicon", {}))
    dictionary = cfg.dictionaries.get("czynnosci", {}).get("czynnosci", [])
    trace: dict = {}
    text = flat(doc.text)
    lines = [l.text.replace("   ", " ").strip() for l in doc.lines]

    city, date = _header(doc, opts)
    dzien, powod_id, opis = _action(text, opts, dictionary, trace)

    secs = _sections(lines, opts)
    odw_secs = [s for s in secs if s[0] == "odwolujacy"]
    zam_secs = [s for s in secs if s[0] == "zamawiajacy"]
    leader_rx = re.compile(opts["leader_rx"], re.I)

    odwolujacy = []
    if odw_secs:
        kind, hdr, body = odw_secs[0]
        ents = _entities(hdr, body, opts)
        if ents:
            lead = next((e for e in ents if e["sub"] and leader_rx.search(e["sub"])), ents[0])
            section_text = flat(" ".join(body))
            att = _attorney(section_text, lex)
            odwolujacy.append(_party(lead, {
                "przez-pelnomocnika": att["przez"],
                "pelnomocnik": {"imie_nazwisko": att["imie_nazwisko"], "nazwa": att["nazwa"], "mail": att["mail"]},
            }))
            trace["Odwolujacy"] = {"podmioty": [e["name"] for e in ents], "lider": lead["name"]}

    zamawiajacy = []
    if zam_secs:
        kind, hdr, body = zam_secs[0]
        ents = _entities(hdr, body, opts)
        for e in ents:
            prow = None
            if len(ents) > 1:
                prow = 1 if (e["sub"] and leader_rx.search(e["sub"])) else 0
            zamawiajacy.append(_party(e, {"prowadzacy_postepowanie": prow}))
        trace["Zamawiajacy"] = {"podmioty": [e["name"] for e in ents]}

    engine = Engine(doc_type.fields)
    zone = _header_zone(text, opts)
    hits = {n: engine.extract_field(doc, n, flat=zone) for n in doc_type.fields}
    for k, h in hits.items():
        trace[k] = h.trace()

    result = {
        "OdwolanieKIO": {
            "data": date,
            "czynnosc_dzien": dzien,
            "czynnosc_powod_id": powod_id,
            "czynnosc_opis": opis,
            "miejscowosc": city,
        },
        "Odwolujacy": odwolujacy,
        "Zamawiajacy": zamawiajacy,
        "ZamowieniePubliczne": {
            "numer_bzp": hits["numer_bzp"].value,
            "numer_postepowania": hits["numer_postepowania"].value,
            "numer_ted": hits["numer_ted"].value,
            "tytul": hits["tytul"].value,
        },
    }
    return result, trace
