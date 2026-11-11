"""The landing page conversation before sign-in: finds out whether the visitor is an exporter or a TEM, then asks
SPIN questions that fit that role. No case file exists yet, so what the visitor says is kept on the conversation
and carried over after sign-in.

The endpoint is public, so it is capped: messages per visitor, messages per network address per day, and a daily
ceiling for the whole site. Past a cap the page falls back to the scripted buttons and the TEM form.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

from . import ai_usage, db

MODEL = "claude-sonnet-5-5"
MESSAGE_CAP = 12
IP_DAILY_CAP = 40
DAILY_CEILING = int(os.environ.get("LANDING_DAILY_CEILING", "600"))
MAX_CHARS = 1000
MAX_TOKENS = 600
VISITOR = re.compile(r"^[a-f0-9]{16,64}$")
ROLES = ("exporter", "tem", "looking")
CATEGORIES = ("pasta", "wine", "olive oil", "cheese and dairy", "spirits", "cured meat", "preserves", "bakery", "other")
COUNTRIES = ("UK", "USA", "Canada", "Switzerland", "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
             "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Latvia", "Lithuania", "Luxembourg",
             "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden", "other")
TOPICS = ("product", "destination", "situation", "problem", "implication", "need", "firm", "clients", "contact")

OPENER = {"it": "Ciao. Esporti cibo italiano, oppure sei un TEM o consulente export?",
          "en": "Hello. Do you export Italian food, or are you a TEM or export consultant?"}

SYSTEM = """You are the MioTEM guide on the public landing page. MioTEM is an AI Trade Export Manager for Italian food
companies: it prepares the document checklist, duties and next steps for exporting Italian food. The visitor has not
signed in yet. You speak plainly, warmly and briefly (two to four short sentences per message).

The visitor has already seen this opening line: "Do you export Italian food, or are you a TEM or export consultant?"
(a TEM is a Trade Export Manager: a consultant who runs exports for several food companies).

STEP 1. Find out the role. As soon as it is clear, call set_role (exporter, tem or looking). A person who only wants to
look around is "looking": answer what they ask and let them explore.

STEP 2. Ask questions that fit the role. The whole conversation depends on the role. Use SPIN: ask about the Situation,
then the Problem, then the Implication of that problem, then the Need-payoff (what would change for them if it were
solved). Ask exactly ONE question per message. Never repeat a question. Call save_answer for each answer, in the same
response as your reply. Never pressure and never gate: the visitor may skip any question.

If the role is exporter:
- Situation: what they export and to which country (product and destination), and who handles exports today.
- Problem: what worries or slows them, such as documents, duties, labels, finding buyers.
- Implication: ask what happens to them if that goes wrong (a delayed shipment, a rejected label, a lost buyer). Ask,
  do not tell. Never state figures, fines or deadlines yourself.
- Need-payoff: ask what it would mean to know the exact documents and duties before they ship.
- Then offer to sign in so MioTEM prepares the checklist and duties for their route.

If the role is tem:
- Do NOT ask about a product or a destination country. A TEM works for many exporters.
- Situation: the firm, how many exporter clients they serve, which products and countries.
- Problem: where time goes (chasing documents, checking rules per country, tracking each client).
- Implication: ask what it costs them when a client's file has an error or a rule changes late.
- Need-payoff: ask what a workspace with a checked document list per client project would change.
- Then offer to sign in: MioTEM gives a TEM a trial workspace to try with real clients (2 clients, 5 projects).
- Ask for the firm name and a contact email near the end, with consent, and save with save_answer (firm, contact).

Rules:
- Never state tariffs, taxes, legal requirements, prices or deadlines. If asked, say MioTEM checks these against
  official sources once the visitor is signed in, and that you will not guess.
- Never promise outcomes. Never say you are human. If asked, say you are an AI.
- Never use these words: "SaaS", "traceability", "AI-powered". Describe MioTEM as compliance document validation,
  powered by orchestrated AI-Agents. Never use em dashes.
- If the visitor writes in another language, follow them. Otherwise use the interface language below.
- When the answer is a short choice you may end with one final line: OPTIONS: first | second | third (2 to 4 choices).
- When the visitor has reached the end of the conversation allowance, close warmly and invite them to sign in: the
  conversation continues after sign-in."""

TOOLS = [
    {"name": "set_role", "description": "Record who the visitor is.",
     "input_schema": {"type": "object", "properties": {"role": {"type": "string", "enum": list(ROLES)}}, "required": ["role"]}},
    {"name": "save_answer", "description": "Record one thing the visitor told you, in their words, short. For topic product "
     "also give value: one of the product categories. For topic destination also give value: one of the countries.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string", "enum": list(TOPICS)},
                                                       "text": {"type": "string"},
                                                       "value": {"type": "string", "description": "product: " + ", ".join(CATEGORIES) + ". destination: " + ", ".join(COUNTRIES) + " (use other if none fits)."}},
                     "required": ["topic", "text"]}},
]


def ip_hash(ip):
    return hashlib.sha256(("vl-landing:" + (ip or "unknown")).encode()).hexdigest()[:32]


def _since(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def used_today(con):
    r = con.execute("SELECT COALESCE(SUM(messages), 0) AS n FROM anon_chats WHERE updated_at>?", (_since(24),)).fetchone()
    return int(r["n"])


def _row(con, visitor):
    r = con.execute("SELECT * FROM anon_chats WHERE visitor_id=?", (visitor,)).fetchone()
    return dict(r) if r else None


def run_tool(state, name, args):
    if name == "set_role" and args.get("role") in ROLES:
        state["role"] = args["role"]
        return {"ok": True}
    if name == "save_answer" and args.get("topic") in TOPICS:
        state["answers"].setdefault(args["topic"], []).append(str(args.get("text") or "")[:300])
        state["answers"][args["topic"]] = state["answers"][args["topic"]][-3:]
        value = str(args.get("value") or "")
        if args["topic"] == "product" and value in CATEGORIES:
            state["answers"]["category"] = value
        if args["topic"] == "destination" and value in COUNTRIES:
            state["answers"]["country"] = value
        return {"ok": True}
    return {"error": "unknown"}


def _note(state, lang, left):
    t = f"Interface language: {'Italian' if lang == 'it' else 'English'}. Role so far: {state['role'] or 'not known yet'}."
    if state["answers"]:
        t += " Saved so far: " + json.dumps(state["answers"], ensure_ascii=False) + "."
    if left <= 1:
        t += " This is the visitor's LAST message in this conversation: answer it, then close warmly and invite them to sign in."
    return t


def message(con, body, ip, client):
    """One visitor message in, one reply out. Returns (status, body)."""
    visitor = str(body.get("visitor") or "")
    text = str(body.get("message") or "").strip()[:MAX_CHARS]
    lang = "en" if body.get("lang") == "en" else "it"
    if not VISITOR.match(visitor) or not text:
        return 400, {"error": "bad_request"}
    row = _row(con, visitor)
    state = {"role": row["role"] if row else None,
             "history": json.loads(row["history"]) if row else [],
             "answers": json.loads(row["answers"]) if row else {},
             "messages": row["messages"] if row else 0}
    if state["messages"] >= MESSAGE_CAP:
        return 429, {"error": "cap", "signin": True, "role": state["role"]}
    h = ip_hash(ip)
    mine = con.execute("SELECT COALESCE(SUM(messages), 0) AS n FROM anon_chats WHERE ip_hash=? AND updated_at>?",
                       (h, _since(24))).fetchone()["n"]
    if mine >= IP_DAILY_CAP or used_today(con) >= DAILY_CEILING:
        return 503, {"error": "busy", "role": state["role"]}
    left = MESSAGE_CAP - state["messages"] - 1
    history = state["history"]
    if history and history[-1]["role"] == "user" and isinstance(history[-1]["content"], list):
        history[-1]["content"].append({"type": "text", "text": text})  # the last reply ended on tool results: roles must alternate
    else:
        history.append({"role": "user", "content": text})
    usage = {}
    try:
        for _ in range(4):
            with db.outside_call():
                resp = client.messages.create(
                    model=MODEL, max_tokens=MAX_TOKENS, tools=TOOLS, messages=history[-24:],
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": _note(state, lang, left)}])
            ai_usage.add(usage, getattr(resp, "usage", None))
            history.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            uses = [b for b in resp.content if b.type == "tool_use"]
            reply = "".join(b.text for b in resp.content if b.type == "text").strip()
            if not uses:
                break
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(run_tool(state, u.name, u.input))} for u in uses]})
            if reply:
                break
        else:
            reply = ""
    except Exception:
        ai_usage.record(con, None, "visitor", usage, MODEL)
        return 503, {"error": "ai_unavailable", "role": state["role"]}  # history not saved: the message counts as not sent
    ai_usage.record(con, None, "visitor", usage, MODEL)
    if not reply:
        reply = OPENER[lang]
    now = db.now()
    fields = (state["role"], json.dumps(history[-24:]), json.dumps(state["answers"], ensure_ascii=False), state["messages"] + 1, now)
    if row:
        con.execute("UPDATE anon_chats SET role=?, history=?, answers=?, messages=?, updated_at=? WHERE visitor_id=?", fields + (visitor,))
    else:
        con.execute("INSERT INTO anon_chats(visitor_id, ip_hash, role, history, answers, messages, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (visitor, h, state["role"], fields[1], fields[2], fields[3], now, now))
    return 200, {"reply": reply, "role": state["role"], "left": left, "signin": left <= 0}


def listing(con):
    rows = [dict(r) for r in con.execute(
        "SELECT role, answers, messages, created_at FROM anon_chats ORDER BY updated_at DESC LIMIT 100").fetchall()]
    by = {}
    for r in rows:
        by[r["role"] or "unknown"] = by.get(r["role"] or "unknown", 0) + 1
    return {"total": len(rows), "by_role": by, "chats": rows}


def claim(con, user_sub, visitor):
    """After sign-in: attach the landing conversation to the person and return what it learned. A conversation
    already claimed by someone else is not shared."""
    if not VISITOR.match(str(visitor or "")):
        return {"claimed": False}
    row = _row(con, visitor)
    if not row or (row.get("user_sub") and row["user_sub"] != user_sub):
        return {"claimed": False}
    if not row.get("user_sub"):
        con.execute("UPDATE anon_chats SET user_sub=? WHERE visitor_id=?", (user_sub, visitor))
    a = json.loads(row["answers"])
    first = lambda k: (a.get(k) or [""])[-1] if isinstance(a.get(k), list) else ""
    return {"claimed": True, "role": row["role"], "category": a.get("category"), "country": a.get("country"),
            "product": first("product"), "destination": first("destination")}


def note_for(con, user_sub):
    """A line for the project chat prompt: what this person told the landing guide before signing in."""
    if not user_sub:
        return ""
    row = con.execute("SELECT answers, role FROM anon_chats WHERE user_sub=? ORDER BY updated_at DESC LIMIT 1", (user_sub,)).fetchone()
    if not row or row["role"] != "exporter":
        return ""
    a = json.loads(row["answers"])
    told = "; ".join(f"{k}: {' / '.join(v)}" for k, v in a.items() if isinstance(v, list) and v)
    if not told:
        return ""
    return (" Before signing in, the client told our landing guide: " + told + ". Do not ask for these again. Build on the "
            "problem and the consequence they named, in your own words, and ask only what is still missing.")
