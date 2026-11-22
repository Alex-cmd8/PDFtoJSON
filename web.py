"""Odwołania2JSON – lokalny interfejs WWW (tylko biblioteka standardowa Pythona).

    python web.py                 # http://127.0.0.1:8000
    python web.py --port 8080 --llm-mode off

Wgraj pliki PDF (albo cały folder sprawy) → JSON dla każdego dokumentu + ślad ekstrakcji
(skąd pochodzi każda wartość: reguła, strona, fragment tekstu, odpowiedź modelu).
Wyniki zapisywane są też w output/web/<znacznik czasu>/<sprawa>/<plik>.json.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import logging
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from email.parser import BytesParser
from email.policy import HTTP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

from odwolania2json.config import DEFAULT_CONFIG_DIR, load_config
from odwolania2json.llm import load_dotenv
from odwolania2json.pipeline import environment_warnings, process_pdf

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "odwolania2json" / "web" / "index.html"
MAX_UPLOAD = 200 * 1024 * 1024  # 200 MB na jedno wysłanie
log = logging.getLogger("odwolania2json.web")


def _safe_rel(name: str) -> PurePosixPath:
    """Ścieżka względna z formularza („sprawa1/odwolanie.pdf”) bez „..”, liter dysków i znaków sterujących."""
    parts = [re.sub(r'[<>:"|?*\x00-\x1f]', "_", p) for p in re.split(r"[\\/]+", name)
             if p not in ("", ".", "..")]
    return PurePosixPath(*parts[-2:]) if parts else PurePosixPath("dokument.pdf")


class App:
    def __init__(self, cfg, out_root: Path):
        self.cfg = cfg
        self.out_root = out_root
        self.lock = threading.Lock()  # OCR i klient LLM są współdzielone – przetwarzamy po kolei
        self.batches: dict[str, list[dict]] = {}

    def status(self) -> dict:
        from odwolania2json.extractors.odwolanie import _llm_client
        llm = _llm_client(self.cfg)
        lcfg = self.cfg.settings.get("llm", {})
        # sprawdzamy tylko instalację – import easyocr/torch trwa kilka sekund
        from odwolania2json import ocr as ocr_mod
        ocfg = self.cfg.settings.get("ocr", {})
        ocr = bool(ocfg.get("enabled", True)) and ocr_mod.available(ocfg)
        return {"llm": {"available": llm.available, "model": llm.model,
                        "mode": lcfg.get("mode_override") or "fallback"},
                "ocr": ocr, "types": sorted(self.cfg.doc_types)}

    def process(self, files: list[tuple[str, bytes]]) -> dict:
        batch = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        items = []
        tmp = Path(tempfile.mkdtemp(prefix="o2j_"))
        try:
            with self.lock:
                for name, data in files:
                    rel = _safe_rel(name)
                    if rel.suffix.lower() != ".pdf":
                        continue
                    pdf = tmp / rel
                    pdf.parent.mkdir(parents=True, exist_ok=True)
                    pdf.write_bytes(data)
                    t0 = time.time()
                    try:
                        result, trace = process_pdf(pdf, self.cfg)
                        error = None
                    except Exception:
                        log.exception("Błąd przetwarzania %s", rel)
                        result, trace, error = {}, {}, traceback.format_exc(limit=3)
                    trace.pop("file", None)
                    out = self.out_root / batch / rel.with_suffix(".json")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    items.append({"name": str(rel), "json_name": str(rel.with_suffix(".json")),
                                  "doc_type": trace.get("doc_type"), "seconds": round(time.time() - t0, 1),
                                  "ocr_pages": trace.get("ocr_pages", 0), "result": result,
                                  "trace": trace, "error": error})
                    log.info("%-50s -> %s (%.1fs)", rel, trace.get("doc_type"), time.time() - t0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.batches[batch] = items
        return {"batch": batch, "output_dir": str(self.out_root / batch), "items": items}

    def zip_batch(self, batch: str) -> bytes | None:
        items = self.batches.get(batch)
        if items is None:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for it in items:
                z.writestr(it["json_name"], json.dumps(it["result"], ensure_ascii=False, indent=2))
        return buf.getvalue()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Odwolania2JSON"

        def log_message(self, fmt, *args):  # ciszej niż domyślnie
            log.debug(fmt, *args)

        def _send(self, code, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=HTTPStatus.OK):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(app.status())
            elif m := re.fullmatch(r"/api/batch/([\w-]+)\.zip", self.path):
                data = app.zip_batch(m.group(1))
                if data is None:
                    self._json({"error": "nie ma takiej partii"}, HTTPStatus.NOT_FOUND)
                else:
                    self._send(HTTPStatus.OK, data, "application/zip",
                               {"Content-Disposition": f'attachment; filename="odwolania2json-{m.group(1)}.zip"'})
            else:
                self._json({"error": "nie znaleziono"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if self.path != "/api/process":
                return self._json({"error": "nie znaleziono"}, HTTPStatus.NOT_FOUND)
            length = int(self.headers.get("Content-Length") or 0)
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                return self._json({"error": "oczekiwano multipart/form-data"}, HTTPStatus.BAD_REQUEST)
            if length <= 0 or length > MAX_UPLOAD:
                return self._json({"error": f"rozmiar 1 B – {MAX_UPLOAD // 2**20} MB"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            body = self.rfile.read(length)
            msg = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {ctype}\r\n\r\n".encode() + body)
            files = [(part.get_filename() or "dokument.pdf", part.get_payload(decode=True) or b"")
                     for part in msg.iter_parts() if part.get_filename()]
            if not files:
                return self._json({"error": "brak plików"}, HTTPStatus.BAD_REQUEST)
            self._json(app.process(files))

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Odwołania2JSON – interfejs WWW")
    ap.add_argument("--host", default="127.0.0.1", help="adres nasłuchu (domyślnie tylko ten komputer)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG_DIR))
    ap.add_argument("--output", default=str(ROOT / "output" / "web"))
    ap.add_argument("--llm-mode", choices=["off", "fallback", "always"])
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    cfg = load_config(a.config)
    if a.llm_mode:
        cfg.settings.setdefault("llm", {})["mode_override"] = a.llm_mode
    for w in environment_warnings(cfg):
        print(f"UWAGA: {w}")
    app = App(cfg, Path(a.output))
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(app))
    print(f"Odwołania2JSON: http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}  (Ctrl+C – koniec)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
