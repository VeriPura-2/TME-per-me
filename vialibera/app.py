"""Minimal chat service for staging. POST /chat {"case_id": optional, "message": "..."}.

Deploy to Cloud Run with authentication required (no public access).
Storage: Cloud SQL Postgres when CLOUDSQL_INSTANCE is set, otherwise local SQLite (dev only).
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from urllib.parse import parse_qs, urlparse

from . import accounts, agent, auth, db, docs, features, invites, personas, plans, storage, voice
from .menu import MENU
from .secrets import get_secret

TERMS_VERSION = "2026-10-v0.3"
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
    pid = None
    if who:
        prof = accounts.get_profile(c, who["user"])
        pid = prof["persona_id"]
        if not pid:
            path = c.execute("SELECT path_type FROM cases WHERE id=?", (cid,)).fetchone()["path_type"]
            pid = personas.pick(who["user"], prof["style"], path)["id"]
            accounts.save_profile(c, who["user"], persona_id=pid)
    reply = agent.turn(llm or client(), c, cid, MENU, history, msg, lang=lang, persona_id=pid)
    db.save_history(c, cid, history)
    out = {"case_id": cid, "reply": reply,
           "persona": {"id": pid, "name": personas.BY_ID[pid]["name"]} if pid else None}
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


def consent_ok(who):
    return not who or accounts.has_consent(con(), who["user"], TERMS_VERSION)


def handle_upload(headers, data, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    from urllib.parse import unquote
    return docs.upload(con(), who, unquote(headers.get("X-Filename", "file")), data,
                       product=unquote(headers.get("X-Product", "")) or None,
                       market=unquote(headers.get("X-Market", "")) or None,
                       case_id=headers.get("X-Case") or None)


def handle_docs(query, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    q = {k: v[0] for k, v in parse_qs(query).items()}
    return 200, {"documents": docs.listing(con(), who, q.get("case"), q.get("product"), q.get("type")),
                 "types": [{"id": t[0], "it": t[1], "en": t[2]} for t in docs.TYPES]}


def handle_doc_update(doc_id, body, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    if body.get("link_case"):
        if not docs.link(con(), who, body["link_case"], doc_id):
            return 404, {"error": "not found"}
    row = docs.update(con(), who, doc_id, body)
    if row is None:
        return 404, {"error": "not found"}
    return 200, {"id": doc_id, "doc_type": row["doc_type"], "product": row["product"], "market": row["market"],
                 "status": row["status"], "valid_until": row["valid_until"]}


def handle_profile(body, who):
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    style = body.get("style") if body.get("style") in personas.STYLES else None
    cur = accounts.get_profile(c, who["user"])
    if body.get("switch"):
        pick = personas.pick(who["user"] + db.now(), style or cur["style"], body.get("path_type", 1),
                             exclude=(cur["persona_id"],) if cur["persona_id"] else ())
        accounts.save_profile(c, who["user"], persona_id=pick["id"], style=style)
    elif style:
        accounts.save_profile(c, who["user"], style=style)
    p = accounts.get_profile(c, who["user"])
    pid = p["persona_id"]
    return 200, {"style": p["style"], "persona": {"id": pid, "name": personas.BY_ID[pid]["name"]} if pid else None}


def _case_for(body, who):
    """Return (row, error) for the case in the body, enforcing access."""
    if not who:
        return None, (400, {"error": "sign-in required"})
    row = con().execute("SELECT * FROM cases WHERE id=?", (body.get("case_id"),)).fetchone()
    if row is None or not accounts.can_access(con(), row, who):
        return None, (404, {"error": "case not found"})
    return row, None


def handle_intro(body, who, post=None):
    """Spoken welcome. Picks the persona if none yet, so the voice matches the person who then chats."""
    if not who or not consent_ok(who):
        return 403, {"error": "consent_required"}
    c = con()
    prof = accounts.get_profile(c, who["user"])
    pid = prof["persona_id"]
    if not pid:
        pid = personas.pick(who["user"], prof["style"], 1)["id"]
        accounts.save_profile(c, who["user"], persona_id=pid)
    code, out = voice.intro_audio(c, pid, "en" if body.get("lang") == "en" else "it", post=post)
    return code, out


def handle_speak(body, who, post=None):
    if not consent_ok(who) or not who:
        return 403, {"error": "consent_required"}
    if os.environ.get("VOICE_REPLIES") != "1":
        return 404, {"error": "reply_voice_off"}
    p = accounts.get_profile(con(), who["user"])
    pid = p["persona_id"]
    name = personas.BY_ID[pid]["name"] if pid in personas.BY_ID else None
    return voice.speak(con(), who["user"], str(body.get("text", "")), pid,
                       lang="en" if body.get("lang") == "en" else "it",
                       intro_name=name if body.get("intro") else None, post=post)


def handle_plan(body, who):
    if not who:
        return 400, {"error": "sign-in required"}
    out = {}
    if body.get("plan") in plans.PLANS:
        accounts.save_profile(con(), who["user"], plan=body["plan"])
        if features.is_sim("invite_trigger"):
            from .sim import invite_trigger
            out["invite_credit"] = invite_trigger.on_plan_chosen(con(), who["user"], body["plan"])
        else:
            pass  # live: the payment system calls invites.on_first_paid_month
    out["plan"] = accounts.get_profile(con(), who["user"])["plan"] or plans.DEFAULT
    return 200, out


def handle_invite(body, who):
    if not who or not consent_ok(who):
        return 403, {"error": "consent_required"}
    out = invites.stats(con(), who["user"])
    out["simulated"] = invites.has_simulated(con(), who["user"])
    return 200, out


def handle_invite_accept(body, who):
    if not who or not consent_ok(who):
        return 403, {"error": "consent_required"}
    return 200, {"status": invites.accept(con(), who["user"], str(body.get("code", ""))[:40])}


def handle_journey(body, who):
    """Everything the Journey panel shows. Simulated parts are tagged by sim.tag."""
    row, err = _case_for(body, who)
    if err:
        return err
    c = con()
    plan = accounts.get_profile(c, who["user"])["plan"] or plans.DEFAULT
    case = db.case_read(c, row["id"])
    have = {d["doc_type"] for d in docs.listing(c, who) if d["doc_type"]}
    out = {"credits": {"balance_cents": invites.balance(c, who["user"]),
                       "simulated": invites.has_simulated(c, who["user"])},
           "plan": plan, "case": {"product": case["product"].get("name_brand"), "country": case["market"].get("country"),
                                  "category": case["product"].get("category"),
                                  "export_registration": case["company"].get("export_registration")}}
    if features.is_sim("required_docs"):
        from .sim import required_docs
        out["required_docs"] = required_docs.required(case["product"].get("category"), have)
    if features.is_sim("options_packet"):
        from .sim import packet
        sel = body.get("selected") or packet.wanted_items(case["market"].get("needs"))
        sel = [i for i in sel if i in packet.NAMES]
        out["packet"] = packet.build(sel, plan)
        out["selected"] = sel
    return 200, out


def handle_eori(body, who):
    """What we hold for the EORI form, what is missing, and the links. DRAFT, see eori.py."""
    row, err = _case_for(body, who)
    if err:
        return err
    from . import eori
    return 200, eori.describe(db.case_read(con(), row["id"]), "en" if body.get("lang") == "en" else "it")


def handle_eori_pdf(body, who):
    """Save the values the person confirmed and return the filled ADM form as PDF bytes."""
    row, err = _case_for(body, who)
    if err:
        return err
    from . import eori
    vals = {k: str(v)[:200] for k, v in (body.get("values") or {}).items()
            if k in {f[0] for f in eori.FIELDS} | {"legal_form"} and v is not None}
    if vals:
        db.case_write(con(), row["id"], "company", {"eori_" + k: v for k, v in vals.items()}, actor=who["user"])
    case = db.case_read(con(), row["id"])
    return 200, eori.fill(eori.prefill(case, eori.saved_values(case)))


def handle_simpay(body, who):
    row, err = _case_for(body, who)
    if err:
        return err
    if not (features.is_sim("payment") and features.is_sim("options_packet")):
        return 501, {"error": "payment is not simulated"}
    from .sim import packet, payment, deliverables
    c = con()
    plan = accounts.get_profile(c, who["user"])["plan"] or plans.DEFAULT
    sel = [i for i in (body.get("selected") or []) if i in packet.NAMES]
    if not sel:
        return 400, {"error": "no items selected"}
    pk = packet.build(sel, plan)["data"]
    ids = sorted(i["id"] for i in pk["items"])
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(timespec="seconds")
    for ev in c.execute("SELECT data FROM events WHERE case_id=? AND kind='sim_payment' AND actor=? AND at>=? ORDER BY at DESC",
                        (row["id"], who["user"], since)).fetchall():
        d = json.loads(ev["data"] if not isinstance(ev, tuple) else ev[0])
        if sorted(d.get("items", [])) == ids:  # same packet just paid: replay, do not charge or spend credit again
            from .sim import tag
            out = {"payment": tag("payment", {"ref": d["ref"], "charged": False, "total_cents": d["total_cents"],
                                              "credit_used_cents": d["credit_used_cents"],
                                              "payable_cents": d["total_cents"] - d["credit_used_cents"], "duplicate": True,
                                              "message": {"it": "Pagamento già registrato poco fa. Nessun addebito (simulazione).",
                                                          "en": "Payment already recorded a moment ago. No charge (simulation)."}})}
            if features.is_sim("deliverables"):
                out["deliverables"] = deliverables.sample(ids)
            return 200, out
    used = invites.apply(c, who["user"], pk["total_cents"], case_ref=row["id"])
    out = {"payment": payment.pay(c, row["id"], who, pk, credit_used=used)}
    if features.is_sim("deliverables"):
        out["deliverables"] = deliverables.sample([i["id"] for i in pk["items"]])
    return 200, out


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
                                    "terms_version": TERMS_VERSION,
                                    "voice": voice.configured(),
                                    "voice_replies": os.environ.get("VOICE_REPLIES") == "1"})
        if path == "/plans.json":
            body = plans.public()
            if features.is_sim("price_menu"):
                from .sim import prices
                body["prices"] = prices.prices()
            return self._send(200, body)
        if path == "/features.json":
            return self._send(200, features.public())
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
        if path == "/docs" or path.startswith("/doc/"):
            try:
                who = self._who()
            except auth.AuthError:
                return self._send(401, {"error": "unauthorized"})
            if path == "/docs":
                return self._send(*handle_docs(urlparse(self.path).query, who))
            if not consent_ok(who):
                return self._send(403, {"error": "consent_required"})
            row = docs.get_doc(con(), path[len("/doc/"):], who)
            if row is None:
                return self._send(404, {"error": "not found"})
            data = storage.store().get(row["store_key"])
            self.send_response(200)
            self.send_header("Content-Type", row["mime"])
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % row["filename"].replace('"', ""))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        self._send(404, {})

    def _who(self):
        return auth.verify(self.headers.get("Authorization")) if auth.enabled() else None

    def do_POST(self):
        if not (self.path in ("/chat", "/consent", "/me", "/profile", "/upload", "/plan", "/journey", "/simpay", "/speak", "/intro", "/invite", "/invite/accept", "/eori", "/eori/pdf")
                or self.path.startswith("/doc/")):
            return self._send(404, {})
        try:
            try:
                who = self._who()
            except auth.AuthError:
                return self._send(401, {"error": "unauthorized"})
            n = int(self.headers.get("Content-Length", 0))
            if self.path == "/upload":
                if n > docs.MAX_BYTES + 1024:
                    return self._send(413, {"error": "file too large"})
                return self._send(*handle_upload(self.headers, self.rfile.read(n), who))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path.startswith("/doc/"):
                return self._send(*handle_doc_update(self.path[len("/doc/"):], body, who))
            if self.path == "/consent":
                return self._send(*handle_consent(body, who))
            if self.path == "/profile":
                return self._send(*handle_profile(body, who))
            if self.path in ("/speak", "/intro"):
                code, out = (handle_speak if self.path == "/speak" else handle_intro)(body, who)
                if code == 200:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    return self.wfile.write(out)
                return self._send(code, out)
            if self.path == "/eori":
                return self._send(*handle_eori(body, who))
            if self.path == "/eori/pdf":
                code, out = handle_eori_pdf(body, who)
                if code == 200:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers()
                    return self.wfile.write(out)
                return self._send(code, out)
            if self.path == "/invite":
                return self._send(*handle_invite(body, who))
            if self.path == "/invite/accept":
                return self._send(*handle_invite_accept(body, who))
            if self.path == "/plan":
                return self._send(*handle_plan(body, who))
            if self.path == "/journey":
                return self._send(*handle_journey(body, who))
            if self.path == "/simpay":
                return self._send(*handle_simpay(body, who))
            if self.path == "/me":
                ok = bool(who) and accounts.has_consent(con(), who["user"], TERMS_VERSION)
                latest = None
                if who:
                    r = con().execute("SELECT id FROM cases WHERE owner_sub=? ORDER BY created_at DESC LIMIT 1",
                                      (who["user"],)).fetchone()
                    latest = r["id"] if r else None
                return self._send(200, {"consent": ok or not who, "terms_version": TERMS_VERSION,
                                        "latest_case": latest,
                                        **(accounts.get_profile(con(), who["user"]) if who else {})})
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
