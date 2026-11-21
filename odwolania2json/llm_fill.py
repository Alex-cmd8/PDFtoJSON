"""Uzupełnianie przez model językowy pól, których ścisłe reguły nie ustaliły.

Zasada: reguły działają tylko w swoim miejscu dokumentu i na dokładnej formie; jeśli pole zostało puste,
pytamy model WYŁĄCZNIE o te pola. Odpowiedź jest przyjmowana tylko wtedy, gdy ma oparcie w tekście
(rachunek/NIP występuje w dokumencie, imię i nazwisko składa się ze słów z dokumentu itd.).
Konfiguracja – sekcja `llm_fill` w YAML typu dokumentu:

    llm_fill:
      fields:
        z_rachunku: {path: przelew_bankowy.z_rachunku, type: account, opis: "rachunek nadawcy"}
        imie_ifiz:  {path: "mocodawca[*].data.imie_nazwisko", type: person, opis: "…",
                     only_if: {"data.typ": osoba_fizyczna}, context: "data.nazwa"}
"""
from __future__ import annotations

import re
import unicodedata

from .normalize import AMOUNT_RX, DATE_RX, norm_amount, norm_date

_IDX = re.compile(r"^(?P<key>[^\[\]]+)(?:\[(?P<i>\d+|\*)\])?$")


# ----------------------------------------------------------------- ścieżki w JSON
def _get(obj, path: str):
    for part in path.split("."):
        m = _IDX.match(part)
        if obj is None or not isinstance(obj, dict):
            return None
        obj = obj.get(m.group("key"))
        if m.group("i") is not None:
            i = int(m.group("i"))
            obj = obj[i] if isinstance(obj, list) and i < len(obj) else None
    return obj


def _set(obj, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        m = _IDX.match(part)
        obj = obj[m.group("key")]
        if m.group("i") is not None:
            obj = obj[int(m.group("i"))]
    obj[parts[-1]] = value


def _expand(result: dict, spec: dict) -> list[tuple[str, str | None]]:
    """Ścieżka z [*] → konkretne ścieżki (z kontekstem elementu listy, np. nazwą mocodawcy)."""
    path = spec["path"]
    if "[*]" not in path:
        return [(path, None)]
    head, tail = path.split("[*].", 1)
    items = _get(result, head) or []
    out = []
    for i, item in enumerate(items):
        cond = spec.get("only_if", {})
        if all(_get(item, k) == v for k, v in cond.items()):
            ctx = _get(item, spec["context"]) if spec.get("context") else None
            out.append((f"{head}[{i}].{tail}", ctx))
    return out


# ------------------------------------------------------------------ walidacja
def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _ocr_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _plain(s)).translate(str.maketrans("01", "ol"))


def _validate(kind: str, value, text: str):
    """Zwraca wartość znormalizowaną albo None, gdy nie ma oparcia w tekście."""
    if value in (None, "", "null", "None"):
        return None
    digits_text = re.sub(r"\D", "", text)
    if kind == "account":
        d = re.sub(r"\D", "", str(value))
        return d if len(d) == 26 and d in digits_text else None
    if kind in ("nip", "krs"):
        d = re.sub(r"\D", "", str(value))
        return d if len(d) == 10 and d in digits_text else None
    if kind == "flag01":
        return int(value) if str(value) in ("0", "1") else None
    if kind == "date":
        d = norm_date(str(value)) or str(value)
        dates = {norm_date(m.group("v")) for m in re.finditer(DATE_RX, text, re.I)}
        return d if d in dates else None
    if kind == "email":
        # format adresu + obecność w tekście. Model bywa przepisuje zniekształcony przez OCR adres
        # („aIybak@rybak-kancelaria example”) – lepiej puste pole niż błędny adres.
        v = str(value).strip().strip(".")
        ok = re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", v, re.I)
        return v if ok and v.lower() in text.lower() else None
    if kind == "person":
        # imię i nazwisko w mianowniku: każde słowo musi mieć w tekście słowo o tym samym rdzeniu
        from .extractors.odwolanie import ORG_WORD_RX
        if ORG_WORD_RX.search(str(value)):
            return None
        words = str(value).split()
        tw = {_plain(w) for w in re.findall(r"[\w-]+", text)}
        ok = 2 <= len(words) <= 4 and all(
            any(t.startswith(_plain(w)[: max(3, len(w) - 3)]) for t in tw) for w in words)
        return " ".join(words) if ok else None
    if kind == "amount":
        # kwota musi wystąpić w tekście jako liczba (po normalizacji zapisu)
        try:
            v = round(float(str(value).replace(" ", "").replace(",", ".")), 2)
        except ValueError:
            return None
        found = {norm_amount(m.group("v")) for m in re.finditer(AMOUNT_RX, text)}
        return v if v in found else None
    if kind == "regon":
        d = re.sub(r"\D", "", str(value))
        return d if len(d) in (9, 14) and d in digits_text else None
    if kind == "pesel":
        d = re.sub(r"\D", "", str(value))
        return d if len(d) == 11 and d in digits_text else None
    if kind == "code":
        # identyfikator (numer postępowania): jeden token z cyfrą, dosłownie w tekście
        v = str(value).strip().strip(".,;")
        # sygnatura zawsze ma separator („ZP/12/2026”, „DA.ZP.242.13.2026”); samo „271” to nie numer
        return v if (re.fullmatch(r"\S{3,40}", v) and re.search(r"\d", v) and re.search(r"[./-]", v)
                     and v in text) else None
    if kind == "text":
        # porównanie bez spacji i interpunkcji, z typowymi pomyłkami OCR (0↔o, 1↔l): „Sp: z 0.0” ≈ „Sp. z o.o.”
        v = re.sub(r"\s+", " ", str(value)).strip()
        probe = _ocr_key(v)[:22]
        return v if len(probe) >= 5 and probe in _ocr_key(text) else None
    return None


def _validate_field(fs: dict, value, text: str):
    if fs["type"] == "list":
        return _validate_list(fs, value, text)
    if fs["type"] == "enum":
        return value if value in fs["values"] else None
    return _validate(fs["type"], value, text)


def _validate_list(fs: dict, value, text: str):
    """Lista obiektów: każdy element walidowany polami `item`; element bez pierwszego pola odpada."""
    if not isinstance(value, list):
        return None
    out, seen = [], set()
    first = next(iter(fs["item"]))
    for el in value:
        if not isinstance(el, dict):
            el = {first: el}
        item = {k: _validate(kind, el.get(k), text) for k, kind in fs["item"].items()}
        key = (item[first] or "").lower()
        if item[first] and key not in seen:
            seen.add(key)
            out.append(item)
    return out or None


# ------------------------------------------------------------------- główna funkcja
def fill(result: dict, doc, doc_type, cfg, trace: dict) -> dict:
    spec = doc_type.raw.get("llm_fill")
    lcfg = cfg.settings.get("llm", {})
    mode = lcfg.get("mode_override") or (spec or {}).get("mode", "fallback")
    if not spec or mode == "off" or not result:
        return result
    from .extractors.odwolanie import _llm_client  # wspólny klient (cache, limity)

    client = _llm_client(cfg)
    if not client.available:
        return result
    # pola puste po regułach
    targets = {}
    for key, fs in spec["fields"].items():
        if any(_get(result, k) == v for k, v in fs.get("skip_if", {}).items()):
            continue
        # pole wypełniamy tylko, gdy reguły nie odczytały całego bloku (np. NIP strony też pusty);
        # pusty KRS przy odczytanym bloku to prawdziwy brak, a nie luka do zgadywania
        if any(_get(result, k) is not None for k in fs.get("only_if_null", [])):
            continue
        for i, (path, ctx) in enumerate(_expand(result, fs)):
            try:
                current = _get(result, path)
            except (KeyError, IndexError, TypeError):
                continue
            parent = path.rsplit(".", 1)[0] if "." in path else None
            empty = current is None or (fs["type"] == "list" and current == [])
            if empty and (parent is None or isinstance(_get(result, parent), dict)):
                tkey = f"{key}_{i}" if "[*]" in fs["path"] else key
                targets[tkey] = (path, fs, ctx)
    if not targets:
        return result
    text = re.sub(r"\s+", " ", doc.text)
    lines = []
    for tkey, (path, fs, ctx) in targets.items():
        extra = f" (dotyczy: {ctx})" if ctx else ""
        if fs["type"] == "list":
            keys = ", ".join(f'"{k}"' for k in fs["item"])
            extra += f" – lista obiektów z kluczami {keys}"
        lines.append(f'- "{tkey}": {fs["opis"]}{extra}')
    system = spec.get("system_prompt") or lcfg["fill_system_prompt"]
    template = spec.get("user_prompt") or lcfg["fill_user_prompt"]
    user = template.format(fields="\n".join(lines), text=text[: spec.get("max_chars", 8000)])
    ans = client.chat_json(system, user)
    info = {"pytanie": list(targets), "odpowiedz": ans, "przyjete": {}, "odrzucone": {}}
    trace["llm_fill"] = info
    if not isinstance(ans, dict):
        return result
    # model pisze klucze z polskimi znakami („pełnomocnicy”, „podpisujący_0”) – porównujemy bez nich
    ans = {_plain(str(k)).replace(" ", "_"): v for k, v in ans.items()}
    for tkey, (path, fs, _) in targets.items():
        v = _validate_field(fs, ans.get(tkey), text)
        # wartość nie może powtarzać innego pola (np. zamawiający ≠ odwołujący)
        if v is not None and fs.get("not_equal"):
            other = _get(result, fs["not_equal"])
            if other and _ocr_key(str(other)) == _ocr_key(str(v)):
                v = None
        if v is not None and fs["type"] == "text" and path.endswith(".nazwa"):
            from .extractors.common import fix_legal_form
            v = fix_legal_form(v)
        if v is None:
            if ans.get(tkey) not in (None, "", "null"):
                info["odrzucone"][tkey] = ans.get(tkey)
            continue
        _set(result, path, v)
        info["przyjete"][tkey] = v
        info.setdefault("sciezki", []).append(path)
    _consistency(result, spec, info)
    return result


def _consistency(result: dict, spec: dict, info: dict) -> None:
    """Reguły spójności z YAML: `exclusive` (pola wykluczające się) i `disjoint` (rozłączne listy osób)."""
    # tylko wartości wpisane przez model w tym wywołaniu – wynik ścisłych reguł zostaje nietknięty
    filled = set(info.get("sciezki", []))
    for rule in spec.get("exclusive", []):
        if all(_get(result, k) == v for k, v in rule["if"].items()):
            for path in rule["clear"]:
                if path in filled and _get(result, path) is not None:
                    _set(result, path, None)
    dj = spec.get("disjoint")
    if dj and isinstance(_get(result, dj["list"]), list):
        head, tail = dj["against"].split("[*].", 1)
        others = {(p.get(dj["key"]) or "").casefold()
                  for item in (_get(result, head) or []) for p in (_get(item, tail) or [])}
        kept = [p for p in _get(result, dj["list"]) if (p.get(dj["key"]) or "").casefold() not in others]
        if len(kept) != len(_get(result, dj["list"])):
            info["usuniete_wspolne"] = [p for p in _get(result, dj["list"]) if p not in kept]
            _set(result, dj["list"], kept)
