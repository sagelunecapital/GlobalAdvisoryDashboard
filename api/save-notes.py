import os, json
from http.server import BaseHTTPRequestHandler
import urllib.request

KV_URL   = os.environ.get("KV_REST_API_URL", "").rstrip("/")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")
KEY      = "notes"


def _kv(cmds):
    body = json.dumps(cmds).encode()
    req = urllib.request.Request(
        f"{KV_URL}/pipeline",
        data=body,
        headers={"Authorization": f"Bearer {KV_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if not KV_URL or not KV_TOKEN:
            _send(self, 503, {"error": "KV env vars not set"})
            return
        try:
            res = _kv([["GET", KEY]])
            val = res[0].get("result")
            _send(self, 200, json.loads(val) if val else {})
        except Exception as e:
            _send(self, 500, {"error": str(e)})

    def do_POST(self):
        if not KV_URL or not KV_TOKEN:
            _send(self, 503, {"error": "KV env vars not set"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            notes = json.loads(self.rfile.read(length))
        except Exception:
            _send(self, 400, {"error": "Invalid JSON"})
            return
        try:
            _kv([["SET", KEY, json.dumps(notes, ensure_ascii=False)]])
            _send(self, 200, {"ok": True})
        except Exception as e:
            _send(self, 500, {"error": str(e)})

    def log_message(self, *args):
        pass
