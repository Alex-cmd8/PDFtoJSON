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

### Interfejs WWW (wgrywanie dokumentów)

```
start_web.bat                   # http://127.0.0.1:8000 – otwiera się w przeglądarce
python web.py --port 8080 --llm-mode off
```

Lokalny serwer (tylko biblioteka standardowa Pythona, bez dodatkowych zależności).
Przeciągnij pliki PDF albo cały folder sprawy → dla każdego dokumentu:

- rozpoznany typ (po treści) albo „inny dokument → `{}`”,
- tabela pól z **źródłem każdej wartości**: ścisła reguła z YAML, model językowy
  (wartość sprawdzona w tekście) albo poprawka typowego błędu OCR,
- JSON do skopiowania / pobrania, wszystkie wyniki jako ZIP (`<sprawa>/<plik>.json`),
- ślad ekstrakcji: punkty klasyfikacji, pytania do modelu, odpowiedzi przyjęte i odrzucone.

Wyniki zapisywane są też w `output/web/<data-godzina>/`. Serwer domyślnie nasłuchuje tylko
na tym komputerze (`--host 0.0.0.0`, aby udostępnić go w sieci lokalnej).

## Ocena jakości (F1)

```
python eval/f1.py --gt dane --pred out            # podsumowanie per pole i per typ
python eval/f1.py --gt dane --pred out --details  # lista błędów
python eval/f1.py --gt dane --pred out --strict   # bez dopasowania rozmytego
```

Reguły liczenia wg organizatorów: TP/TN/FP/FN per pole, długie napisy porównywane
z progiem podobieństwa 80%. Wyniki:

| Zbiór | F1 | `--strict` |
|---|---|---|
| treningowy `dane/przyklad_*` (60 spraw, 180 PDF) | 1.000 | 1.000 |
| testy obciążeniowe `dane/test` (12 spraw, 34 PDF) | 0.957 | 418/455 pól; brakujące 37 to wyłącznie skan bez warstwy tekstowej |

```
python eval/f1.py --gt dane --pred out --cases "przyklad_*"   # tylko sprawy treningowe
```

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

## LLM: pola, których ścisłe reguły nie ustaliły

Model: **ministral-8b-2512** (Mistral AI, open-weight, Apache 2.0) przez API Mistral AI
(firma z Francji, serwery w UE). Dowolne API zgodne z OpenAI – dostawcę i model zmienia się
w `config/llm.yaml`. Model jest pytany **tylko** o:

- zaskarżoną czynność w odwołaniu, gdy nie zadziałał ścisły wzorzec „Zamawiający w dniu <data> <czynność>”
  (prompt i tryb: sekcja `llm` w `config/document_types/odwolanie.yaml`),
- pola puste po regułach (sekcja `llm_fill` w YAML każdego typu),
- typ dokumentu w „szarej strefie” klasyfikacji (np. skan zniekształcony przez OCR).

Tryby: `fallback` (domyślnie), `always` (porównanie z regułami), `off` – same reguły.

Każda odpowiedź jest walidowana: format (rachunek 26 cyfr, NIP/KRS 10 cyfr, poprawny adres e-mail,
sygnatura z separatorem…) **i obecność w tekście dokumentu** – wartości wymyślone przez model są
odrzucane. Ślad (`--trace`, zakładka „Ślad ekstrakcji” w interfejsie WWW) pokazuje pytania,
odpowiedzi przyjęte i odrzucone.
Klucz: zmienna `MISTRAL_API_KEY` lub plik `.env` (w `.gitignore`, wzór w `.env.example`).
Bez klucza działają same reguły.

```
python run.py --input dane --output out --llm-mode always --trace trace
python eval/f1.py --gt dane --pred out --details
```

## Znane ograniczenia

- **Skany bez warstwy tekstowej** (np. `szablon-aplikacja/input/case1/przyklad odwolanie.pdf`)
  nie są jeszcze obsługiwane – wymagają OCR.
- Reguły dla odwołania i pełnomocnictwa są dopasowane do układów ze zbioru treningowego;
  dokumenty rzeczywiste (etykiety stron w lewej kolumnie, anonimizacja) mogą wymagać
  wsparcia LLM dla pól semantycznych.
