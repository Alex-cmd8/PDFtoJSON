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
    hdr = {k: re.compile(v) for k, v in opts["section_headers"].items()}
    out: list[tuple[str, str, list[str]]] = []
    cur = None
    for ln in lines:
        kind = next((k for k, rx in hdr.items() if rx.match(ln)), None)
        if kind:
            cur = (kind, ln, [])
            out.append(cur)
            if kind == "inne" and re.match(r"(?:O\s?D\s?W|Działając)", ln):
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
    # pod-nagłówek zawinięty na dwie linie: „2) Zamawiający prowadzący postępowanie w imieniu …” + „zamawiających:”
    start_rx = re.compile(opts.get("entity_subheader_start", r"^\d+\)"), re.I)
    merged: list[str] = []
    for ln in body:
        if (merged and start_rx.match(merged[-1]) and not merged[-1].rstrip().endswith(":")
                and re.match(r"[a-ząćęłńóśźż].*:\s*$", ln)):
            merged[-1] = merged[-1].rstrip() + " " + ln
        else:
            merged.append(ln)
    body = merged
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
    # „korespondencji” bywa zniekształcone przez OCR („korespondencii”); adres może być w nowej linii bez przecinka
    if am := re.search(r"adres do korespondencj?i+\s*:?\s*(.+?)(?:,?\s+(?:ul\.|al\.|pl\.|os\.)|,\s*\d{2}-\d{3}|$)", ent_text, re.I):
        nazwa = am.group(1).strip(" ,")
    tail = ent_text[m.start():]
    em = EMAIL_RX.search(tail)
    return {"przez": 1, "imie_nazwisko": person, "nazwa": nazwa, "mail": em.group(0) if em else None}


def _linearize_tables(doc_lines, cfg: dict | None) -> list[str]:
    """Tabela stron „Strona | Pole | Dane” → zwykłe linie sekcji („Odwołujący:”, „KRS: …”).

    Wiersz z 3+ komórkami zaczyna stronę (pierwsza komórka = nazwa strony z `parties`);
    wiersz z 2 komórkami (pole, wartość) należy do bieżącej strony. Wiersze pełnomocnika
    są dopisywane do sekcji odwołującego. Linie spoza tabeli zostają bez zmian.
    """
    plain = [l.text.replace("   ", " ").strip() for l in doc_lines]
    if not cfg:
        return plain
    parties = [(re.compile("^" + k, re.I), v) for k, v in cfg["parties"].items()]
    fields = [(re.compile(f"^(?:{k})$", re.I), v) for k, v in cfg["fields"].items()]

    def field_of(text):
        return next((tpl for rx, tpl in fields if rx.match(text.strip())), None)

    out, i, n = [], 0, len(doc_lines)
    while i < n:
        cells = doc_lines[i].cells
        party = next((v for rx, v in parties if rx.match(cells[0].text)), None) if len(cells) >= 3 else None
        if not (party and field_of(cells[1].text)):
            out.append(plain[i]); i += 1
            continue
        blocks: dict[str, list[str]] = {}
        order: list[str] = []
        current = None
        party_x = cells[0].x0
        while i < n:
            cells = doc_lines[i].cells
            p = next((v for rx, v in parties if rx.match(cells[0].text)), None) if len(cells) >= 3 else None
            if p and field_of(cells[1].text):
                current = p
                if p not in blocks:
                    blocks[p] = []
                    order.append(p)
                f, val = cells[1].text, " ".join(c.text for c in cells[2:])
            elif len(cells) == 2 and field_of(cells[0].text) and current:
                f, val = cells[0].text, cells[1].text
            elif len(cells) == 1 and abs(cells[0].x0 - party_x) <= 8:
                i += 1  # dalszy ciąg nazwy strony w 1. kolumnie („Pełnomocnik / Odwołującego”)
                continue
            else:
                break
            blocks[current].append(field_of(f).format(v=val))
            i += 1
        for p in order:
            if p == "pelnomocnik":
                continue
            out.append(p)
            out.extend(blocks[p])
            if p.startswith("Odwołując") and "pelnomocnik" in blocks:
                out.extend(blocks["pelnomocnik"])
    return out


# ------------------------------------------------------------- zaskarżona czynność
_SENT_END = re.compile(r"\.\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])")


def _sentence_after(text: str, pos: int, need_date: bool = False) -> str:
    """Zdanie od pozycji `pos`; jeśli trzeba daty, a jej nie ma – dołącza kolejne zdanie
    (nazwa w rodzaju „sp. z o.o. Zamawiający…” bywa fałszywym końcem zdania)."""
    rest = text[pos:]
    end = _SENT_END.search(rest)
    sent = rest[: end.start() if end else 300]
    if need_date and end and not re.search(DATE_RX, sent, re.I):
        end2 = _SENT_END.search(rest, end.end())
        sent = rest[: end2.start() if end2 else min(len(rest), 600)]
    return sent


def _classify_earliest(sentence: str, dictionary: list[dict]) -> dict | None:
    """Klasa czynności wymienionej NAJWCZEŚNIEJ w zdaniu (petitum wymienia najpierw główną)."""
    best = None
    for item in dictionary:
        for p in item["patterns"]:
            m = re.search(p, sentence, re.I)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), item)
    return best[1] if best else None


def _petitum_date(sentence: str) -> str | None:
    """Pierwsza data w zdaniu, która nie jest datą ustawy („ustawy z dnia 11 września 2019 r.”)."""
    for m in re.finditer(DATE_RX, sentence, re.I):
        if not re.search(r"ustaw\w*\s+z\s+(?:dnia\s+)?$", sentence[max(0, m.start() - 25): m.start()], re.I):
            return norm_date(m.group("v"))
    return None


def _action(text: str, opts: dict, dictionary: list[dict], trace: dict) -> tuple[str | None, int | None, str | None]:
    for tier in opts["action_triggers"]:
        if isinstance(tier, dict) and tier.get("mode") == "petitum":
            for p in tier["patterns"]:
                for m in re.finditer(p, text, re.I):
                    sentence = _sentence_after(text, m.end(), need_date=True)
                    item = _classify_earliest(sentence, dictionary)
                    if item:
                        trace["czynnosc"] = {"regula": "wyzwalacz: petitum", "zdanie": (m.group(0) + sentence)[:300],
                                             "id": item["id"]}
                        return _petitum_date(sentence), item["id"], item["opis"]
            continue
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
    # zapasowo: pierwszy zarzut + pierwsza data „w dniu/z dnia” – to ZGADYWANIE, domyślnie wyłączone
    # (lepiej null albo LLM niż pewna siebie błędna wartość); włączenie: action_fallback_zarzut: true
    zm = opts.get("action_fallback_zarzut", False) and re.search(r"zarzut\w*\s*(?:nr\s*)?1\b(.{0,400})", text, re.I | re.S)
    if zm:
        seg = zm.group(1)
        for item in dictionary:
            if any(re.search(p, seg, re.I) for p in item["patterns"]):
                dm = re.search(r"(?:w dniu|z dnia)\s+" + DATE_RX, text, re.I)
                trace["czynnosc"] = {"regula": "zarzut nr 1 (zapasowo)", "zdanie": seg[:300], "id": item["id"]}
                return (norm_date(dm.group("v")) if dm else None), item["id"], item["opis"]
    trace["czynnosc"] = {"regula": "brak dopasowania"}
    return None, None, None


_LLM = None


def _llm_client(cfg):
    global _LLM
    if _LLM is None:
        from ..llm import LLMClient
        _LLM = LLMClient(cfg.settings.get("llm", {}))
    return _LLM


def _normalize_answer(ans: dict) -> dict:
    """Klucze bez polskich znaków (model pisze czasem „czynność_powod_id”), „null” jako tekst → None,
    cytat bez formatowania Markdown."""
    import unicodedata

    def plain(k: str) -> str:
        k = unicodedata.normalize("NFKD", str(k)).replace("ł", "l").replace("Ł", "L")
        return "".join(c for c in k if not unicodedata.combining(c)).lower()

    out = {}
    for k, v in ans.items():
        if isinstance(v, str):
            v = v.replace("**", "").strip().strip('"„”')
            if v.lower() in ("", "null", "none", "brak"):
                v = None
        out[plain(k)] = v
    return out


def _date_near_quote(text: str, quote: str | None) -> str | None:
    """Pierwsza data (nie data ustawy) w zdaniu tekstu, które zawiera cytat podany przez model."""
    if not quote:
        return None
    probe = re.sub(r"\s+", " ", quote).strip()[:30]
    pos = text.find(probe) if len(probe) >= 12 else -1
    if pos < 0:
        return None
    start = max(text.rfind(". ", 0, pos), 0)
    end_m = _SENT_END.search(text, pos)
    sentence = text[start: end_m.start() + 1 if end_m else pos + 400]
    return _petitum_date(sentence)


def _action_llm_step(text, rule_result, doc_type, cfg, dictionary, trace):
    """LLM dla zaskarżonej czynności.

    Tryby (`llm.mode` w YAML typu, nadpisywane z CLI `--llm-mode`):
      off      – tylko reguły,
      fallback – LLM tylko gdy reguła wyzwalacza nie zadziałała (domyślnie),
      always   – LLM zawsze (do porównań); reguła zostaje jako zapas.
    Odpowiedź jest walidowana: id musi być w słowniku, data musi występować w tekście.
    """
    lcfg = doc_type.raw.get("llm", {})
    mode = cfg.settings.get("llm", {}).get("mode_override") or lcfg.get("mode", "off")
    rule_ok = trace.get("czynnosc", {}).get("regula", "").startswith("wyzwalacz")
    if mode == "off" or (mode == "fallback" and rule_ok):
        return rule_result
    client = _llm_client(cfg)
    classes = "\n".join(f"{c['id']}: {c['opis']}" + (f" — {c['llm_hint']}" if c.get("llm_hint") else "")
                        for c in dictionary)
    user = lcfg["user_prompt"].format(classes=classes, text=text[: lcfg.get("max_chars", 8000)])
    ans = client.chat_json(lcfg["system_prompt"], user)
    info = {"tryb": mode, "odpowiedz": ans}
    trace["czynnosc_llm"] = info
    if not isinstance(ans, dict):
        info["wynik"] = "brak odpowiedzi – zostaje reguła"
        return rule_result
    ans = _normalize_answer(ans)
    by_id = {c["id"]: c for c in dictionary}
    try:
        pid = int(ans.get("czynnosc_powod_id")) if ans.get("czynnosc_powod_id") is not None else None
    except (TypeError, ValueError):
        pid = None
    if pid not in by_id:
        info["wynik"] = f"id {pid!r} spoza słownika – zostaje reguła"
        return rule_result
    # data: tylko taka, która rzeczywiście występuje w tekście (ochrona przed halucynacją)
    dates_in_text = {norm_date(m.group("v")) for m in re.finditer(DATE_RX, text, re.I)}
    d = ans.get("czynnosc_dzien")
    if d is None:
        # model nie podał daty – szukamy cytatu w tekście i bierzemy pierwszą datę z TEGO zdania
        d = _date_near_quote(text, ans.get("cytat"))
        info["data_z_cytatu"] = d
    if isinstance(d, str) and d not in dates_in_text:
        d = norm_date(d.strip()) or d  # model bywa niekonsekwentny w formacie („02.07.2025”)
    if d not in dates_in_text:
        info["data_odrzucona"] = d
        d = rule_result[0] if rule_result[1] == pid else None
    info["wynik"] = "przyjęto"
    return d, pid, by_id[pid]["opis"]


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
    lines = _linearize_tables(doc.lines, opts.get("table_layout"))

    city, date = _header(doc, opts)
    dzien, powod_id, opis = _action(text, opts, dictionary, trace)
    dzien, powod_id, opis = _action_llm_step(text, (dzien, powod_id, opis), doc_type, cfg, dictionary, trace)

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
