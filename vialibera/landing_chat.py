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
QUIET_TOOLS = ("set_role", "save_answer", "show_signin")
VISITOR = re.compile(r"^[a-f0-9]{16,64}$")
ROLES = ("exporter", "tem", "looking")
CATEGORIES = ("pasta", "wine", "olive oil", "cheese and dairy", "spirits", "cured meat", "preserves", "bakery", "other")
COUNTRIES = ("UK", "USA", "Canada", "Switzerland", "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
             "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Latvia", "Lithuania", "Luxembourg",
             "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden", "other")
TOPICS = ("product", "destination", "situation", "handling", "time", "volume", "cost", "problem", "implication", "need",
          "firm", "clients", "contact")

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

If the role is exporter (about 8 questions in this order, fewer if the visitor is brief):
1. Situation: what they export and to which country (product and destination).
2. Situation: how they handle the export documents today, or how they plan to if they have not exported yet:
   OPTIONS: Myself or my team | A freight forwarder | A customs broker | A TEM or consultant | Not decided yet
3. Problem, in numbers: roughly how many hours the paperwork takes per shipment, and how many shipments a year they expect.
   Offer ranges as quick choices, for example OPTIONS: Under 2 hours | 2 to 5 hours | 5 to 10 hours | Over 10 hours. If they
   type an exact number, use that instead. Ask the shipments per year the same way.
4. Problem, in money: what they pay per shipment to a forwarder, broker or consultant for the documents (ranges as quick
   choices in euros, or an exact figure if they offer one). A first-time exporter is asked what they expect to spend.
5. Once you have hours and shipments (and fees if given), call yearly_estimate and tell them the result as THEIR estimate:
   "By your own numbers, that is about X hours and Y euros a year." Never present it as a MioTEM figure.
6. Implication: ask what that does to them (margin, lead time, a delayed shipment, a rejected label, a lost buyer). Ask,
   do not tell. Never state figures, fines or deadlines yourself.
7. Need-payoff: ask what it would mean to know the exact documents and duties for their route before they ship.
8. Offer to sign in so MioTEM prepares the checklist and duties for their route, and say a preview of their route can be
   shown (when it is offered, the page will show it).
Save every answer with save_answer: product, destination, handling, time, volume, cost, problem, implication, need.

If the role is tem:
- Do NOT ask about a product or a destination country. A TEM works for many exporters.
- Situation: the firm, how many exporter clients they serve, which products and countries.
- Problem, in numbers: hours per client file or per shipment, how many files a month, and what they charge or lose on a
  file (ranges as quick choices, exact if they offer one). Then call yearly_estimate and state it as THEIR estimate.
- Implication: ask what it costs them when a client file has an error or a rule changes late.
- Need-payoff: ask what a workspace with a checked document list per client project would change.
- Then offer to sign in: MioTEM gives a TEM a trial workspace to try with real clients (2 clients, 5 projects).
- Ask for the firm name and a contact email near the end, with consent, and save with save_answer (firm, contact).

When you invite the visitor to sign in, or they say they want to, call show_signin in that same response and say the
Sign in button is below your message. Never describe a link or a page you cannot show.

Rules:
- Never state tariffs, taxes, legal requirements, prices or deadlines. If asked, say MioTEM checks these against
  official sources once the visitor is signed in, and that you will not guess.
- If asked what it costs to sign in or to try: answer it, it is a buying signal. Signing in is free. For an exporter, the free
  Explore plan includes one project on a covered route with its document checklist and duties, and one free check. For a TEM,
  the trial workspace is free, with 2 clients and 5 client projects and no time limit. Do not quote the price of any paid
  plan: those are shown after sign-in. Then ask the next question or invite them to sign in.
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
    {"name": "show_signin", "description": "Make the page show a Sign in button under your reply. Call it whenever you invite the "
     "visitor to sign in, and whenever they say they want to sign in. In your reply say the button is below.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "yearly_estimate", "description": "Work out the visitor's own yearly paperwork time and cost from their numbers. "
     "Use midpoints for ranges (for an open top range such as 'over 10' use the lower bound and say 'at least'). Returns the totals to quote as THEIR estimate.",
     "input_schema": {"type": "object", "properties": {"hours_per_shipment": {"type": "number"}, "shipments_per_year": {"type": "number"},
                                                       "cost_per_shipment_eur": {"type": "number"}}, "required": ["hours_per_shipment", "shipments_per_year"]}},
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
    if name == "show_signin":
        state["offer_signin"] = True
        return {"ok": True}
    if name == "yearly_estimate":
        try:
            h, n = float(args.get("hours_per_shipment")), float(args.get("shipments_per_year"))
            c = float(args.get("cost_per_shipment_eur") or 0)
        except (TypeError, ValueError):
            return {"error": "numbers_needed"}
        if not (0 <= h <= 1000 and 0 <= n <= 100000 and 0 <= c <= 1000000):
            return {"error": "out_of_range"}
        out = {"hours_per_year": round(h * n, 1), "cost_per_year_eur": round(c * n)}
        state["answers"]["estimate"] = [f"their own numbers: {h:g} h per shipment x {n:g} shipments"
                                        + (f", EUR {c:g} per shipment" if c else "") + f" = {out['hours_per_year']:g} h"
                                        + (f", EUR {out['cost_per_year_eur']:,} a year" if c else " a year")]
        return {**out, "note": "the visitor's own estimate, not a MioTEM figure"}
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
            if reply and all(u.name in QUIET_TOOLS for u in uses):
                break  # saves need no second call; an estimate must come back to the AI before it speaks
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
    return 200, {"reply": reply, "role": state["role"], "left": left, "signin": left <= 0, "offer_signin": bool(state.get("offer_signin"))}


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
            "product": first("product"), "destination": first("destination"), "firm": first("firm"), "contact": first("contact")}


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
