"""AI usage and cost per client message, for the Staff page.

Each AI call returns a usage block (tokens in, out, written to and read from the prompt cache). agent.turn adds
them up for one client message; handle_chat records the total as one "ai_usage" event on the case.
Prices are list prices in USD per million tokens and can be overridden with the env var AI_PRICES
(JSON, same keys), so a price change needs no code change.
"""
import json
import os
from datetime import datetime, timedelta, timezone

# Claude Sonnet 5.5, Claude API list prices (USD per million tokens), checked 4 Nov 2026.
DEFAULT_PRICES = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10}
FIELDS = ("input", "output", "cache_write", "cache_read")


def prices():
    p = dict(DEFAULT_PRICES)
    try:
        p.update({k: float(v) for k, v in json.loads(os.environ.get("AI_PRICES") or "{}").items() if k in p})
    except (ValueError, TypeError, AttributeError):
        pass
    return p


def add(acc, usage):
    """Add one API response's usage block to the running total. Stand-ins without usage count as a call only."""
    acc["calls"] = acc.get("calls", 0) + 1
    if usage is None:
        return acc
    for key, attr in (("input", "input_tokens"), ("output", "output_tokens"),
                      ("cache_write", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens")):
        acc[key] = acc.get(key, 0) + int(getattr(usage, attr, 0) or 0)
    return acc


def cost(acc, p=None):
    p = p or prices()
    return round(sum(acc.get(k, 0) * p[k] for k in FIELDS) / 1_000_000, 6)


def record(con, case_id, actor, acc, model, load_test=False):
    """One event per client message. Nothing is recorded when no AI call was made."""
    if not acc.get("calls"):
        return None
    from . import db
    data = {k: acc.get(k, 0) for k in FIELDS}
    data.update({"calls": acc["calls"], "model": model, "cost_usd": 0.0 if load_test else cost(acc),
                 "load_test": bool(load_test)})
    db.log_event(con, case_id, actor, "ai_usage", data)
    return data


def summary(con, days=14):
    """Per day and per conversation, real AI only (load tests left out)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = con.execute("SELECT case_id, at, data FROM events WHERE kind='ai_usage' AND at>=? ORDER BY at",
                       (since,)).fetchall()
    per_day, per_case, total = {}, {}, {"messages": 0, "calls": 0, "cost_usd": 0.0, **{k: 0 for k in FIELDS}}
    for r in rows:
        d = json.loads(r["data"])
        if d.get("load_test"):
            continue
        for bucket in (per_day.setdefault(r["at"][:10], {"messages": 0, "calls": 0, "cost_usd": 0.0, **{k: 0 for k in FIELDS}}),
                       per_case.setdefault(r["case_id"], {"messages": 0, "calls": 0, "cost_usd": 0.0, "last": r["at"],
                                                          **{k: 0 for k in FIELDS}}),
                       total):
            bucket["messages"] += 1
            bucket["calls"] += d.get("calls", 0)
            bucket["cost_usd"] += d.get("cost_usd", 0.0)
            for k in FIELDS:
                bucket[k] += d.get(k, 0)
        per_case[r["case_id"]]["last"] = r["at"]
    names = {}
    if per_case:
        marks = ",".join("?" * len(per_case))
        for r in con.execute(f"SELECT c.id, co.legal_name FROM cases c LEFT JOIN companies co ON co.id=c.company_id "
                             f"WHERE c.id IN ({marks})", tuple(per_case)).fetchall():
            names[r["id"]] = r["legal_name"]
    top = sorted(per_case.items(), key=lambda kv: -kv[1]["cost_usd"])[:10]
    rnd = lambda b: {**b, "cost_usd": round(b["cost_usd"], 4)}
    return {"days": days, "prices": prices(), "total": rnd(total),
            "per_day": [{"day": k, **rnd(v)} for k, v in sorted(per_day.items(), reverse=True)],
            "top_cases": [{"case_id": k, "company": names.get(k), **rnd(v)} for k, v in top]}
