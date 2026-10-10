"""Local web server (127.0.0.1 only) exposing a small JSON API + single-page UI."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .i18n import t
from . import generic
from .scoring import score_signal
from .treg_client import BASE_URL, auth_headers

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".png": "image/png", ".svg": "image/svg+xml"}
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def check_token(token, org=None, lang="en"):
    """Verify a token with a free, read-only call (GET /calls)."""
    req = urllib.request.Request(f"{BASE_URL}/calls?limit=1", headers=auth_headers(token, org))
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True, t(lang, "token_ok")
    except urllib.error.HTTPError as e:
        return False, t(lang, "token_bad", code=e.code)
    except urllib.error.URLError as e:
        return False, t(lang, "token_net", reason=e.reason)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LeadSignalListener/0.1"

        def log_message(self, fmt, *args):  # keep console quiet; never log headers (token)
            pass

        # ---- helpers ----
        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ALLOWED_HOSTS  # blocks DNS-rebinding from other sites

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if not isinstance(body, (bytes, bytearray)):
                body = (json.dumps(body, ensure_ascii=False) if ctype.startswith("application/json") else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            extra = extra or {}
            if "Cache-Control" not in extra:
                self.send_header("Cache-Control", "no-store")
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self):
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("Content-Type must be application/json")
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        def _filters(self, qs):
            g = lambda k: (qs.get(k) or [None])[0]
            since = None
            if g("scope") == "last_run":  # only leads first seen in the most recent run
                last = app.store.last_run()
                since = last["started"] if last else int(time.time()) + 1
            return {"status": g("status"), "source": g("source"), "persona": g("persona"),
                    "min_score": g("min_score") or 0, "q": g("q"), "since": since}

        # ---- routes ----
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/fonts.css" or u.path.startswith("/fonts/"):
                # Only plain files inside static/, no traversal.
                rel = os.path.normpath(u.path.lstrip("/"))
                full = os.path.join(STATIC_DIR, rel)
                ext = os.path.splitext(full)[1]
                if ".." in rel.split(os.sep) or ext not in STATIC_TYPES or not os.path.isfile(full):
                    return self._send(404, {"error": "not found"})
                with open(full, "rb") as f:
                    return self._send(200, f.read(), STATIC_TYPES[ext], {"Cache-Control": "max-age=86400"})
            if u.path == "/api/config":
                cfg = app.config.public()
                cfg["project_dir"] = PROJECT_DIR  # used by the "let an agent set it up" prompt
                return self._send(200, cfg)
            if u.path == "/api/status":
                return self._send(200, {"running": app.runner.running, "last_log": app.runner.last_log,
                                        "stats": app.store.stats(), "runs": app.store.recent_runs(10),
                                        "next_run": app.next_run})
            if u.path == "/api/signals":
                f = self._filters(qs)
                limit = max(1, min(500, int((qs.get("limit") or [200])[0])))
                offset = max(0, int((qs.get("offset") or [0])[0]))
                sort = (qs.get("sort") or ["score"])[0]
                rows = app.store.list_signals(limit=limit, offset=offset, sort=sort, **f)
                # Body stays a plain list for compatibility; the total for paging rides in a header.
                return self._send(200, rows, extra={"X-Total-Count": str(app.store.count_signals(**f))})
            if u.path == "/api/catalog":
                q = (qs.get("q") or [""])[0]
                if not q:
                    return self._send(400, {"error": "q is required"})
                try:
                    return self._send(200, generic.search_catalog(q, limit=int((qs.get("limit") or [10])[0])))
                except (urllib.error.URLError, ValueError) as e:
                    return self._send(502, {"error": f"catalog search failed: {e}"})
            if u.path == "/api/export":
                fmt = (qs.get("fmt") or ["csv"])[0]
                body = app.store.export(fmt, sort=(qs.get("sort") or ["score"])[0], **self._filters(qs))
                ctype = "application/json; charset=utf-8" if fmt == "json" else "text/csv; charset=utf-8"
                name = time.strftime("signals-%Y%m%d-%H%M") + (".json" if fmt == "json" else ".csv")
                return self._send(200, body.encode("utf-8"), ctype,
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            u = urllib.parse.urlparse(self.path)
            try:
                body = self._json_body()
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            try:
                if u.path == "/api/config":
                    app.config.update(body)
                    app.reschedule()
                    return self._send(200, app.config.public())
                if u.path == "/api/test-token":
                    token = body.get("token") or app.config.token()
                    if not token or "…" in token:
                        token = app.config.token()
                    if not token:
                        return self._send(400, {"ok": False, "message": t(app.config.data.get("lang", "en"), "token_missing")})
                    ok, msg = check_token(token, app.config.data.get("treg_org") or None, app.config.data.get("lang", "en"))
                    return self._send(200, {"ok": ok, "message": msg})
                if u.path == "/api/run":
                    if app.runner.running:
                        return self._send(409, {"ok": False, "error": t(app.config.data.get("lang", "en"), "busy")})
                    threading.Thread(target=app.runner.run, daemon=True).start()
                    return self._send(202, {"ok": True, "started": True})
                if u.path == "/api/import":
                    # Let another agent or script push signals found anywhere.
                    rules = app.config.data.get("rules")
                    default_src = body.get("source", "import") if isinstance(body, dict) else "import"
                    rows = generic.normalize_imported(body, default_src)
                    for s in rows:
                        s["score"], s["persona"], s["matched"] = score_signal(s, rules)
                    return self._send(200, {"ok": True, "received": len(rows), "new": app.store.upsert_signals(rows)})
                if u.path == "/api/rescore":
                    rules = app.config.data.get("rules")
                    n = app.store.rescore_all(lambda s: score_signal(s, rules))
                    return self._send(200, {"ok": True, "rescored": n})
                if u.path.startswith("/api/signals/"):
                    sid = int(u.path.rsplit("/", 1)[1])
                    app.store.update_signal(sid, status=body.get("status"), note=body.get("note"))
                    return self._send(200, {"ok": True})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            return self._send(404, {"error": "not found"})

    return Handler


class App:
    def __init__(self, config, store, runner):
        self.config, self.store, self.runner = config, store, runner
        self.next_run = None
        self._timer_lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._scheduler, daemon=True).start()
        self.reschedule()

    def reschedule(self):
        hours = float(self.config.data.get("schedule_hours") or 0)
        with self._timer_lock:
            self.next_run = int(time.time() + hours * 3600) if hours > 0 else None

    def _scheduler(self):
        while not self._stop.wait(20):
            with self._timer_lock:
                due = self.next_run is not None and time.time() >= self.next_run
            if due:
                self.runner.run()
                self.reschedule()

    def serve(self, host="127.0.0.1", port=8787):
        httpd = ThreadingHTTPServer((host, port), make_handler(self))
        return httpd
