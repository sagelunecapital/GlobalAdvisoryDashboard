import os, json
from http.server import BaseHTTPRequestHandler
import urllib.request

SB_URL  = (os.environ.get("SUPABASE_URL") or os.environ.get("main_SUPABASE_URL", "")).rstrip("/")
SB_KEY  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("main_SUPABASE_SERVICE_ROLE_KEY", "")
TABLE   = "notes"
ROW_ID  = "journal"

HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _get():
    url = f"{SB_URL}/rest/v1/{TABLE}?id=eq.{ROW_ID}&select=data"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    r = urllib.request.urlopen(req, timeout=10)
    rows = json.loads(r.read())
    return rows[0]["data"] if rows else {}


def _set(entries):
    url = f"{SB_URL}/rest/v1/{TABLE}"
    body = json.dumps({"id": ROW_ID, "data": entries}).encode()
    hdrs = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"}
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    urllib.request.urlopen(req, timeout=10)


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
        if not SB_URL or not SB_KEY:
            _send(self, 503, {"error": "Supabase env vars not set"})
            return
        try:
            _send(self, 200, _get())
        except Exception as e:
            _send(self, 500, {"error": str(e)})

    def do_POST(self):
        if not SB_URL or not SB_KEY:
            _send(self, 503, {"error": "Supabase env vars not set"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            entries = json.loads(self.rfile.read(length))
        except Exception:
            _send(self, 400, {"error": "Invalid JSON"})
            return
        try:
            _set(entries)
            _send(self, 200, {"ok": True})
        except Exception as e:
            _send(self, 500, {"error": str(e)})

    def log_message(self, *args):
        pass
