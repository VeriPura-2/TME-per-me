"""Minimal chat service for staging. POST /chat {"case_id": optional, "message": "..."}.

Deploy to Cloud Run with authentication required (no public access).
Storage: Cloud SQL Postgres when CLOUDSQL_INSTANCE is set, otherwise local SQLite (dev only).
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from . import accounts, agent, auth, db
from .menu import MENU
from .secrets import get_secret

TERMS_VERSION = "2026-10-v0.1"
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
    if who and not accounts.has_consent(c, who["user"], TERMS_VERSION):
        return 403, {"error": "consent_required", "terms_version": TERMS_VERSION}
    lang = "en" if body.get("lang") == "en" else "it"
    cid = body.get("case_id")
    if cid:
        row = c.execute("SELECT owner_sub, company_id, org_id FROM cases WHERE id=?", (cid,)).fetchone()
        if row is None or not accounts.can_access(c, row, who):
            return 404, {"error": "case not found"}  # same answer for other people's cases
    else:
        cid = db.create_case(c, int(body.get("path_type", 1)), org_id=(who or {}).get("org"),
                             owner_sub=who["user"] if who else None)
    history = db.load_history(c, cid)
    reply = agent.turn(llm or client(), c, cid, MENU, history, msg, lang=lang)
    db.save_history(c, cid, history)
    out = {"case_id": cid, "reply": reply,
           "persona": agent.persona_for(db.case_read(c, cid)["path_type"])}
    notice = accounts.attach_company(c, cid, who)
    if notice:
        out["account"] = notice
    return 200, out


def handle_consent(body, who):
    if not who:
        return 400, {"error": "sign-in required"}
    if not (body.get("accept_terms") and body.get("accept_onerous")):
        return 400, {"error": "both acceptances required"}
    accounts.record_consent(con(), who["user"], TERMS_VERSION, "en" if body.get("lang") == "en" else "it", True)
    return 200, {"ok": True, "terms_version": TERMS_VERSION}


def render_terms(lang):
    import markdown
    name = "en" if lang == "en" else "it"
    path = os.path.join(os.path.dirname(__file__), "static", f"terms_{name}.md")
    body = markdown.markdown(open(path, encoding="utf-8").read(), extensions=["tables"])
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<style>body{font:16px/1.6 system-ui;max-width:760px;margin:0 auto;padding:16px}"
            "@media(prefers-color-scheme:dark){body{background:#121212;color:#e8e8e8}a{color:#8ab4f8}}</style>"
            + body).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self._send(200, {"ok": True})
        if path == "/config.json":  # public values only
            return self._send(200, {"domain": os.environ.get("AUTH0_DOMAIN", ""),
                                    "client_id": os.environ.get("AUTH0_CLIENT_ID", ""),
                                    "audience": os.environ.get("AUTH0_AUDIENCE", ""),
                                    "default_org": os.environ.get("AUTH0_DEFAULT_ORG", ""),
                                    "terms_version": TERMS_VERSION})
        if path in ("/terms", "/terms.html"):
            data = render_terms(self.path.split("lang=")[-1][:2] if "lang=" in self.path else "it")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if path == "/":
            data = open(os.path.join(os.path.dirname(__file__), "static", "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        self._send(404, {})

    def do_POST(self):
        if self.path not in ("/chat", "/consent", "/me"):
            return self._send(404, {})
        try:
            who = None
            if auth.enabled():
                try:
                    who = auth.verify(self.headers.get("Authorization"))
                except auth.AuthError:
                    return self._send(401, {"error": "unauthorized"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/consent":
                return self._send(*handle_consent(body, who))
            if self.path == "/me":
                ok = bool(who) and accounts.has_consent(con(), who["user"], TERMS_VERSION)
                latest = None
                if who:
                    r = con().execute("SELECT id FROM cases WHERE owner_sub=? ORDER BY created_at DESC LIMIT 1",
                                      (who["user"],)).fetchone()
                    latest = r["id"] if r else None
                return self._send(200, {"consent": ok or not who, "terms_version": TERMS_VERSION,
                                        "latest_case": latest})
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
