"""Minimal chat service for staging. POST /chat {"case_id": optional, "message": "..."}.

Deploy to Cloud Run with authentication required (no public access).
Storage: Cloud SQL Postgres when CLOUDSQL_INSTANCE is set, otherwise local SQLite (dev only).
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from . import agent, auth, db
from .menu import MENU
from .secrets import get_secret

CON = None
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return _client


def con():
    global CON
    if CON is None:
        inst = os.environ.get("CLOUDSQL_INSTANCE")
        if inst:
            CON = db.connect_pg(f"/cloudsql/{inst}", os.environ.get("DB_NAME", "vialibera"),
                                os.environ.get("DB_USER", "app"), get_secret("DB_PASSWORD"))
        else:
            CON = db.connect(os.environ.get("DB_PATH", "/tmp/vialibera.db"))
    return CON


def handle_chat(body, llm=None, who=None):
    msg = (body.get("message") or "").strip()
    if not msg:
        return 400, {"error": "message required"}
    c = con()
    org = who["org"] if who else None
    cid = body.get("case_id")
    if cid:
        row = c.execute("SELECT org_id FROM cases WHERE id=?", (cid,)).fetchone()
        if row is None or (who and row["org_id"] != org):
            return 404, {"error": "case not found"}  # same answer for other companies' cases
    else:
        cid = db.create_case(c, int(body.get("path_type", 1)), org_id=org)
    history = db.load_history(c, cid)
    reply = agent.turn(llm or client(), c, cid, MENU, history, msg)
    db.save_history(c, cid, history)
    return 200, {"case_id": cid, "reply": reply}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {})

    def do_POST(self):
        if self.path != "/chat":
            return self._send(404, {})
        try:
            who = None
            if auth.enabled():
                try:
                    who = auth.verify(self.headers.get("Authorization"))
                except auth.AuthError:
                    return self._send(401, {"error": "unauthorized"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(*handle_chat(body, who=who))
        except Exception as e:  # keep the service up, report a typed error
            self._send(500, {"error": type(e).__name__})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler).serve_forever()
