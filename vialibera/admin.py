"""VeriPura superadmin screens and actions. Every handler refuses anyone without the superadmin claim.

Reading a company is logged (staff_access). Changing a company is logged (staff_change). Nothing here pays for a company.
"""
import json

from . import db, invites, permissions, plans


def _guard(who):
    return who is not None and permissions.is_superadmin(who)


def _log(con, who, kind, company, **data):
    db.log_event(con, None, who["user"], kind, {"company": company, **data})


def companies(con, who):
    """One row per company with the things staff look for first."""
    if not _guard(who):
        return 403, {"error": "forbidden"}
    from .app import TERMS_VERSION
    rows = []
    for co in con.execute("SELECT id, vat, legal_name, status, plan, created_at FROM companies ORDER BY created_at DESC").fetchall():
        m = con.execute("SELECT SUM(status='active') AS a, SUM(status='pending') AS p FROM memberships WHERE company_id=?", (co["id"],)).fetchone()
        n = con.execute("SELECT COUNT(*) AS n, MAX(updated_at) AS last FROM cases WHERE company_id=?", (co["id"],)).fetchone()
        cc = con.execute("SELECT 1 FROM company_consents WHERE company_id=? AND terms_version=?", (co["id"], TERMS_VERSION)).fetchone()
        rows.append({"id": co["id"], "name": co["legal_name"], "vat": co["vat"], "status": co["status"], "plan": co["plan"],
                     "members": m["a"] or 0, "pending": m["p"] or 0, "cases": n["n"], "last_activity": n["last"],
                     "terms_accepted": bool(cc), "created_at": co["created_at"]})
    return 200, {"companies": rows, "plans": list(plans.PLANS)}


def company(con, who, cid):
    if not _guard(who):
        return 403, {"error": "forbidden"}
    co = con.execute("SELECT id, vat, legal_name, status, plan, created_at FROM companies WHERE id=?", (cid,)).fetchone()
    if co is None:
        return 404, {"error": "no such company"}
    members = [dict(r) for r in con.execute(
        "SELECT user_sub AS user, role, status, label FROM memberships WHERE company_id=? ORDER BY created_at", (cid,)).fetchall()]
    cases = []
    for r in con.execute("SELECT id, status, product, market, updated_at FROM cases WHERE company_id=? ORDER BY updated_at DESC", (cid,)).fetchall():
        prod, mkt = json.loads(r["product"] or "{}"), json.loads(r["market"] or "{}")
        cases.append({"id": r["id"], "status": r["status"], "product": prod.get("name_brand") or prod.get("category"),
                      "country": mkt.get("country"), "updated_at": r["updated_at"]})
    events = [{"at": e["at"], "actor": e["actor"], "kind": e["kind"]} for e in con.execute(
        "SELECT e.at, e.actor, e.kind FROM events e JOIN cases c ON c.id=e.case_id WHERE c.company_id=? ORDER BY e.id DESC LIMIT 30", (cid,)).fetchall()]
    owner = next((m["user"] for m in members if m["role"] == "owner" and m["status"] == "active"), None)
    credit = invites.balance(con, owner) if owner else 0
    _log(con, who, "staff_access", cid, action="view_company")
    return 200, {"company": dict(co), "members": members, "cases": cases, "events": events, "credit": credit}


def audit(con, who, limit=100):
    """Who on staff looked at or changed what. Superadmins only."""
    if not _guard(who):
        return 403, {"error": "forbidden"}
    rows = con.execute("SELECT at, actor, kind, data FROM events WHERE kind IN ('staff_access','staff_change') ORDER BY id DESC LIMIT ?",
                       (min(int(limit), 500),)).fetchall()
    return 200, {"events": [{"at": r["at"], "actor": r["actor"], "kind": r["kind"], "data": json.loads(r["data"])} for r in rows]}


def verify(con, who, cid, verified=True):
    """Staff confirm the VAT number is real (VIES or the company's own papers)."""
    if not _guard(who):
        return 403, {"error": "forbidden"}
    if con.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone() is None:
        return 404, {"error": "no such company"}
    con.execute("UPDATE companies SET status=? WHERE id=?", ("verified" if verified else "unverified", cid))
    con.commit()
    _log(con, who, "staff_change", cid, action="verify", verified=bool(verified))
    return 200, {"ok": True}


def set_plan(con, who, cid, plan):
    if not _guard(who):
        return 403, {"error": "forbidden"}
    if plan not in plans.PLANS:
        return 400, {"error": "unknown plan"}
    old = con.execute("SELECT plan FROM companies WHERE id=?", (cid,)).fetchone()
    if old is None:
        return 404, {"error": "no such company"}
    con.execute("UPDATE companies SET plan=? WHERE id=?", (plan, cid))
    con.commit()
    _log(con, who, "staff_change", cid, action="set_plan", old=old["plan"], new=plan)
    return 200, {"ok": True}
