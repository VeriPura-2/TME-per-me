"""Minimal chat service for staging. POST /chat {"case_id": optional, "message": "..."}.

Deploy to Cloud Run with authentication required (no public access).
Storage: Cloud SQL Postgres when CLOUDSQL_INSTANCE is set, otherwise local SQLite (dev only).
"""
import json
import os
import sys

if __name__ == "__main__":
    # Started as `python -m vialibera.app`: this module is __main__. Register it as vialibera.app as well, so an
    # import of vialibera.app gets this same copy, not a second one with its own connection bookkeeping (3 Nov 2026).
    sys.modules.setdefault("vialibera.app", sys.modules[__name__])
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic

from urllib.parse import parse_qs, urlparse

from . import importers, marks, admin, ai_usage, limits, lane_requests, tools, permissions, team, accounts, agent, auth, core_checks, db, docs, duties, features, jobs, vat_check, invites, personas, plans, requirements, storage, stripe_pay, tariff_watch, tems, voice
from .menu import MENU
from . import plan_prices
from .secrets import get_secret

from .terms import TERMS_VERSION  # noqa: E402 (kept here: app.TERMS_VERSION is used across the code and tests)
CON = None
_client = None


_client_lock = threading.Lock()


def client():
    """The AI client, created once per instance (by one thread: the others wait for it). Made at start-up by warm_up."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return _client


# Requests run in parallel threads (ThreadingHTTPServer). On Postgres each request borrows its own
# connection from a small pool and gives it back at the end (release_con). SQLite (local dev and
# tests) keeps one shared connection, and the server runs requests one at a time on it.
POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "4"))  # per instance. db-f1-micro allows ~25: 4 x max 4 instances = 16
_local = threading.local()
_pool = None
_pool_lock = threading.Lock()
_slots = threading.BoundedSemaphore(POOL_SIZE)
_sqlite_lock = threading.Lock()

# Diagnostics (3 Nov 2026): who holds the pooled connections. One log line when a request holds a connection
# for more than HOLD_LOG_S, and the list of current holders when a request gives up with "database busy".
HOLD_LOG_S = float(os.environ.get("DB_HOLD_LOG_S", "5"))
_holders = {}  # id(RequestCon) -> (request path, borrowed at, where in our code)
_holders_lock = threading.Lock()


def _where():
    """The last few places in our own code that led to this borrow (not the pool code itself)."""
    frames = [f for f in traceback.extract_stack()[:-3] if "/vialibera/" in f.filename and f.name not in ("_get", "raw", "execute")]
    return " < ".join(f"{f.filename.rsplit('/vialibera/', 1)[1]}:{f.lineno} {f.name}" for f in reversed(frames[-4:]))


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def postgres():
    return bool(os.environ.get("CLOUDSQL_INSTANCE"))


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = db.PGPool(f"/cloudsql/{os.environ['CLOUDSQL_INSTANCE']}", os.environ.get("DB_NAME", "vialibera"),
                              os.environ.get("DB_USER", "app"), get_secret("DB_PASSWORD"), POOL_SIZE)
    return _pool


class RequestCon:
    """A request's database handle on Postgres. Borrows a pooled connection on first use and can lend it
    back mid-request (outside calls) and borrow again later, so a handle kept in a local variable stays valid."""
    postgres = True

    def __init__(self):
        self._pg = None
        self._stats = [0, 0.0, 0.0, ""]  # queries, time in them, slowest, slowest query (since the last borrow)

    def _get(self):
        if self._pg is not None and self._pg.raw.closed:  # lost: hand it back closed and borrow a fresh one
            self.give_back()
        if self._pg is None:
            pool = _get_pool()
            t = time.time()
            if not _slots.acquire(timeout=30):
                now = time.time()
                with _holders_lock:
                    held = "; ".join(f"{p} held {now - t0:.1f}s from {w}" for p, t0, w in _holders.values())
                _log(f"DB_BUSY path={getattr(_local, 'path', '?')} waited={now - t:.1f}s holders: {held}")
                raise RuntimeError("database busy: no free connection within 30 s")
            try:
                self._pg = pool.get()
            except Exception:
                _slots.release()
                raise
            with _holders_lock:
                _holders[id(self)] = (getattr(_local, "path", "?"), time.time(), _where())
            self._stats = [0, 0.0, 0.0, ""]
        return self._pg

    @property
    def raw(self):
        return self._get().raw

    def held(self):
        return self._pg is not None

    def execute(self, sql, params=()):
        pg = self._get()
        t = time.time()
        try:
            return pg.execute(sql, params)
        finally:
            d = time.time() - t
            st = self._stats
            st[0] += 1
            st[1] += d
            if d > st[2]:
                st[2], st[3] = d, " ".join(sql.split())[:60]

    def executescript(self, script):
        return self._get().executescript(script)

    def commit(self):
        if self._pg is not None:
            self._pg.commit()

    def rollback(self):
        if self._pg is not None:
            self._pg.rollback()

    def give_back(self):
        """Commit or roll back, then return the connection to the pool. The handle stays usable."""
        pg, self._pg = self._pg, None
        if pg is None:
            return
        with _holders_lock:
            info = _holders.pop(id(self), None)
        if info and time.time() - info[1] > HOLD_LOG_S:
            n, total, worst, q = self._stats
            _log(f"DB_HOLD path={info[0]} held={time.time() - info[1]:.1f}s queries={n} in_queries={total:.1f}s "
                 f"slowest={worst:.2f}s [{q}] from {info[2]}")
        try:
            ok = db.finish(pg)
            _pool.put(pg, close=not ok)
        except Exception:
            traceback.print_exc()
            try:
                _pool.put(pg, close=True)
            except Exception:
                pass
        finally:
            _slots.release()


def con():
    global CON
    if not postgres():
        if CON is None:
            CON = db.connect(os.environ.get("DB_PATH", "/tmp/vialibera.db"))
        return CON
    c = getattr(_local, "con", None)
    if c is None:
        c = _local.con = RequestCon()
    elif c.held() and c._pg.raw.get_transaction_status() == 3:  # a failed statement left the transaction aborted
        c._pg.raw.rollback()
    return c


def lend_back():
    """Before a slow outside call: save this request's writes and return its connection to the pool."""
    c = getattr(_local, "con", None)
    if c is not None:
        c.give_back()


db.set_outside_hook(lend_back)


def release_con():
    """End of a request: commit or roll back, give the connection back, forget the handle."""
    c = getattr(_local, "con", None)
    if c is None:
        return
    _local.con = None
    c.give_back()


def rollback_current():
    c = CON if not postgres() else getattr(_local, "con", None)
    if c is not None:
        c.rollback()


STATIC_ASSETS = {"/logo-mark.png": "image/png", "/favicon.png": "image/png",
                 "/favicon.ico": "image/x-icon", "/apple-touch-icon.png": "image/png"}


LOAD_TEST_PREFIX = "Load test"  # first words of every load-test message: lets staff find and remove them


class LoadTestAI:
    """Stand-in for the AI in load tests (superadmin only): waits like a real reply, answers a fixed sentence,
    spends no AI credit. Everything else in the request (sign-in, database, saving the conversation) is real."""

    def __init__(self, delay):
        self.delay, self.messages = delay, self

    def create(self, **kw):
        from types import SimpleNamespace as NS
        time.sleep(self.delay)  # already inside db.outside_call in agent.turn, like a real AI call
        text = "Load test reply (stand-in, no AI used)."
        return NS(content=[NS(type="text", text=text, model_dump=lambda: {"type": "text", "text": text})])


def handle_chat(body, llm=None, who=None):
    msg = (body.get("message") or "").strip()
    if not msg:
        return 400, {"error": "message required"}
    if body.get("load_test"):
        if not permissions.is_superadmin(who):
            return 403, {"error": "forbidden"}  # never fall back to the real AI: that would spend credit
        try:
            delay = min(max(float(body.get("delay", 7)), 0.0), 30.0)
        except (TypeError, ValueError):
            delay = 7.0
        llm = LoadTestAI(delay)
        if not msg.startswith(LOAD_TEST_PREFIX):
            msg = f"{LOAD_TEST_PREFIX}: {msg}"
    c = con()
    if who and not accounts.has_consent(c, who["user"], TERMS_VERSION):
        return 403, {"error": "consent_required", "terms_version": TERMS_VERSION}
    lang = "en" if body.get("lang") == "en" else "it"
    cid = body.get("case_id")
    if cid:
        row = c.execute("SELECT owner_sub, company_id, org_id FROM cases WHERE id=?", (cid,)).fetchone()
        if row is None or not accounts.can_access(c, row, who):
            return 404, {"error": "case not found"}  # same answer for other people's cases
        role = permissions.case_role(c, row, who)
        if not permissions.allowed(role, "write"):
            return 403, {"error": "forbidden"}
        if role in ("staff", "support"):
            permissions.audit_staff(c, who, row, "write")
    else:
        if not permissions.can(c, who, "write"):
            return 403, {"error": "forbidden"}
        refused = limits.check_new(c, who)
        if refused:
            return refused
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
    usage = {}
    try:
        reply = agent.turn(llm or client(), c, cid, MENU, history, msg, lang=lang, persona_id=pid, usage=usage)
    except anthropic.APIError as e:  # credit used up, overloaded, timeout, connection: not the client's fault
        traceback.print_exc()
        ai_usage.record(c, cid, who["user"] if who else "client", usage, agent.MODEL, load_test=bool(body.get("load_test")))
        jobs.ai_unavailable(c, e)
        # history is not saved: the message counts as not sent, so resending it starts clean
        return 503, {"error": "ai_unavailable", "case_id": cid}
    db.save_history(c, cid, history)
    limits.register(c, who, cid)
    ai_usage.record(c, cid, who["user"] if who else "client", usage, agent.MODEL, load_test=bool(body.get("load_test")))
    out = {"case_id": cid, "reply": reply,
           "persona": {"id": pid, "name": personas.BY_ID[pid]["name"]} if pid else None}
    notice = accounts.attach_company(c, cid, who)
    if notice:
        out["account"] = notice
    return 200, out


START_CATEGORIES = ("pasta", "wine", "olive oil", "cheese and dairy", "spirits", "cured meat", "preserves", "bakery", "other")
EU_NAMES = ("Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France", "Germany",
            "Greece", "Hungary", "Ireland", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal",
            "Romania", "Slovakia", "Slovenia", "Spain", "Sweden")
START_COUNTRIES = ("UK", "USA", "Canada", "Switzerland") + EU_NAMES + ("other",)


def handle_start(body, who):
    """Start form: product, country and VAT number go straight into a new case, with no AI call.
    The checklist and duties are ready at once; the interview then starts from what is already known."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    if not accounts.has_consent(c, who["user"], TERMS_VERSION):
        return 403, {"error": "consent_required", "terms_version": TERMS_VERSION}
    if not permissions.can(c, who, "write"):
        return 403, {"error": "forbidden"}
    cat = body.get("category") if body.get("category") in START_CATEGORIES else None
    country = body.get("country") if body.get("country") in START_COUNTRIES else None
    other_product = str(body.get("other_product") or "").strip()[:120] if cat == "other" else ""
    other_country = str(body.get("other_country") or "").strip()[:120] if country == "other" else ""
    desc = str(body.get("description") or "").strip()[:200]
    raw_vat = str(body.get("vat") or "").strip()[:20]
    if not (cat or country or raw_vat):
        return 400, {"error": "nothing to start with"}
    vat, vat_err = (None, None)
    if raw_vat:
        vat, vat_err = vat_check.italian(raw_vat)
    path = 4 if cat and country else 1
    refused = limits.check_new(c, who, cat, country)
    if refused:
        return refused
    cid = db.create_case(c, path, actor="client", org_id=who.get("org"), owner_sub=who["user"])
    if cat:
        db.case_write(c, cid, "product", {"category": cat, **({"name_brand": desc} if desc else {})}, actor="client")
    if country:
        db.case_write(c, cid, "market", {"country": country}, actor="client")
    company = permissions.company_of(c, who["user"])
    notice = None
    if vat and not vat_err:
        fields_ = {"vat_number": vat}
        name = str(body.get("legal_name") or "").strip()[:200]
        if name:
            fields_["legal_name"] = name
        db.case_write(c, cid, "company", fields_, actor="client")
        notice = accounts.attach_company(c, cid, who)
    elif company:  # already works for a company: the new case belongs to it
        c.execute("UPDATE cases SET company_id=? WHERE id=?", (company, cid))
    c.commit()
    db.log_event(c, cid, "client", "start_form", {"category": cat, "country": country, "vat_given": bool(raw_vat),
                                                   "vat_error": vat_err})
    limits.register(c, who, cid)
    out = {"case_id": cid, "path_type": path, "covered": requirements.covers(cat, country)}
    if other_product or other_country or not out["covered"]:  # something MioTEM does not cover yet: staff see it under Lane requests
        lane_requests.record(c, cid, who["user"], {"product": other_product or cat, "country": other_country or country},
                             source="start_form")
        out["requested"] = {"product": other_product or None, "country": other_country or None}
    if vat_err:
        out["vat_error"] = vat_err
    if notice:
        out["account"] = notice
    return 200, out


def handle_consent(body, who):
    if not who:
        return 400, {"error": "sign-in required"}
    if not (body.get("accept_terms") and body.get("accept_onerous")):
        return 400, {"error": "both acceptances required"}
    lang = "en" if body.get("lang") == "en" else "it"
    accounts.record_consent(con(), who["user"], TERMS_VERSION, lang, True)
    return 200, {"ok": True, "terms_version": TERMS_VERSION}


def handle_company_consent(body, who):
    """An owner accepts the terms for the whole company. Members need no separate acceptance."""
    if not who:
        return 400, {"error": "sign-in required"}
    if not (body.get("accept_terms") and body.get("accept_onerous") and body.get("authorised")):
        return 400, {"error": "all three confirmations required"}
    if not accounts.record_company_consent(con(), who["user"], TERMS_VERSION, "en" if body.get("lang") == "en" else "it"):
        return 403, {"error": "forbidden"}
    return 200, {"ok": True, "terms_version": TERMS_VERSION}


def consent_ok(who):
    return not who or accounts.has_consent(con(), who["user"], TERMS_VERSION)


def handle_upload(headers, data, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    case_id = headers.get("X-Case") or None
    if case_id:
        row = con().execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None or not accounts.can_access(con(), row, who):
            return 404, {"error": "case not found"}
        if not permissions.allowed(permissions.case_role(con(), row, who), "write"):
            return 403, {"error": "forbidden"}
        if who and permissions.case_role(con(), row, who) == "tem":
            tems.log_access(con(), who, row, "upload")
    elif not permissions.can(con(), who, "write"):
        return 403, {"error": "forbidden"}
    from urllib.parse import unquote
    code, out = docs.upload(con(), who, unquote(headers.get("X-Filename", "file")), data,
                            product=unquote(headers.get("X-Product", "")) or None,
                            market=unquote(headers.get("X-Market", "")) or None,
                            case_id=case_id)
    if code == 200 and case_id and not out.get("duplicate"):
        core_checks.on_upload(con(), case_id, out["id"])  # only when the automatic switch is on
    return code, out


def handle_core(path, body, who):
    """VeriPura Core checks. View: anyone on the case. Send and switch: superadmin. Refresh: staff."""
    if not who and auth.enabled():
        return 400, {"error": "sign-in required"}
    c = con()
    case_id = str(body.get("case_id") or "")
    if path == "/core/view":
        return core_checks.view(c, who, case_id)
    if path == "/core/send":
        return core_checks.send(c, who, case_id, str(body.get("document_id") or ""))
    if path == "/core/refresh":
        return core_checks.refresh(c, who, case_id)
    if path == "/core/auto":
        return core_checks.set_auto(c, who, bool(body.get("on")))
    if path == "/core/auto_state":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        return 200, {"auto": core_checks.auto_enabled(c), "mode": core_checks.adapter().mode}
    return 404, {}


def handle_tem(path, body, who):
    """TEM firms, engagement and workspace. See tems.py for the access rules."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    case_id = str(body.get("case_id") or "")
    if path == "/tem/me":
        return tems.overview(c, who)
    if path == "/tem/ask":  # a client asks their TEM; the client signs in as an ordinary user
        if not consent_ok(who):
            return 403, {"error": "consent_required"}
        row, err = _case_for(body, who, "write")
        if err:
            return err
        return tems.ask(c, who, row, body.get("tool"), body.get("note"))
    if path == "/tem/join":
        return tems.join(c, who, str(body.get("token") or ""), body.get("label"))
    if path == "/tem/engage_info":
        return tems.engage_info(c, who, str(body.get("token") or ""))
    if path == "/tem/vat_lookup":  # pre-fills the engagement form from VIES
        return vat_check.lookup(body.get("vat"))
    if path == "/tem/engage_accept":
        return tems.engage_accept(c, who, str(body.get("token") or ""), body, TERMS_VERSION)
    if path == "/tem/client":
        return tems.client_view(c, who)
    if path == "/tem/revoke":
        return tems.revoke(c, who, str(body.get("firm") or ""))
    if path == "/tem/note":
        return tems.add_note(c, who, case_id, body.get("text"), body.get("visibility"))
    if path == "/tem/confirm":
        return tems.confirm_item(c, who, case_id, str(body.get("item") or ""), body.get("note"), body.get("on", True) is not False)
    if not consent_ok(who):  # working on clients needs the TEM's own acceptance of the terms
        return 403, {"error": "consent_required"}
    if path == "/tem/invite":
        return tems.invite_member(c, who)
    if path == "/tem/remove":
        return tems.remove_member(c, who, str(body.get("user") or ""))
    if path == "/tem/assign":
        return tems.assign(c, who, str(body.get("company") or ""), str(body.get("user") or ""), body.get("on", True) is not False)
    if path == "/tem/engage_link":
        return tems.engage_link(c, who)
    if path == "/tem/new_project":
        return tems.new_project(c, who, str(body.get("company") or ""), body.get("category"), body.get("country"), body.get("name"))
    if path == "/tem/project":
        return tems.project(c, who, case_id)
    if path == "/tem/request_done":
        return tems.request_done(c, who, str(body.get("id") or ""))
    if path == "/tem/tool_visibility":
        return tools.set_visibility(c, who, case_id, str(body.get("tool") or ""), body.get("visible", True) is not False)
    return 404, {}


def handle_job(headers, query=""):
    """Daily job, called by Cloud Scheduler with the X-Job-Secret header. No user sign-in.
    ?part=sources|vies|tariffs runs one part; no part runs all of them."""
    import hmac
    try:
        secret = get_secret("JOB_SECRET")
    except Exception:
        return 503, {"error": "job not configured"}
    if not hmac.compare_digest(str(headers.get("X-Job-Secret") or ""), secret):
        return 401, {"error": "unauthorized"}
    part = (parse_qs(query).get("part") or [""])[0]
    if part:
        if part not in jobs.PARTS:
            return 400, {"error": "unknown part", "parts": list(jobs.PARTS)}
        return 200, jobs.run_part(con(), part)
    return 200, jobs.run_daily(con())


def handle_docs(query, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    q = {k: v[0] for k, v in parse_qs(query).items()}
    return 200, {"documents": docs.listing(con(), who, q.get("case"), q.get("product"), q.get("type")),
                 "types": [{"id": t[0], "it": t[1], "en": t[2]} for t in docs.TYPES]}


def handle_doc_update(doc_id, body, who):
    if not consent_ok(who):
        return 403, {"error": "consent_required"}
    if not permissions.can(con(), who, "write"):
        d = docs.get_doc(con(), doc_id, who)  # a TEM may edit the documents of its engaged clients
        if d is None or not tems.has_access(con(), who, d["company_id"]):
            return 403, {"error": "forbidden"}
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


def _case_for(body, who, action="read"):
    """Return (row, error) for the case in the body, enforcing access and the role's rights for the action."""
    if not who:
        return None, (400, {"error": "sign-in required"})
    row = con().execute("SELECT * FROM cases WHERE id=?", (body.get("case_id"),)).fetchone()
    if row is None or not accounts.can_access(con(), row, who):
        return None, (404, {"error": "case not found"})
    role = permissions.case_role(con(), row, who)
    if not permissions.allowed(role, action):
        return None, (403, {"error": "forbidden"})
    if role in ("staff", "support"):
        permissions.audit_staff(con(), who, row, action)
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
    return voice.speak(con(), who["user"], str(body.get("text", "")).replace("**", ""), pid,
                       lang="en" if body.get("lang") == "en" else "it",
                       intro_name=name if body.get("intro") else None, post=post)


def handle_account(body, who):
    """Plan, usage and limits for the Account page."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    out = limits.usage(c, who["user"])
    cid = permissions.company_of(c, who["user"])
    out["company"] = None
    if cid:
        co = c.execute("SELECT legal_name, vat, vies_state FROM companies WHERE id=?", (cid,)).fetchone()
        n = c.execute("SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND status='active'", (cid,)).fetchone()["n"]
        out["company"] = {"name": co["legal_name"], "vat": co["vat"], "vies": co["vies_state"],
                          "owner_confirmed": permissions.owner_confirmed(c, cid),
                          "team": {"used": n, "cap": plans.get(out["plan"])["team_members"]}}
    return 200, out


def handle_plan(body, who):
    if not who:
        return 400, {"error": "sign-in required"}
    out = {}
    if body.get("plan") in plans.PLANS:
        if plans.get(body["plan"]).get("audience") == "tem":  # set by staff only
            return 403, {"error": "forbidden"}
        if not permissions.can(con(), who, "plan"):
            return 403, {"error": "forbidden"}
        if stripe_pay.enabled():  # with payments on, paid plans change only through Stripe
            if plans.get(body["plan"])["monthly"]:
                return 409, {"error": "use_checkout"}
            if stripe_pay.has_active_subscription(con(), who["user"]):
                return 409, {"error": "use_portal"}
        accounts.set_plan(con(), who["user"], body["plan"])
        if features.is_sim("invite_trigger") and not stripe_pay.enabled():
            from .sim import invite_trigger
            out["invite_credit"] = invite_trigger.on_plan_chosen(con(), who["user"], body["plan"])
        else:
            pass  # live: the payment system calls invites.on_first_paid_month
    out["plan"] = accounts.get_plan(con(), who["user"]) or plans.DEFAULT
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


def handle_mark(body, who):
    """Tick or untick a checklist item by hand. Needs the write right on the project (reviewers cannot)."""
    row, err = _case_for(body, who, "write")
    if err:
        return err
    c = con()
    case = db.case_read(c, row["id"])
    cat, country = case["product"].get("category"), case["market"].get("country")
    if not requirements.covers(cat, country):
        return 400, {"error": "not_covered"}
    ids = {i["id"] for i in requirements.required(cat, country, set())["data"]["items"]}
    return marks.mark(c, row["id"], who, body.get("item"), body.get("on", True) is not False, ids)


def handle_lane_details(body, who):
    """Save the optional questions (timing, volume, buyer) for a project on a route we do not cover yet."""
    row, err = _case_for(body, who, "write")
    if err:
        return err
    return lane_requests.add_details(con(), row["id"], who, body)


def handle_journey(body, who):
    """Everything the Journey panel shows. Simulated parts are tagged by sim.tag."""
    row, err = _case_for(body, who)
    if err:
        return err
    c = con()
    plan = accounts.get_plan(c, who["user"]) or plans.DEFAULT
    case = db.case_read(c, row["id"])
    have = {d["doc_type"] for d in docs.listing(c, who) if d["doc_type"]}
    out = {"credits": {"balance_cents": invites.balance(c, who["user"]),
                       "simulated": invites.has_simulated(c, who["user"])},
           "plan": plan, "role": permissions.case_role(c, row, who), "case": {"product": case["product"].get("name_brand"), "country": case["market"].get("country"),
                                  "category": case["product"].get("category"),
                                  "export_registration": case["company"].get("export_registration")}}
    if requirements.covers(case["product"].get("category"), case["market"].get("country")):
        out["required_docs"] = requirements.required(case["product"].get("category"), case["market"].get("country"), have)
    elif features.is_sim("required_docs_other"):
        from .sim import required_docs
        out["required_docs"] = required_docs.required(case["product"].get("category"), have)
    if out.get("required_docs") and not out["required_docs"].get("simulated"):
        tems.apply_confirmations(c, row["id"], out["required_docs"])
        jobs.apply_source_flags(c, row["id"], out["required_docs"])
        vat_check.apply_to_checklist(c, row["company_id"], out["required_docs"])
        marks.apply(c, row["id"], out["required_docs"])
    if not requirements.covers(case["product"].get("category"), case["market"].get("country")):
        lr = lane_requests.latest(c, row["id"])
        out["lane_request"] = {k: (lr or {}).get(k) or "" for k in ("timing", "volume", "buyer")} if lr else None
    out["core"] = core_checks.summary(c, row["id"])
    out["notes"] = tems.notes(c, row["id"], internal=False)
    out["duties"] = duties.for_case(c, case)
    viewer = "client" if tools.has_tem(c, row["company_id"]) and not tems.firm_of(c, who["user"]) else "exporter"
    out["tools"] = tools.for_viewer(c, row, case["product"].get("category"), case["market"].get("country"), viewer)
    if viewer == "client":  # the client can ask their TEM for help with the tools they see
        out["tools"]["tem"] = True
        out["tools"]["open_requests"] = [r["tool"] or "" for r in c.execute(
            "SELECT tool FROM tem_requests WHERE case_id=? AND status='open'", (row["id"],)).fetchall()]
    if features.is_sim("options_packet"):
        from .sim import packet
        sel = body.get("selected") or packet.wanted_items(case["market"].get("needs"))
        sel = [i for i in sel if i in packet.NAMES]
        out["packet"] = packet.build(sel, plan)
        out["selected"] = sel
    return 200, out


def handle_tools(path, body, who):
    """Tool cards on the project: interest clicks and export reference format checks."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    if path == "/tools/interest":
        cid = body.get("case_id")
        if cid:
            row, err = _case_for(body, who)
            if err and tems._case_tem(c, who, cid) is None:  # a TEM works on client projects through the engagement
                return err
        return tools.record_interest(c, cid, who["user"], str(body.get("tool") or ""))
    if path == "/tools/catalog":  # the tool tour after sign-in: every tool, as this user would see it
        company = permissions.company_of(c, who["user"])
        viewer = "tem" if tems.firm_of(c, who["user"]) else ("client" if tools.has_tem(c, company) else "exporter")
        cards = tools.for_case(None, None)
        if viewer == "client":
            cards = [x for x in cards if x.get("always") or x["id"] not in tools.CLIENT_OFF]
        return 200, {"cards": cards, "refcheck": True, "viewer": viewer}
    if path == "/tools/importers":  # researched importers for this project's destination; websites for paid plans only
        row, err = _case_for(body, who)
        if err:
            return err
        case = db.case_read(c, row["id"])
        plan = accounts.get_plan(c, who["user"]) or plans.DEFAULT
        via_tem = bool(tems.firm_of(c, who["user"])) or tools.has_tem(c, row["company_id"])
        return 200, importers.for_project(case["product"].get("category"), case["market"].get("country"), plan,
                                          permissions.is_superadmin(who), via_tem)
    if path == "/tools/refcheck":
        out = tools.check_reference(str(body.get("kind") or ""), body.get("value"))
        return (400 if out.get("error") else 200), out
    return 404, {}


def handle_team(path, body, who):
    """Team screen and owner actions. Everyone active may look; only owners change people."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    if path == "/team":
        return team.overview(c, who, body.get("label"))
    if path == "/team/accept":
        return team.accept(c, who, str(body.get("token") or ""))
    if path == "/team/decide":
        return team.decide(c, who, str(body.get("user") or ""), bool(body.get("approve")), body.get("company"))
    if path == "/team/role":
        return team.set_role(c, who, str(body.get("user") or ""), str(body.get("role") or ""), body.get("company"))
    if path == "/team/remove":
        return team.remove(c, who, str(body.get("user") or ""), body.get("company"))
    if path == "/team/consent":
        return handle_company_consent(body, who)
    if path == "/team/invite":
        return team.invite(c, who, str(body.get("role") or "member"), body.get("company"))
    return 404, {}


def handle_admin(path, body, who):
    """VeriPura superadmin only (Auth0 roles claim). See admin.py."""
    if not who:
        return 400, {"error": "sign-in required"}
    c = con()
    cid = str(body.get("company") or "")
    if path == "/admin/companies":
        return admin.companies(c, who)
    if path == "/admin/company":
        return admin.company(c, who, cid)
    if path == "/admin/audit":
        return admin.audit(c, who)
    if path == "/admin/load_test_cleanup":
        return admin.load_test_cleanup(c, who, bool(body.get("confirm")), body.get("expected"))
    if path == "/admin/confirm_owner":
        return admin.confirm_owner(c, who, cid)
    if path == "/admin/set_owner":
        return admin.set_owner(c, who, cid, str(body.get("user") or ""))
    if path == "/admin/verify":
        return admin.verify(c, who, cid, bool(body.get("verified", True)))
    if path == "/admin/plan":
        return admin.set_plan(c, who, cid, str(body.get("plan") or ""))
    if path == "/admin/add_company":
        return admin.add_company(c, who, body.get("vat"), body.get("name"))
    if path == "/admin/owner_invite":
        return admin.owner_invite(c, who, cid)
    if path == "/admin/queue":
        return admin.queue(c, who)
    if path == "/admin/lane_requests":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        return 200, lane_requests.listing(c)
    if path == "/admin/tool_interest":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        return 200, tools.interest_listing(c)
    if path == "/admin/ai_usage":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        try:
            days = min(max(int(body.get("days") or 14), 1), 90)
        except (TypeError, ValueError):
            days = 14
        return 200, ai_usage.summary(c, days)
    if path == "/admin/changes":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        return 200, {"changes": jobs.changes(c)}
    if path == "/admin/change_dismiss":
        if not permissions.is_superadmin(who):
            return 403, {"error": "forbidden"}
        return jobs.dismiss(c, who, str(body.get("id") or ""))
    if path == "/admin/run_daily":
        if not permissions.is_superadmin(who):
            return 403, {"error": "forbidden"}
        part = str(body.get("part") or "")
        if part:
            if part not in jobs.PARTS:
                return 400, {"error": "unknown part"}
            return 200, jobs.run_part(c, part)
        return 200, jobs.run_daily(c)
    if path == "/admin/tariff_watch":
        if not permissions.is_staff(who):
            return 403, {"error": "forbidden"}
        return 200, {"lines": tariff_watch.snapshot(c)}
    if path == "/admin/tariff_watch_run":
        if not permissions.is_superadmin(who):
            return 403, {"error": "forbidden"}
        return 200, tariff_watch.run(c)
    if path == "/admin/vies_recheck":
        if not permissions.is_superadmin(who):
            return 403, {"error": "forbidden"}
        res = vat_check.check_company(c, cid)
        return (200, res) if res else (404, {"error": "no Italian company"})
    if path == "/admin/tem_firms":
        return tems.list_firms(c, who)
    if path == "/admin/tem_firm":
        return tems.create_firm(c, who, body.get("name"), body.get("vat"), body.get("seats"))
    if path == "/admin/tem_project_limit":
        return tems.set_project_limit(c, who, str(body.get("firm") or ""), body.get("limit"))
    if path == "/admin/tem_lead_link":
        return tems.lead_link(c, who, str(body.get("firm") or ""))
    if path == "/admin/item":
        return admin.set_item(c, who, str(body.get("item_id") or ""), str(body.get("state") or ""))
    return 404, {}


def handle_eori(body, who):
    """What we hold for the EORI form, what is missing, and the links. DRAFT, see eori.py."""
    row, err = _case_for(body, who)
    if err:
        return err
    from . import eori
    return 200, eori.describe(db.case_read(con(), row["id"]), "en" if body.get("lang") == "en" else "it")


def handle_ocqpr(body, who):
    """Check one VAT number against OCQ PR's public list of certified operators. Only when a person asks."""
    row, err = _case_for(body, who)
    if err:
        return err
    from . import ocqpr
    case = db.case_read(con(), row["id"])
    vat = body.get("vat") or (case.get("company") or {}).get("vat_number")
    return 200, ocqpr.check_vat(vat, "en" if body.get("lang") == "en" else "it")


def handle_eori_pdf(body, who):
    """Save the values the person confirmed and return the filled ADM form as PDF bytes."""
    row, err = _case_for(body, who, "write")
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
    row, err = _case_for(body, who, "order")
    if err:
        return err
    if stripe_pay.enabled():
        return 409, {"error": "use_pay"}  # real (test) payments are on: the simulated button must not give work away
    if not (features.is_sim("payment") and features.is_sim("options_packet")):
        return 501, {"error": "payment is not simulated"}
    from .sim import packet, payment, deliverables
    c = con()
    plan = accounts.get_plan(c, who["user"]) or plans.DEFAULT
    sel = [i for i in (body.get("selected") or []) if i in packet.NAMES]
    if not sel:
        return 400, {"error": "no items selected"}
    pk = packet.build(sel, plan)["data"]
    if not pk["items"]:
        return 402, {"error": "plan_required"}  # the plan cannot buy these items
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


def _base(handler_host=None):
    return os.environ.get("PUBLIC_BASE_URL") or (f"https://{handler_host}" if handler_host else "")


def _packet(body, row, who):
    """The approved packet for a case, from the same builder the simulated payment uses."""
    from .sim import packet
    plan = accounts.get_plan(con(), who["user"]) or plans.DEFAULT
    sel = [i for i in (body.get("selected") or []) if i in packet.NAMES]
    if not sel:
        return None
    pk = packet.build(sel, plan)["data"]
    return pk if pk["items"] else None


def handle_pay(body, who, host=None):
    """Start a real (test-mode) payment: returns a Stripe Checkout address, or records a credit-only payment."""
    row, err = _case_for(body, who, "order")
    if err:
        return err
    if not stripe_pay.enabled():
        return 501, {"error": "payments_not_configured"}
    pk = _packet(body, row, who)
    if not pk:
        return 400, {"error": "no items selected"}
    c = con()
    total = pk["total_cents"]
    credit = min(invites.balance(c, who["user"]), total)
    ids = sorted(i["id"] for i in pk["items"])
    if total - credit <= 0:  # fully covered by credit: nothing to charge
        d = stripe_pay.record_payment(c, row["id"], who["user"], "CREDIT-" + db.now(), ids, total, credit)
        return 200, {"paid": True, "payment": d}
    try:
        out = stripe_pay.checkout_items(c, who, row["id"], pk["items"], total, credit, _base(host),
                                        lang="en" if body.get("lang") == "en" else "it", email=body.get("email"))
    except stripe_pay.StripeError as e:
        return (400 if e.status == 400 else 502), {"error": str(e)}
    return 200, {"url": out["url"]}


def handle_plan_checkout(body, who, host=None):
    if not who:
        return 400, {"error": "sign-in required"}
    if not stripe_pay.enabled():
        return 501, {"error": "payments_not_configured"}
    if not permissions.can(con(), who, "plan"):
        return 403, {"error": "forbidden"}
    if body.get("plan") not in plans.PLANS or not plans.get(body["plan"])["monthly"] or plans.get(body["plan"]).get("audience") == "tem":
        return 400, {"error": "not a paid plan"}
    try:
        if stripe_pay.has_active_subscription(con(), who["user"]):
            return 200, stripe_pay.portal(con(), who, _base(host), body.get("email"))
        return 200, stripe_pay.checkout_plan(con(), who, body["plan"], _base(host),
                                             lang="en" if body.get("lang") == "en" else "it", email=body.get("email"))
    except stripe_pay.StripeError as e:
        return (400 if e.status == 400 else 502), {"error": str(e)}


def handle_billing_portal(body, who, host=None):
    if not who:
        return 400, {"error": "sign-in required"}
    if not stripe_pay.enabled():
        return 501, {"error": "payments_not_configured"}
    if not permissions.can(con(), who, "plan"):
        return 403, {"error": "forbidden"}
    try:
        return 200, stripe_pay.portal(con(), who, _base(host), body.get("email"))
    except stripe_pay.StripeError as e:
        return 502, {"error": str(e)}


def handle_pay_confirm(body, who):
    """The return page asks Stripe directly whether the session was paid, so the result shows even before the webhook arrives."""
    if not who:
        return 400, {"error": "sign-in required"}
    if not stripe_pay.enabled():
        return 501, {"error": "payments_not_configured"}
    sid = str(body.get("session_id", ""))
    if not sid.startswith("cs_"):
        return 400, {"error": "bad session"}
    try:
        s = stripe_pay.retrieve_session(sid)
    except stripe_pay.StripeError as e:
        return 502, {"error": str(e)}
    meta = s.get("metadata") or {}
    c = con()
    mine = meta.get("user") == who["user"] or invites.holder(c, who["user"]) == meta.get("holder")
    if not mine:
        return 404, {"error": "not found"}
    if meta.get("kind") == "items":
        row = c.execute("SELECT * FROM cases WHERE id=?", (meta.get("case_id"),)).fetchone()
        if row is None or not accounts.can_access(c, row, who):
            return 404, {"error": "not found"}
    res = stripe_pay.session_paid(c, s)
    out = {"status": res["status"], "kind": meta.get("kind"), "mode": stripe_pay.mode()}
    if res["status"] == "paid" and meta.get("kind") == "items":
        ids = [x for x in meta.get("items", "").split(",") if x]
        total = int(meta.get("total_cents", 0))
        credit = int(meta.get("credit_cents", 0))
        out.update(ref=sid, total_cents=total, credit_used_cents=credit, payable_cents=total - credit)
        if features.is_sim("deliverables"):
            from .sim import deliverables
            out["deliverables"] = deliverables.sample(ids)
    if res["status"] == "paid" and meta.get("kind") == "plan":
        out["plan"] = accounts.get_plan(c, who["user"]) or plans.DEFAULT
    return 200, out


def handle_stripe_webhook(raw, signature):
    """No sign-in here: the signature is the proof. Bad signature gets 400, everything else 200 so Stripe does not retry forever."""
    try:
        secret = get_secret("STRIPE_WEBHOOK_SECRET")
    except Exception:
        return 503, {"error": "webhook not configured"}
    try:
        event = stripe_pay.verify_webhook(raw, signature or "", secret)
    except stripe_pay.StripeError as e:
        return 400, {"error": str(e)}
    return 200, {"result": stripe_pay.process_event(con(), event)}


def render_terms(lang):
    import markdown
    name = "en" if lang == "en" else "it"
    path = os.path.join(os.path.dirname(__file__), "static", f"terms_{name}.md")
    body = markdown.markdown(open(path, encoding="utf-8").read(), extensions=["tables"])
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Public+Sans:wght@400;600&display=swap'>"
            "<style>body{font:16px/1.6 'Public Sans',system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px;background:#F7F2E8;color:#2B2B26}"
            "h1,h2,h3{font-family:'Libre Baskerville',Georgia,serif;color:#1F3A2E}a{color:#2F6B55}</style>"
            + body).encode()


class Handler(BaseHTTPRequestHandler):
    def _one_request(self, fn):
        if not postgres():  # SQLite: one shared connection, so one request at a time
            with _sqlite_lock:
                return fn()
        _local.path = self.command + " " + self.path.split("?")[0]
        try:
            return fn()
        finally:
            release_con()

    def do_GET(self):
        return self._one_request(self._get)

    def do_POST(self):
        return self._one_request(self._post)

    def _get(self):
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
        if path == "/tools/public.json":  # the public landing page's tool list: no partner names, no user data
            return self._send(200, {"tools": tools.public_catalog()})
        if path == "/plans.json":
            body = plans.public()
            body["stripe"] = stripe_pay.status()
            body["prices"] = {"simulated": False, "data": {k: v for k, v in plan_prices.MENU.items() if k in body["plans"]}}
            return self._send(200, body)
        if path == "/features.json":
            return self._send(200, features.public())
        if path in STATIC_ASSETS:
            data = open(os.path.join(os.path.dirname(__file__), "static", path[1:]), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", STATIC_ASSETS[path])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return self.wfile.write(data)
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

    def _post(self):
        if self.path.split("?")[0] == "/jobs/daily":
            try:
                return self._send(*handle_job(self.headers, urlparse(self.path).query))
            except Exception as e:
                traceback.print_exc()  # full details in the server log, not only the error name
                return self._send(500, {"error": type(e).__name__})
        if not (self.path in ("/chat", "/start", "/consent", "/me", "/profile", "/upload", "/plan", "/journey", "/checklist/mark", "/lane/details", "/account", "/simpay", "/speak", "/intro", "/invite", "/invite/accept", "/eori", "/eori/pdf", "/ocqpr", "/pay", "/pay/confirm", "/plan/checkout", "/billing/portal", "/stripe/webhook")
                or self.path.startswith("/doc/") or self.path.startswith("/team") or self.path.startswith("/admin/")
                or self.path.startswith("/core/") or self.path.startswith("/tem/") or self.path.startswith("/tools/")):
            return self._send(404, {})
        try:
            if self.path == "/stripe/webhook":
                n = int(self.headers.get("Content-Length", 0))
                if n > 1_000_000:
                    return self._send(413, {})
                return self._send(*handle_stripe_webhook(self.rfile.read(n), self.headers.get("Stripe-Signature")))
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
            if self.path.startswith("/team"):
                return self._send(*handle_team(self.path, body, who))
            if self.path.startswith("/admin/"):
                return self._send(*handle_admin(self.path, body, who))
            if self.path.startswith("/core/"):
                return self._send(*handle_core(self.path, body, who))
            if self.path.startswith("/tem/"):
                return self._send(*handle_tem(self.path, body, who))
            if self.path == "/eori":
                return self._send(*handle_eori(body, who))
            if self.path == "/ocqpr":
                return self._send(*handle_ocqpr(body, who))
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
            if self.path == "/start":
                return self._send(*handle_start(body, who))
            if self.path == "/journey":
                return self._send(*handle_journey(body, who))
            if self.path == "/account":
                return self._send(*handle_account(body, who))
            if self.path == "/lane/details":
                return self._send(*handle_lane_details(body, who))
            if self.path == "/checklist/mark":
                return self._send(*handle_mark(body, who))
            if self.path.startswith("/tools/"):
                return self._send(*handle_tools(self.path, body, who))
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
            if self.path == "/pay":
                return self._send(*handle_pay(body, who, host))
            if self.path == "/pay/confirm":
                return self._send(*handle_pay_confirm(body, who))
            if self.path == "/plan/checkout":
                return self._send(*handle_plan_checkout(body, who, host))
            if self.path == "/billing/portal":
                return self._send(*handle_billing_portal(body, who, host))
            if self.path == "/simpay":
                return self._send(*handle_simpay(body, who))
            if self.path == "/me":
                ok = bool(who) and accounts.has_consent(con(), who["user"], TERMS_VERSION)
                latest = None
                if who:
                    cid = permissions.company_of(con(), who["user"])
                    r = con().execute("SELECT id FROM cases WHERE (owner_sub=? AND company_id IS NULL) OR company_id=? "
                                      "ORDER BY created_at DESC LIMIT 1", (who["user"], cid)).fetchone()
                    latest = r["id"] if r else None
                via = None
                if who and ok and not con().execute("SELECT 1 FROM consents WHERE user_sub=? AND terms_version=?",
                                                    (who["user"], TERMS_VERSION)).fetchone():
                    via = "company"
                return self._send(200, {"consent": ok or not who, "terms_version": TERMS_VERSION, "consent_via": via,
                                        "latest_case": latest,
                                        "role": permissions.my_role(con(), who) if who else None,
                                        "superadmin": permissions.is_superadmin(who), "staff_level": permissions.staff_level(who),
                                        "tem": tems.firm_of(con(), who["user"]) if who else None,
                                        "has_company": bool(who and permissions.company_of(con(), who["user"])),
                                        **(accounts.get_profile(con(), who["user"]) if who else {})})
            self._send(*handle_chat(body, who=who))
        except Exception as e:  # keep the service up, report a typed error
            traceback.print_exc()  # full details in the server log, not only the error name
            try:
                rollback_current()
            except Exception:
                pass
            self._send(500, {"error": type(e).__name__})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128  # connections waiting to be accepted (the default of 5 is too small)


def warm_up():
    """Before the instance listens (Cloud Run sends traffic only then): AI client, database pool, voice key.
    On 3 Nov 2026, 20 requests on a new instance each fetched the AI key while holding a database connection."""
    for name, step in (("ai client", client), ("database pool", lambda: postgres() and _get_pool()),
                       ("voice key", voice.api_key)):
        t = time.time()
        try:
            step()
            _log(f"WARM_UP {name} ready in {time.time() - t:.1f}s")
        except Exception as e:  # start anyway: the first request will try again
            _log(f"WARM_UP {name} failed: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    warm_up()
    Server(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler).serve_forever()
