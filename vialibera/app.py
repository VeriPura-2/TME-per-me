"""Minimal chat service for staging. POST /chat {"case_id": optional, "message": "..."}.

Deploy to Cloud Run with authentication required (no public access).
State is SQLite on local disk for staging only: it is lost on restart. Move to Cloud SQL before real clients.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from . import agent, db
from .menu import MENU
from .secrets import get_secret

CON = None
HISTORY = {}
_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return _client


def con():
    global CON
    if CON is None:
        import sqlite3
        CON = sqlite3.connect(os.environ.get("DB_PATH", "/tmp/vialibera.db"), check_same_thread=False)
        CON.row_factory = sqlite3.Row
        CON.executescript(db.SCHEMA)
    return CON


def handle_chat(body, llm=None):
    msg = (body.get("message") or "").strip()
    if not msg:
        return 400, {"error": "message required"}
    c = con()
    cid = body.get("case_id") or db.create_case(c, int(body.get("path_type", 1)))
    reply = agent.turn(llm or client(), c, cid, MENU, HISTORY.setdefault(cid, []), msg)
    return 200, {"case_id": cid, "reply": reply}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {})

    def do_POST(self):
        if self.path != "/chat":
            return self._send(404, {})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send(*handle_chat(body))
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
