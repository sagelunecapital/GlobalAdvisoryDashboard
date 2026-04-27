import os, json, base64
from http.server import BaseHTTPRequestHandler
import requests as req

GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "")    # e.g. sagelunecapital/GlobalAdvisoryDashboard
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
FILE_PATH     = "prototypes/notes.json"
GH_API        = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{FILE_PATH}"


def _get_sha():
    r = req.get(GH_API, headers={"Authorization": f"token {GITHUB_TOKEN}"},
                params={"ref": GITHUB_BRANCH}, timeout=10)
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    r.raise_for_status()


def _put_file(content_str, sha):
    body = {
        "message": "notes: user update",
        "content": base64.b64encode(content_str.encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha
    return req.put(GH_API, headers={"Authorization": f"token {GITHUB_TOKEN}",
                                     "Content-Type": "application/json"},
                   json=body, timeout=15)


def _send_json(handler, status, data):
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
        if not GITHUB_TOKEN or not GITHUB_REPO:
            _send_json(self, 503, {"error": "GITHUB_TOKEN or GITHUB_REPO env vars not set"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            notes = json.loads(self.rfile.read(length))
        except Exception:
            _send_json(self, 400, {"error": "Invalid JSON body"})
            return

        try:
            sha = _get_sha()
            r = _put_file(json.dumps(notes, indent=2, ensure_ascii=False), sha)
            if r.status_code in (200, 201):
                _send_json(self, 200, {"ok": True})
            else:
                _send_json(self, r.status_code, {"error": r.json().get("message", r.text)})
        except Exception as e:
            _send_json(self, 500, {"error": str(e)})

    def log_message(self, *args):
        pass
