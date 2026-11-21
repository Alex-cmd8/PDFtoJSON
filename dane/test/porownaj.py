# -*- coding: utf-8 -*-
"""
Porównuje JSON-y zwrócone przez parser z oczekiwanymi JSON-ami z dane/test.

Użycie:
    python porownaj.py <katalog_test> <katalog_wynikow_parsera>

Oczekiwany układ wyników parsera (taki sam jak w dane/test):
    <katalog_wynikow_parsera>/test_XX_.../odwolanie.json
    <katalog_wynikow_parsera>/test_XX_.../pelnomocnictwo.json
    <katalog_wynikow_parsera>/test_XX_.../przelew.json

Porównanie jest ścisłe (wartość i typ), z dwoma wyjątkami:
  * stringi porównywane po złączeniu wielokrotnych białych znaków w jedną spację i obcięciu brzegów,
  * liczby: 17 == 17.0.
Wypisuje każdą różnicę ze ścieżką pola oraz podsumowanie: trafione pola / wszystkie pola.
"""
import json, os, re, sys


def norm(v):
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip()
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def diff(exp, got, path, out):
    """Zwraca (trafione, wszystkie) liście; różnice dopisuje do out."""
    if isinstance(exp, dict):
        if not isinstance(got, dict):
            out.append(f"{path}: oczekiwano obiektu, jest {type(got).__name__}")
            return 0, count_leaves(exp)
        ok = tot = 0
        for k, v in exp.items():
            a, b = diff(v, got.get(k, _MISSING), f"{path}.{k}", out)
            ok += a; tot += b
        for k in got:
            if k not in exp:
                out.append(f"{path}.{k}: nadmiarowe pole")
        return ok, tot
    if isinstance(exp, list):
        if not isinstance(got, list):
            out.append(f"{path}: oczekiwano listy, jest {type(got).__name__ if got is not _MISSING else 'BRAK'}")
            return 0, count_leaves(exp)
        if len(got) != len(exp):
            out.append(f"{path}: długość listy {len(got)} != oczekiwana {len(exp)}")
        ok = tot = 0
        for i, v in enumerate(exp):
            a, b = diff(v, got[i] if i < len(got) else _MISSING, f"{path}[{i}]", out)
            ok += a; tot += b
        return ok, tot
    if got is _MISSING:
        out.append(f"{path}: BRAK pola (oczekiwano {exp!r})")
        return 0, 1
    if norm(exp) == norm(got) and (exp is None) == (got is None):
        return 1, 1
    out.append(f"{path}: {got!r} != oczekiwane {exp!r}")
    return 0, 1


def count_leaves(o):
    if isinstance(o, dict):
        return sum(count_leaves(v) for v in o.values()) or 1
    if isinstance(o, list):
        return sum(count_leaves(v) for v in o) or 1
    return 1


class _Missing:
    def __repr__(self):
        return "BRAK"


_MISSING = _Missing()


def main(exp_root, got_root):
    total_ok = total = 0
    for case in sorted(d for d in os.listdir(exp_root) if d.startswith("test_")):
        cdir = os.path.join(exp_root, case)
        for jf in sorted(f for f in os.listdir(cdir) if f.endswith(".json")):
            exp = json.load(open(os.path.join(cdir, jf), encoding="utf-8"))
            gp = os.path.join(got_root, case, jf)
            out = []
            if not os.path.exists(gp):
                ok, tot = 0, count_leaves(exp)
                out.append("brak pliku wynikowego")
            else:
                try:
                    got = json.load(open(gp, encoding="utf-8"))
                    ok, tot = diff(exp, got, "$", out)
                except json.JSONDecodeError as e:
                    ok, tot = 0, count_leaves(exp)
                    out.append(f"niepoprawny JSON: {e}")
            total_ok += ok; total += tot
            status = "OK  " if not out else "FAIL"
            print(f"[{status}] {case}/{jf}  {ok}/{tot}")
            for line in out:
                print("        " + line)
    print(f"\nRAZEM: {total_ok}/{total} pól ({100.0 * total_ok / max(total, 1):.1f}%)")
    return 0 if total_ok == total else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
