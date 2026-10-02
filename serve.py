"""Nyon Derma preview server: serves the site and the messages API (contact form, admin inbox, email replies).

Run:  python serve.py      then open http://localhost:5510
Config: copy .env.example to .env (admin password, SMTP email settings). See README.md.
"""
import hmac
import http.server
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from http.cookies import SimpleCookie

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from backend import api  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.store import Store  # noqa: E402

DEFAULT_PORT = 5510
COOKIE = "nyon_admin"
SESSION_SECONDS = 8 * 3600
MAX_BODY = 20_000
# Never serve these, even though they live in the site folder.
PRIVATE_DIRS = {"data", "backend", "tests", "outbox", "__pycache__"}


class App:
    """Shared state for all request threads: config, database, sessions and rate limits."""

    def __init__(self, config):
        self.config = config
        self.store = Store(config.data_dir)
        self.sessions = {}
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def check_password(self, attempt):
        return hmac.compare_digest(attempt.encode(), self.config.admin_password.encode())

    def new_session(self):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = time.time() + SESSION_SECONDS
        return token

    def valid_session(self, token):
        with self.lock:
            exp = self.sessions.get(token or "")
            if exp and exp > time.time():
                return True
            self.sessions.pop(token or "", None)
            return False

    def end_session(self, token):
        with self.lock:
            self.sessions.pop(token or "", None)

    def allow(self, ip, bucket, per_minute=None):
        limit = per_minute or self.config.rate_limit_per_minute
        now = time.time()
        with self.lock:
            q = self.hits[(ip, bucket)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


def is_private(url_path):
    parts = [p for p in urllib.parse.unquote(url_path).split("?")[0].split("/") if p]
    if not parts:
        return False
    return parts[0] in PRIVATE_DIRS or any(p.startswith(".") for p in parts) or parts[-1].endswith(".py")


class Handler(http.server.SimpleHTTPRequestHandler):
    app = None  # set by make_server

    def log_message(self, fmt, *args):
        if os.environ.get("QUIET_LOG") != "1":
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        page = os.path.join(self.directory, "404.html")
        if code == 404 and os.path.exists(page):
            with open(page, "rb") as f:
                body = f.read()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    # ---------- routing
    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.handle_api("GET")
        if is_private(self.path):
            return self.send_error(404)
        return super().do_GET()

    def do_HEAD(self):
        if is_private(self.path):
            return self.send_error(404)
        return super().do_HEAD()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.handle_api("POST")
        return self.send_error(405)

    def handle_api(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        for m, pattern, handler, admin_only in api.ROUTES:
            match = re.match(pattern, parsed.path)
            if m == method and match:
                break
        else:
            return self.send_json(404, {"error": "Not found."})

        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.send_json(413, {"error": "Message is too long."})
            # JSON-only POSTs: plain HTML forms on other sites can't send this content type (CSRF guard).
            if self.headers.get_content_type() != "application/json":
                return self.send_json(415, {"error": "Send JSON."})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"error": "Invalid JSON."})

        token = self.cookie_token()
        is_admin = self.app.valid_session(token)
        if admin_only and not is_admin:
            return self.send_json(401, {"error": "Sign in to the admin to continue."})

        req = api.Request(method, parsed.path, query, body, self.client_address[0], is_admin, match.groupdict())
        status, payload = handler(self.app, req)
        cookie = None
        if "_session" in payload:
            cookie = self.session_cookie(payload.pop("_session"), SESSION_SECONDS)
        if payload.pop("_end_session", False):
            self.app.end_session(token)
            cookie = self.session_cookie("", 0)
        self.send_json(status, payload, cookie)

    # ---------- helpers
    def cookie_token(self):
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        return jar[COOKIE].value if COOKIE in jar else ""

    def session_cookie(self, value, max_age):
        secure = "; Secure" if self.app.config.site_url.startswith("https://") else ""
        return f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"

    def send_json(self, status, payload, cookie=None):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)


def make_server(port, root, config):
    app = App(config)
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = http.server.ThreadingHTTPServer(("", port), lambda *a, **kw: handler(*a, directory=root, **kw))
    server.daemon_threads = True
    server.app = app
    close = server.server_close
    server.server_close = lambda: (close(), app.store.close())
    return server


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    config = Config.from_env(HERE, port)
    httpd = make_server(port, HERE, config)
    print(f"Serving on http://localhost:{port}")
    print(f"Admin messages: {'SMTP ' + config.smtp_host if config.email_enabled else 'email not configured, replies saved to ' + config.outbox_dir}")
    if config.generated_password:
        print(f"ADMIN_PASSWORD not set. One-off admin password for this run: {config.admin_password}")
    httpd.serve_forever()
