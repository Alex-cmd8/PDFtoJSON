"""Minimalny klient LLM (API zgodne z OpenAI chat completions) – tylko biblioteka standardowa.

Odpowiedź oczekiwana w JSON. Wyniki są cache'owane na dysku, więc ponowne uruchomienie
na tych samych dokumentach nie wysyła zapytań. Brak dostępu lub błąd sieci → None
(ekstrakcja wraca do wyniku reguł).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("odwolania2json.llm")
ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Wczytuje KLUCZ=wartość z pliku .env (puste wartości i istniejące zmienne są pomijane)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)


def _parse_json(content: str) -> dict | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)  # model dodał tekst wokół JSON-a
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


class LLMClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.model = self.cfg.get("model", "mistral-small-latest")
        self.base_url = self.cfg.get("base_url", "https://api.mistral.ai/v1").rstrip("/")
        self.cache = ROOT / self.cfg.get("cache_dir", ".llm_cache")
        self.calls = 0
        self._last_call = 0.0

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.cfg.get("api_key_env", "MISTRAL_API_KEY")) or None

    @property
    def available(self) -> bool:
        return bool(self.api_key) or bool(self.cfg.get("allow_anonymous"))

    def _throttle(self) -> None:
        """Odstęp między zapytaniami: `min_interval` (limit planu), bez klucza `anonymous_min_interval`."""
        interval = self.cfg.get("min_interval", 0) if self.api_key else self.cfg.get("anonymous_min_interval", 0)
        wait = interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def chat_json(self, system: str, user: str) -> dict | None:
        key = hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()
        cached = self.cache / f"{key}.json"
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        if not self.available:
            return None
        payload = {
            "model": self.model,
            "temperature": self.cfg.get("temperature", 0),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.cfg.get("json_mode", True):
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        retries = self.cfg.get("max_retries", 3)
        for attempt in range(retries):
            self._throttle()
            req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                         data=json.dumps(payload).encode(), method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.get("timeout", 60)) as r:
                    data = json.loads(r.read())
                self.calls += 1
                out = _parse_json(data["choices"][0]["message"].get("content") or "")
                if out is None:
                    log.warning("LLM: odpowiedź nie jest JSON-em")
                    return None
                self.cache.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                return out
            except urllib.error.HTTPError as e:
                body = e.read()[:300]
                if e.code == 400 and "response_format" in payload:  # dostawca bez trybu JSON
                    payload.pop("response_format")
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                    time.sleep(min(60, 2 ** attempt * 15))
                    continue
                log.warning("LLM HTTP %s: %s", e.code, body)
                return None
            except (urllib.error.URLError, TimeoutError, KeyError) as e:
                log.warning("LLM błąd: %s", e)
                return None
        return None
