"""Requests for products and countries MioTEM does not cover yet.

When a client asks for a lane outside the covered list, the AI (or the start form) records what they want to
export, where, when, how much and whether they have a buyer. Staff see the requests, counted by country and
product, to decide which lanes to build next.
"""
import uuid

from . import db

COVERED_PRODUCTS = ("pasta", "wine", "olive oil", "cheese")
COVERED_COUNTRIES = ("UK", "USA", "Canada", "Switzerland", "Germany", "France", "Spain", "Netherlands", "Belgium", "Austria")
KEYS = ("product", "country", "timing", "volume", "buyer", "notes")


def _clean(data):
    return {k: str(data.get(k)).strip()[:300] for k in KEYS if data.get(k) not in (None, "")}


def record(con, case_id, user_sub, data, source="chat"):
    """One request per case and destination: later details update it rather than adding a new row."""
    d = _clean(data or {})
    if not d.get("country") and not d.get("product"):
        return {"error": "product or country required"}
    company = None
    if case_id:
        r = con.execute("SELECT company_id, owner_sub FROM cases WHERE id=?", (case_id,)).fetchone()
        company = r["company_id"] if r else None
        user_sub = user_sub or (r["owner_sub"] if r else None)
    t = db.now()
    row = None
    if case_id:
        for r in con.execute("SELECT * FROM lane_requests WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall():
            same_country = not d.get("country") or not r["country"] or r["country"].lower() == d["country"].lower()
            same_product = not d.get("product") or not r["product"] or r["product"].lower() == d["product"].lower()
            if same_country and same_product:
                row = r
                break
    if row:
        sets = ", ".join(f"{k}=?" for k in d)
        con.execute(f"UPDATE lane_requests SET {sets}, updated_at=? WHERE id=?", (*d.values(), t, row["id"]))
        rid = row["id"]
    else:
        rid = str(uuid.uuid4())
        con.execute("INSERT INTO lane_requests(id, case_id, company_id, user_sub, product, country, timing, volume, buyer, notes, "
                    "source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, case_id, company, user_sub, *(d.get(k) for k in KEYS), source, t, t))
    con.commit()
    db.log_event(con, case_id, user_sub or "agent", "lane_request", {"id": rid, **d, "source": source})
    return {"ok": True, "request_id": rid}


def latest(con, case_id):
    r = con.execute("SELECT * FROM lane_requests WHERE case_id=? ORDER BY created_at DESC, id DESC LIMIT 1", (case_id,)).fetchone()
    return dict(r) if r else None


def add_details(con, case_id, who, data):
    """The three optional questions on the project page: when, how much, buyer. Updates the project's request."""
    r = latest(con, case_id)
    if r is None:
        return 404, {"error": "no_request"}
    d = _clean({k: data.get(k) for k in ("timing", "volume", "buyer")})
    sets = {k: d.get(k) for k in ("timing", "volume", "buyer")}  # empty answers clear the field
    con.execute("UPDATE lane_requests SET timing=?, volume=?, buyer=?, updated_at=? WHERE id=?", (sets["timing"], sets["volume"], sets["buyer"], db.now(), r["id"]))
    con.commit()
    db.log_event(con, case_id, who["user"], "lane_details", {k: v for k, v in sets.items() if v})
    return 200, {"ok": True, **{k: v or "" for k, v in sets.items()}}


def listing(con, limit=200):
    rows = [dict(r) for r in con.execute(
        "SELECT l.*, co.legal_name AS company FROM lane_requests l LEFT JOIN companies co ON co.id=l.company_id "
        "ORDER BY l.updated_at DESC LIMIT ?", (limit,)).fetchall()]
    count = lambda key: sorted(((k, n) for k, n in _tally(rows, key).items()), key=lambda kv: (-kv[1], kv[0]))
    return {"total": len(rows), "by_country": [{"name": k, "n": n} for k, n in count("country")],
            "by_product": [{"name": k, "n": n} for k, n in count("product")], "requests": rows}


def _tally(rows, key):
    out = {}
    for r in rows:
        k = (r.get(key) or "(not given)").strip()
        k = k[:1].upper() + k[1:] if key == "country" else k.lower()
        out[k] = out.get(k, 0) + 1
    return out
