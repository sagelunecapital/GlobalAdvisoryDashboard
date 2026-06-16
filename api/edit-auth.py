import os, json, hmac
from http.server import BaseHTTPRequestHandler

# Shared editor password. Set EDIT_PASSWORD (or main_EDIT_PASSWORD) in the
# Vercel project environment. If unset, editing is locked for everyone
# (fail-closed) — set the env var to enable the editor login.
EDIT_PW = os.environ.get("EDIT_PASSWORD") or os.environ.get("main_EDIT_PASSWORD", "")


def _send(handler, status, data):
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if not EDIT_PW:
            _send(self, 503, {"error": "Editing not configured (EDIT_PASSWORD unset)"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            pw = str(body.get("password", ""))
        except Exception:
            _send(self, 400, {"error": "Invalid JSON"})
            return
        if hmac.compare_digest(pw, EDIT_PW):
            _send(self, 200, {"ok": True})
        else:
            _send(self, 401, {"ok": False, "error": "Incorrect password"})

    def log_message(self, *args):
        pass
