import os, json, hmac
from http.server import BaseHTTPRequestHandler

# Editor credentials + roles. Two sources, checked in order:
#   EDIT_USERS    — JSON object. Each value is either:
#                     "password"                       -> role "editor" (default)
#                     {"pw": "password", "role": "..."} -> explicit role
#                   role is one of: "editor" (view + edit) | "viewer" (view only).
#   EDIT_PASSWORD — legacy single shared password (any username, role "editor").
# If neither is set, editing is locked for everyone (fail-closed).
#
# Example EDIT_USERS value:
#   {"LLS":{"pw":"secret1","role":"editor"},"BTS":{"pw":"secret2","role":"viewer"}}

VALID_ROLES = ("editor", "viewer")


def _load_users():
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
                    if role not in VALID_ROLES:
                        role = "editor"
                    out[str(k)] = {"pw": pw, "role": role}
                return out
        except Exception:
            pass
    pw = os.environ.get("EDIT_PASSWORD") or os.environ.get("main_EDIT_PASSWORD", "")
    if pw:
        # Legacy mode: any username paired with the shared password -> editor.
        return {"__legacy__": {"pw": pw, "role": "editor"}}
    return {}


def authenticate(username, password):
    """Return the user's role string on success, "" on bad creds,
    or None if editing is not configured (caller should 503)."""
    users = _load_users()
    if not users:
        return None
    if set(users.keys()) == {"__legacy__"}:
        rec = users["__legacy__"]
        return rec["role"] if hmac.compare_digest(str(password), rec["pw"]) else ""
    rec = users.get(str(username))
    if rec is None:
        # Constant-ish time even for unknown users.
        hmac.compare_digest(str(password), "x" * 32)
        return ""
    return rec["role"] if hmac.compare_digest(str(password), rec["pw"]) else ""


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
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            user = str(body.get("username", ""))
            pw = str(body.get("password", ""))
        except Exception:
            _send(self, 400, {"error": "Invalid JSON"})
            return
        role = authenticate(user, pw)
        if role is None:
            _send(self, 503, {"error": "Editing not configured (set EDIT_USERS or EDIT_PASSWORD)"})
        elif role:
            _send(self, 200, {"ok": True, "username": user, "role": role})
        else:
            _send(self, 401, {"ok": False, "error": "Incorrect username or password"})

    def log_message(self, *args):
        pass
