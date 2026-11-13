"""
HTTP server on 127.0.0.1 for the app's WebView (also runs on a desktop for testing):

    python -m mobile.server --root /some/folder --port 8765

Only the page itself is served without the session token; every /api and /files request
must carry it, so other apps on the phone cannot read or drive the scanner.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from mobile import alerts, api, jobs, resources

TOKEN = os.environ.get("EW_SERVER_TOKEN") or secrets.token_urlsafe(24)    # env: desktop testing only
_server: Optional[ThreadingHTTPServer] = None


GET: dict[str, Callable[[dict], Any]] = {
    "/api/state": lambda q: api.state(),
    "/api/prefs": lambda q: api.get_prefs(q.get("key", "ew5")),
    "/api/data": lambda q: api.data_summary(),
    "/api/tickers": lambda q: api.get_tickers(),
    "/api/run/options": lambda q: api.run_options(),
    "/api/run/last": lambda q: api.last_run(),
    "/api/job": lambda q: {"job": jobs.current()},
    "/api/guide": lambda q: api.guide(),
    "/api/alerts": lambda q: api.alerts_overview(),
}
POST: dict[str, Callable[[dict], Any]] = {
    "/api/prefs/save": lambda b: api.save_prefs(b["key"], b["prefs"]),
    "/api/dashboard": api.dashboard,
    "/api/chart": api.chart,
    "/api/data/preview": api.data_preview,
    "/api/data/update": api.start_update,
    "/api/data/weekly": lambda b: api.start_weekly(),
    "/api/data/import": lambda b: api.start_import(),
    "/api/tickers": lambda b: api.save_tickers(b.get("text", "")),
    "/api/run/check": api.run_check,
    "/api/run": api.start_run,
    "/api/alerts/settings": api.alerts_save,
    "/api/alerts/run": lambda b: api.alerts_run(),
    "/api/alerts/test": lambda b: alerts.test_notification(),
    "/api/alerts/telegram_test": api.alerts_telegram_test,
    "/api/alerts/telegram_chat": api.alerts_telegram_chat,
    "/api/alerts/telegram_preview": api.alerts_telegram_preview,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "EWScanner"

    def log_message(self, fmt: str, *args: Any) -> None:       # keep logcat quiet
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _authorised(self, query: dict) -> bool:
        return secrets.compare_digest(self.headers.get("X-Token") or query.get("t", ""), TOKEN)

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        if name == "plotly.min.js":
            body = resources.plotly_js()
        elif "/" in name or name.startswith("."):          # only the page's own flat files
            body = None
        else:
            body = resources.read(f"web/{name}")
        if body is None:
            self._send(404, b"not found", "text/plain")
            return
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        cache = {"Cache-Control": "max-age=86400"} if name == "plotly.min.js" else None
        self._send(200, body, ctype, cache)

    def _call(self, fn: Callable[[Any], Any], arg: Any) -> None:
        try:
            self._json(200, fn(arg))
        except (ValueError, RuntimeError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()})

    # ---------------------------------------------------------------- verbs
    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in GET:
            if not self._authorised(query):
                return self._json(403, {"error": "forbidden"})
            return self._call(GET[url.path], query)
        if url.path.startswith("/files/results/"):
            if not self._authorised(query):
                return self._json(403, {"error": "forbidden"})
            path = api.result_path(unquote(url.path.rsplit("/", 1)[-1]))
            if path is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, path.read_bytes(), "text/csv",
                              {"Content-Disposition": f'attachment; filename="{path.name}"'})
        return self._static(url.path)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path not in POST:
            return self._json(404, {"error": "not found"})
        if not self._authorised({}):
            return self._json(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad JSON"})
        self._call(POST[url.path], body)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind also does a reverse DNS lookup of the host (socket.getfqdn),
        # which can hang for a long time without network. It is only used for logging.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


FIXED_PORTS = range(47651, 47661)       # same address every launch: the WebView keeps its cache and settings


def _bind(port: int) -> "Server":
    for p in ([port] if port else list(FIXED_PORTS)) + [0]:
        try:
            return Server(("127.0.0.1", p), Handler)
        except OSError:
            continue
    raise OSError("no free port")


def start(root: str, port: int = 0) -> str:
    """Start in a background thread; returns the page URL (with the session token)."""
    global _server
    if _server is None:
        api.init(root)
        _server = _bind(int(port))
        _server.daemon_threads = True
        threading.Thread(target=_server.serve_forever, name="http", daemon=True).start()
        threading.Thread(target=api.warm_up, name="warm-up", daemon=True).start()
    return f"http://127.0.0.1:{_server.server_address[1]}/?t={TOKEN}"


def scheduled(root: str) -> str:
    """Called by app.ewscanner.JobService when a scheduled time comes (app may have been closed)."""
    start(root)
    return json.dumps(alerts.run(api._app(), source="schedule"), default=str)


def results_dir() -> str:
    return str(api._app().cfg["results_dir"])


def import_target() -> str:
    """Where the Android file picker copies a stock.csv before the import job splits it."""
    path = api._app().root / "data" / "import_stock.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the phone UI on a desktop for testing")
    parser.add_argument("--root", required=True, help="folder that plays the app's storage")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(start(os.path.abspath(args.root), args.port), flush=True)
    threading.Event().wait()
