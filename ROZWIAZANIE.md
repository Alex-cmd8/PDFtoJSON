# Odwołania2JSON – rozwiązanie

Ekstrakcja danych z dokumentów sprawy odwoławczej KIO (odwołanie, pełnomocnictwo,
potwierdzenie przelewu) do JSON. Rdzeń działa **bez LLM i bez GPU** – na regułach
sterowanych konfiguracją YAML; każda wartość ma ślad, skąd została wzięta.

## Uruchomienie

```
start.bat                       # input\<sprawa>\*.pdf -> output\<sprawa>\*.json
start.bat --trace trace         # dodatkowo ślady ekstrakcji w trace\
python run.py --input dane --output out
```

Wymagania: Python 3.13+, `pip install -r requirements.txt`.

## Ocena jakości (F1)

```
python eval/f1.py --gt dane --pred out            # podsumowanie per pole i per typ
python eval/f1.py --gt dane --pred out --details  # lista błędów
python eval/f1.py --gt dane --pred out --strict   # bez dopasowania rozmytego
```

Reguły liczenia wg organizatorów: TP/TN/FP/FN per pole, długie napisy porównywane
z progiem podobieństwa 80%. Wynik na zbiorze treningowym (60 spraw, 180 PDF):
**F1 = 1.000** (tryb `--strict`: 0.9998).

## Architektura

```
PDF ─► pdftext (linie + kolumny z pozycji słów)
    ─► classify (ważone reguły z YAML; poniżej progu → pusty JSON)
    ─► ekstraktor typu:
         rules           – generyczny silnik „etykieta → wartość” (tylko YAML)
         pelnomocnictwo  – mocodawcy/konsorcjum, podpisy pod kropkami, pełnomocnicy
         odwolanie       – sekcje stron, lider konsorcjum, zaskarżona czynność
    ─► JSON + ślad (reguła, strona, fragment tekstu)
```

| Katalog | Zawartość |
|---|---|
| `config/document_types/*.yaml` | jeden plik = jeden typ dokumentu: klasyfikacja, pola, szablon wyjścia |
| `config/dictionaries/czynnosci.yaml` | słownik zaskarżonych czynności (id → opis + wzorce) |
| `config/dictionaries/lexicon.yaml` | formy prawne, tytuły pełnomocników, słowa-stopery |
| `odwolania2json/` | kod: ekstrakcja tekstu, silnik reguł, klasyfikator, ekstraktory |
| `eval/f1.py` | skrypt oceny F1 |

### Nowy typ dokumentu bez zmiany kodu

Dodaj `config/document_types/<typ>.yaml` z `extractor: rules`, regułami `classify`,
polami (`labels` / `patterns` / `type`) i szablonem `output`. Wzorem jest `przelew.yaml`,
który obsługuje ~15 różnych szablonów bankowych wyłącznie konfiguracją.

## Znane ograniczenia

- **Skany bez warstwy tekstowej** (np. `szablon-aplikacja/input/case1/przyklad odwolanie.pdf`)
  nie są jeszcze obsługiwane – wymagają OCR.
- Reguły dla odwołania i pełnomocnictwa są dopasowane do układów ze zbioru treningowego;
  dokumenty rzeczywiste (etykiety stron w lewej kolumnie, anonimizacja) mogą wymagać
  wsparcia LLM dla pól semantycznych.
