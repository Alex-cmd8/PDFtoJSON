"""Ocena F1 wyników ekstrakcji względem danych referencyjnych.

Reguły (wg organizatorów, Discord UZP):
  TP – wartość jest w JSON i zgadza się z referencją (długie napisy: podobieństwo >= 80%)
  TN – brak wartości i w JSON, i w referencji
  FP – wartość tylko w JSON albo w obu, ale niepoprawna
  FN – wartość jest w referencji, a brak jej w JSON
  F1 = 2TP / (2TP + FP + FN)

Użycie:
  python eval/f1.py --gt dane --pred output [--details] [--strict]
Pliki predykcji parowane są z referencją po nazwie; aliasy pozwalają sparować
np. referencję `przelew.json` z wynikiem `potwierdzenie_przelewu.json`.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ALIASES = {"przelew": ["potwierdzenie_przelewu"]}
FUZZY_MIN_LEN = 15
FUZZY_THRESHOLD = 0.8


def _norm_str(s: str) -> str:
    s = unicodedata.normalize("NFC", s).casefold()
    s = s.replace("„", '"').replace("”", '"').replace("“", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def values_match(gt, pred, strict: bool = False) -> bool:
    if isinstance(gt, bool) or isinstance(pred, bool):
        return gt == pred
    # liczby (również zapisane jako tekst, np. PESEL)
    try:
        if isinstance(gt, (int, float)) or isinstance(pred, (int, float)):
            return abs(float(gt) - float(pred)) < 0.005
    except (TypeError, ValueError):
        return False
    g, p = _norm_str(str(gt)), _norm_str(str(pred))
    if g == p:
        return True
    if not strict and len(g) >= FUZZY_MIN_LEN and re.search(r"[a-ząćęłńóśźż]", g):
        return SequenceMatcher(None, g, p).ratio() >= FUZZY_THRESHOLD
    return False


def leaves(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from leaves(v, f"{path}[{i}]")
    else:
        yield path, x


def _align_lists(gt, pred, strict):
    """Dopasowuje elementy list predykcji do referencji (zachłannie, po liczbie zgodnych pól)."""
    if isinstance(gt, dict) and isinstance(pred, dict):
        return {k: _align_lists(gt.get(k), pred.get(k), strict) if k in gt else pred[k] for k in pred}
    if isinstance(gt, list) and isinstance(pred, list):
        remaining = list(range(len(pred)))
        out = []
        for g in gt:
            if not remaining:
                break
            best = max(remaining, key=lambda j: _score(g, pred[j], strict))
            remaining.remove(best)
            out.append(_align_lists(g, pred[best], strict))
        out.extend(pred[j] for j in remaining)
        return out
    return pred


def _score(g, p, strict):
    pd = dict(leaves(p))
    return sum(1 for k, v in leaves(g) if v is not None and k in pd and values_match(v, pd[k], strict))


def compare(gt, pred, strict=False):
    """Zwraca listę (ścieżka_bez_indeksów, wynik) dla każdego liścia."""
    pred = _align_lists(gt, pred, strict) if pred is not None else {}
    g, p = dict(leaves(gt)), dict(leaves(pred))
    out = []
    for path in list(g) + [k for k in p if k not in g]:
        gv, pv = g.get(path), p.get(path)
        if gv is None and pv is None:
            r = "TN"
        elif gv is None:
            r = "FP"
        elif pv is None:
            r = "FN"
        else:
            r = "TP" if values_match(gv, pv, strict) else "FP"
        out.append((re.sub(r"\[\d+\]", "[]", path), path, r, gv, pv))
    return out


def find_pred(pred_case: Path, gt_name: str) -> Path | None:
    for name in [gt_name] + ALIASES.get(gt_name, []):
        f = pred_case / f"{name}.json"
        if f.exists():
            return f
    return None


def load_json(f: Path):
    txt = f.read_text(encoding="utf-8").strip()
    return json.loads(txt) if txt else {}


def f1(c):
    d = 2 * c["TP"] + c["FP"] + c["FN"]
    return 2 * c["TP"] / d if d else 1.0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="dane")
    ap.add_argument("--pred", default="output")
    ap.add_argument("--details", action="store_true", help="pokaż każdy błąd")
    ap.add_argument("--strict", action="store_true", help="bez dopasowania rozmytego")
    ap.add_argument("--json-report", help="zapisz raport do pliku JSON")
    ap.add_argument("--cases", default="*", help="wzorzec nazw katalogów spraw, np. 'przyklad_*'")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    total = collections.Counter()
    by_doc = collections.defaultdict(collections.Counter)
    by_field = collections.defaultdict(collections.Counter)
    errors = []
    for case in sorted(p for p in Path(a.gt).glob(a.cases) if p.is_dir()):
        for gt_file in sorted(case.glob("*.json")):
            doc = gt_file.stem
            pf = find_pred(Path(a.pred) / case.name, doc)
            pred = load_json(pf) if pf else None
            for fpath, full, r, gv, pv in compare(load_json(gt_file), pred, a.strict):
                total[r] += 1
                by_doc[doc][r] += 1
                by_field[f"{doc}:{fpath}"][r] += 1
                if r in ("FP", "FN"):
                    errors.append((case.name, doc, full, r, gv, pv))

    print(f"{'pole':60s} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}   F1")
    for k in sorted(by_field):
        c = by_field[k]
        print(f"{k:60s} {c['TP']:4d} {c['FP']:4d} {c['FN']:4d} {c['TN']:4d}  {f1(c):.3f}")
    print()
    for d, c in sorted(by_doc.items()):
        print(f"{d:20s} F1={f1(c):.4f}  {dict(c)}")
    print(f"\nRAZEM F1={f1(total):.4f}  {dict(total)}")
    if a.details:
        print("\n=== błędy")
        for e in errors:
            print(f"{e[0]} {e[1]}:{e[2]} {e[3]}\n    gt  ={e[4]!r}\n    pred={e[5]!r}")
    if a.json_report:
        Path(a.json_report).write_text(json.dumps({
            "f1": f1(total), "counts": dict(total),
            "by_field": {k: {**v, "f1": f1(v)} for k, v in by_field.items()},
            "errors": [dict(zip(["case", "doc", "path", "type", "gt", "pred"], e)) for e in errors],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return f1(total)


if __name__ == "__main__":
    main()
