"""Hours, cost and margin per client project, for the TEM firm only (C2, 22 Nov 2026).

The fee is what the TEM agreed with the client for this project (fixed, or the monthly retainer share the TEM puts on it).
Time and cost entries are the TEM's own records. Nothing here is ever shown to the client: every function needs a TEM
user who works on the project (tems._case_tem), and the client's own endpoints never read these tables.

Who sees what: the firm lead sets the fee and target rate and sees every entry and the margin. A member adds entries,
sees their own entries and their own hours, and can delete their own entries.
Money is kept in euro cents; hours in hundredths of an hour.
"""
import uuid
from datetime import date

from . import db

CATEGORIES = ("chasing", "checking", "rules", "calls", "financing", "other")
FEE_KINDS = ("fixed", "retainer")
MAX_HOURS = 24


def _ctx(con, who, case_id):
    from . import tems
    row = tems._case_tem(con, who, case_id)
    f = tems.firm_of(con, who["user"]) if row is not None else None
    return row, f


def _cents(v):
    try:
        c = round(float(str(v).replace(",", ".")) * 100)
    except (TypeError, ValueError):
        return None
    return c if 0 <= c <= 100_000_000 else None


def _day(v):
    try:
        return date.fromisoformat(str(v)).isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def set_fee(con, who, case_id, kind, amount, target_rate=None):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    if f["role"] != "lead":
        return 403, {"error": "only the firm lead sets the fee"}
    if kind not in FEE_KINDS or _cents(amount) is None:
        return 400, {"error": "bad fee"}
    tr = _cents(target_rate) if target_rate not in (None, "") else None
    con.execute("DELETE FROM tem_fees WHERE case_id=? AND firm_id=?", (case_id, f["firm_id"]))
    con.execute("INSERT INTO tem_fees(case_id, firm_id, kind, amount_cents, target_rate_cents, set_by, set_at) VALUES (?,?,?,?,?,?,?)",
                (case_id, f["firm_id"], kind, _cents(amount), tr, who["user"], db.now()))
    con.commit()
    return 200, {"ok": True}


def add_time(con, who, case_id, hours, category, day=None, note=None):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    h = _cents(hours)
    if h is None or h == 0 or h > MAX_HOURS * 100 or category not in CATEGORIES:
        return 400, {"error": "bad entry"}
    con.execute("INSERT INTO tem_time(id, case_id, firm_id, user_sub, day, hours_x100, category, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, case_id, f["firm_id"], who["user"], _day(day), h, category, (str(note or "").strip()[:200] or None), db.now()))
    con.commit()
    return 200, {"ok": True}


def add_cost(con, who, case_id, amount, what, day=None):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    c, what = _cents(amount), str(what or "").strip()[:200]
    if not c or not what:
        return 400, {"error": "bad entry"}
    con.execute("INSERT INTO tem_costs(id, case_id, firm_id, user_sub, day, amount_cents, what, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, case_id, f["firm_id"], who["user"], _day(day), c, what, db.now()))
    con.commit()
    return 200, {"ok": True}


def delete(con, who, case_id, kind, entry_id):
    row, f = _ctx(con, who, case_id)
    if row is None or kind not in ("time", "cost"):
        return 404, {"error": "no such entry"}
    table = "tem_time" if kind == "time" else "tem_costs"
    e = con.execute(f"SELECT user_sub FROM {table} WHERE id=? AND case_id=? AND firm_id=?", (str(entry_id), case_id, f["firm_id"])).fetchone()
    if e is None or (f["role"] != "lead" and e["user_sub"] != who["user"]):
        return 404, {"error": "no such entry"}
    con.execute(f"DELETE FROM {table} WHERE id=?", (str(entry_id),))
    con.commit()
    return 200, {"ok": True}


def for_case(con, who, case_id):
    """What the TEM project page shows. Lead: fee, every entry, margin. Member: own entries and own hours."""
    row, f = _ctx(con, who, case_id)
    if row is None:
        return None
    lead = f["role"] == "lead"
    mine = "" if lead else " AND user_sub=?"
    args = (case_id, f["firm_id"]) + (() if lead else (who["user"],))
    time = [{"id": r["id"], "day": r["day"], "hours": r["hours_x100"] / 100, "category": r["category"], "note": r["note"], "own": r["user_sub"] == who["user"]}
            for r in con.execute("SELECT * FROM tem_time WHERE case_id=? AND firm_id=?" + mine + " ORDER BY day DESC, created_at DESC", args).fetchall()]
    costs = [{"id": r["id"], "day": r["day"], "amount": r["amount_cents"] / 100, "what": r["what"], "own": r["user_sub"] == who["user"]}
             for r in con.execute("SELECT * FROM tem_costs WHERE case_id=? AND firm_id=?" + mine + " ORDER BY day DESC, created_at DESC", args).fetchall()]
    hours = round(sum(t["hours"] for t in time), 2)
    out = {"lead": lead, "categories": list(CATEGORIES), "time": time, "costs": costs, "hours": hours,
           "by_category": {c: round(sum(t["hours"] for t in time if t["category"] == c), 2) for c in CATEGORIES}}
    if not lead:
        return out
    fee = con.execute("SELECT * FROM tem_fees WHERE case_id=? AND firm_id=?", (case_id, f["firm_id"])).fetchone()
    cost = round(sum(c["amount"] for c in costs), 2)
    out["cost"] = cost
    if fee:
        amount = fee["amount_cents"] / 100
        margin = round(amount - cost, 2)
        out["fee"] = {"kind": fee["kind"], "amount": amount,
                      "target_rate": fee["target_rate_cents"] / 100 if fee["target_rate_cents"] is not None else None}
        out["margin"] = margin
        out["rate"] = round(margin / hours, 2) if hours else None
        out["below_target"] = bool(out["rate"] is not None and out["fee"]["target_rate"] is not None and out["rate"] < out["fee"]["target_rate"])
    return out
