import os, json, hmac
from http.server import BaseHTTPRequestHandler
import urllib.request


def _load_users():
    # Mirror of api/edit-auth.py. EDIT_USERS values may be a bare password
    # (role "editor") or {"pw":..., "role":...}; legacy EDIT_PASSWORD -> editor.
    raw = os.environ.get("EDIT_USERS") or os.environ.get("main_EDIT_USERS", "")
    if raw:
        try:
            d = json.loads(raw)
            if isinstance(d, dict) and d:
                out = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        pw = str(v.get("pw") or v.get("password") or "")
                        role = str(v.get("role") or "editor").lower()
                    else:
                        pw, role = str(v), "editor"
                    if role not in ("editor", "viewer"):
                        role = "editor"
                    out[str(k)] = {"pw": pw, "role": role}
                return out
        except Exception:
            pass
    pw = os.environ.get("EDIT_PASSWORD") or os.environ.get("main_EDIT_PASSWORD", "")
    if pw:
        return {"__legacy__": {"pw": pw, "role": "editor"}}
    return {}


def _require_editor(handler):
    """True only if the request carries valid editor credentials."""
    users = _load_users()
    if not users:
        return False
    user = handler.headers.get("X-Edit-User", "")
    pw = handler.headers.get("X-Edit-Password", "")
    if set(users.keys()) == {"__legacy__"}:
        rec = users["__legacy__"]
        return rec["role"] == "editor" and hmac.compare_digest(str(pw), rec["pw"])
    rec = users.get(str(user))
    if rec is None:
        hmac.compare_digest(str(pw), "x" * 32)
        return False
    return rec["role"] == "editor" and hmac.compare_digest(str(pw), rec["pw"])

SB_URL   = (os.environ.get("SUPABASE_URL") or os.environ.get("main_SUPABASE_URL", "")).rstrip("/")
SB_KEY   = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("main_SUPABASE_SERVICE_ROLE_KEY", "")
TABLE    = "notes"
ROW_ID   = "main"

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


def _set(notes):
    url = f"{SB_URL}/rest/v1/{TABLE}"
    body = json.dumps({"id": ROW_ID, "data": notes}).encode()
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
        if not _require_editor(self):
            _send(self, 401, {"error": "Editing locked — editor login required"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            notes = json.loads(self.rfile.read(length))
        except Exception:
            _send(self, 400, {"error": "Invalid JSON"})
            return
        try:
            _set(notes)
            _send(self, 200, {"ok": True})
        except Exception as e:
            _send(self, 500, {"error": str(e)})

    def log_message(self, *args):
        pass
