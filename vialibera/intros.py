"""Exporters looking for a TEM (Thomas, 20 Nov 2026).

An exporter asks for a TEM introduction from the tour, agreeing that MioTEM may show the company name, product and
destination to TEMs on MioTEM. Every TEM firm sees open requests and may offer to help, with an optional note.
MioTEM staff then arrange the introduction by hand and mark the request introduced. No contact details reach TEMs,
and there is no messaging between exporter and TEM.

A request belongs to one project. The exporter can withdraw it at any time; it then disappears from every TEM list.
"""
import uuid

from . import db, permissions

CONSENT = "may show company name, product and destination to TEMs on MioTEM, and contact about an introduction"


def _demo_sql(col):
    from . import tems
    return tems.DEMO_SQL.replace("vat", col)


def _open(con, case_id):
    return con.execute("SELECT * FROM intro_requests WHERE case_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",
                       (case_id,)).fetchone()


def open_request(con, case_id, who, email=None):
    """Called once the exporter answered yes, with consent, to the tour's TEM question. One open request per project."""
    have = _open(con, case_id)
    if have:
        return have["id"]
    row = con.execute("SELECT company_id FROM cases WHERE id=?", (case_id,)).fetchone()
    rid = str(uuid.uuid4())
    con.execute("INSERT INTO intro_requests(id, case_id, company_id, user_sub, email, consent, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (rid, case_id, row["company_id"] if row else None, who["user"], (str(email or "").strip()[:254] or None),
                 CONSENT, "open", db.now()))
    con.commit()
    db.log_event(con, case_id, who["user"], "intro_requested", {"request": rid})
    return rid


def withdraw(con, who, case_id):
    r = _open(con, case_id)
    if r is None:
        return 200, {"ok": True}
    con.execute("UPDATE intro_requests SET status='withdrawn', closed_at=?, closed_by=? WHERE id=?", (db.now(), who["user"], r["id"]))
    con.commit()
    db.log_event(con, case_id, who["user"], "intro_withdrawn", {"request": r["id"]})
    return 200, {"ok": True}


def _offers(con, request_id):
    return [dict(o) for o in con.execute(
        "SELECT o.firm_id, f.name AS firm, o.note, o.created_at FROM intro_offers o JOIN tem_firms f ON f.id=o.firm_id "
        "WHERE o.request_id=? ORDER BY o.created_at", (request_id,)).fetchall()]


def status(con, case_id):
    """What the exporter sees on the project: the latest request (open or introduced) and the firms that offered."""
    r = con.execute("SELECT * FROM intro_requests WHERE case_id=? AND status IN ('open','introduced') ORDER BY created_at DESC LIMIT 1",
                    (case_id,)).fetchone()
    if r is None:
        return 200, {"request": None}
    return 200, {"request": {"status": r["status"], "since": r["created_at"],
                             "offers": [o["firm"] for o in _offers(con, r["id"])]}}


def _describe(con, r):
    case = db.case_read(con, r["case_id"])
    co = con.execute("SELECT legal_name FROM companies WHERE id=?", (r["company_id"],)).fetchone() if r["company_id"] else None
    p = case["product"]
    extra = p.get("denomination") or p.get("name_brand")
    return {"id": r["id"], "company": (co["legal_name"] if co and co["legal_name"] else case["company"].get("legal_name")) or None,
            "category": p.get("category"), "product": extra, "country": case["market"].get("country"), "since": r["created_at"]}


def tem_list(con, who):
    """Open requests for a TEM firm: not demo companies, not the firm's existing clients."""
    from . import tems
    f = tems.firm_of(con, who["user"]) if who else None
    if not f:
        return 403, {"error": "forbidden"}
    rows = con.execute(
        "SELECT r.* FROM intro_requests r LEFT JOIN companies co ON co.id=r.company_id WHERE r.status='open' "
        "AND (r.company_id IS NULL OR NOT " + _demo_sql("co.vat") + ") "
        "AND NOT EXISTS (SELECT 1 FROM tem_clients t WHERE t.firm_id=? AND t.company_id=r.company_id AND t.status='active') "
        "ORDER BY r.created_at DESC LIMIT 100", (f["firm_id"],)).fetchall()
    out = []
    for r in rows:
        d = _describe(con, r)
        mine = con.execute("SELECT note FROM intro_offers WHERE request_id=? AND firm_id=?", (r["id"], f["firm_id"])).fetchone()
        d["offered"] = mine is not None
        out.append(d)
    return 200, {"requests": out}


def offer(con, who, request_id, note=None):
    from . import tems
    f = tems.firm_of(con, who["user"]) if who else None
    if not f:
        return 403, {"error": "forbidden"}
    r = con.execute("SELECT * FROM intro_requests WHERE id=?", (request_id,)).fetchone()
    if r is None or r["status"] != "open":
        return 404, {"error": "no open request"}
    if con.execute("SELECT 1 FROM intro_offers WHERE request_id=? AND firm_id=?", (request_id, f["firm_id"])).fetchone():
        return 200, {"ok": True, "already": True}
    con.execute("INSERT INTO intro_offers(id, request_id, case_id, firm_id, user_sub, note, created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), request_id, r["case_id"], f["firm_id"], who["user"], (str(note or "").strip()[:500] or None), db.now()))
    con.commit()
    db.log_event(con, r["case_id"], who["user"], "intro_offered", {"request": request_id, "firm": f["firm_id"]})
    return 200, {"ok": True}


def staff_list(con, who):
    if not permissions.is_staff(who):
        return 403, {"error": "forbidden"}
    out = []
    for r in con.execute("SELECT * FROM intro_requests WHERE status IN ('open','introduced') ORDER BY created_at DESC LIMIT 200").fetchall():
        d = _describe(con, r)
        d.update({"status": r["status"], "email": r["email"], "offers": _offers(con, r["id"])})
        out.append(d)
    return 200, {"requests": out}


def mark_introduced(con, who, request_id):
    if not permissions.is_superadmin(who):
        return 403, {"error": "forbidden"}
    r = con.execute("SELECT * FROM intro_requests WHERE id=?", (request_id,)).fetchone()
    if r is None:
        return 404, {"error": "no such request"}
    con.execute("UPDATE intro_requests SET status='introduced', closed_at=?, closed_by=? WHERE id=?", (db.now(), who["user"], request_id))
    con.commit()
    db.log_event(con, r["case_id"], who["user"], "intro_introduced", {"request": request_id})
    return 200, {"ok": True}
