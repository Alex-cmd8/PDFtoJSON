# Odwołania2JSON – uruchomienie oceny

## Komenda

Z katalogu `__SOL__`:

```bash
sudo bash __REPO__/deploy/run.sh
```

- Przetwarza **wszystkie pliki PDF** z `__SOL__/input` (także w podkatalogach spraw)
  i zapisuje wyniki do `__SOL__/output` – ta sama ścieżka względna i nazwa pliku, rozszerzenie `.json`.
- Dokument spoza obsługiwanych typów (odwołanie, pełnomocnictwo, potwierdzenie przelewu) → `{}`.
- Bez interakcji, kończy się sama. Na końcu wypisuje czas przetwarzania.
- Dodatkowo: ślad ekstrakcji (źródło każdej wartości) w `__SOL__/trace` – poza katalogiem wyników.

## Usługi i modele

| Element | Gdzie działa | Szczegóły |
|---|---|---|
| Model językowy | **API Mistral AI** (Francja, serwery w UE) | `ministral-8b-2512` (Ministral 3 8B, open-weight, Apache 2.0). Klucz: `MISTRAL_API_KEY` w `__SOL__/.env`. Bez klucza działają same reguły. |
| OCR skanów | **lokalnie** (bez API) | Tesseract 5 z językiem polskim (pakiet systemowy `tesseract-ocr-pol`) |
| Reguły, klasyfikacja | lokalnie | Python 3.13 (`__REPO__/.venv`), konfiguracja YAML w `__REPO__/config` |

Brak usług w tle i kontenerów – komenda niczego nie musi uruchamiać wcześniej. Wszystkie zależności
i modele są zainstalowane w `__REPO__` (instalacja: `deploy/setup_vm.sh`).

## Czas

PDF z warstwą tekstową: ułamek sekundy. Skan: ok. 3–5 s na stronę (OCR pierwszych 3 stron).
Zapytania do modelu językowego tylko dla pól, których nie ustaliły reguły.
