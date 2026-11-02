"""VeriPura superadmin screens and actions. Every handler refuses anyone without the superadmin claim.

Reading a company is logged (staff_access). Changing a company is logged (staff_change). Nothing here pays for a company.
"""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from . import db, invites, permissions, plans, team


def _guard(who):
    """Read access: superadmin or support."""
    return who is not None and permissions.is_staff(who)


def _full(who):
    """Change access: superadmin only."""
    return who is not None and permissions.is_superadmin(who)


def _log(con, who, kind, company, **data):
    db.log_event(con, None, who["user"], kind, {"company": company, **data})


def companies(con, who):
    """One row per company with the things staff look for first."""
    if not _guard(who):
        return 403, {"error": "forbidden"}
    from .app import TERMS_VERSION
    rows = []
    for co in con.execute("SELECT id, vat, legal_name, status, plan, created_by, created_at, vies_state FROM companies ORDER BY created_at DESC").fetchall():
        m = con.execute("SELECT COALESCE(SUM(CASE WHEN status='active' THEN 1 ELSE 0 END),0) AS a, COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) AS p FROM memberships WHERE company_id=?", (co["id"],)).fetchone()
        n = con.execute("SELECT COUNT(*) AS n, MAX(updated_at) AS last FROM cases WHERE company_id=?", (co["id"],)).fetchone()
        cc = con.execute("SELECT 1 FROM company_consents WHERE company_id=? AND terms_version=?", (co["id"], TERMS_VERSION)).fetchone()
        rows.append({"id": co["id"], "name": co["legal_name"], "vat": co["vat"], "status": co["status"], "plan": co["plan"],
                     "members": m["a"] or 0, "pending": m["p"] or 0, "cases": n["n"], "last_activity": n["last"],
                     "terms_accepted": bool(cc), "created_at": co["created_at"], "by_staff": bool(co["created_by"]),
                     "vies": co["vies_state"]})
    return 200, {"companies": rows, "plans": list(plans.PLANS)}


def company(con, who, cid):
    if not _guard(who):
        return 403, {"error": "forbidden"}
    co = con.execute("SELECT id, vat, legal_name, status, plan, created_by, created_at, vies_state, vies_name, vies_address, "
                     "vies_checked_at FROM companies WHERE id=?", (cid,)).fetchone()
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
    if not _full(who):
        return 403, {"error": "forbidden"}
    rows = con.execute("SELECT at, actor, kind, data FROM events WHERE kind IN ('staff_access','staff_change') ORDER BY id DESC LIMIT ?",
                       (min(int(limit), 500),)).fetchall()
    return 200, {"events": [{"at": r["at"], "actor": r["actor"], "kind": r["kind"], "data": json.loads(r["data"])} for r in rows]}


def verify(con, who, cid, verified=True):
    """Staff confirm the VAT number is real (VIES or the company's own papers)."""
    if not _full(who):
        return 403, {"error": "forbidden"}
    if con.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone() is None:
        return 404, {"error": "no such company"}
    con.execute("UPDATE companies SET status=? WHERE id=?", ("verified" if verified else "unverified", cid))
    con.commit()
    _log(con, who, "staff_change", cid, action="verify", verified=bool(verified))
    return 200, {"ok": True}


def set_plan(con, who, cid, plan):
    if not _full(who):
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


WORK_STATES = ("paid", "in progress", "review")
STAFF_TARGETS = ("in progress", "review", "delivered")


def queue(con, who):
    """What staff owe clients: paid or running items that staff must do (managed level, compliance), oldest first."""
    if not _guard(who):
        return 403, {"error": "forbidden"}
    managed = plans.LEVELS[3]["items"]
    marks = ",".join("?" * len(managed))
    rows = con.execute(
        "SELECT i.id, i.code, i.state, i.is_compliance, i.updated_at, i.case_id, c.company_id, co.legal_name, c.product, c.market "
        "FROM items i JOIN cases c ON c.id=i.case_id LEFT JOIN companies co ON co.id=c.company_id "
        f"WHERE i.state IN ('paid','in progress','review') AND (i.code IN ({marks}) OR i.is_compliance=1 OR i.state='review') "
        "ORDER BY i.updated_at ASC", managed).fetchall()
    items = []
    for r in rows:
        prod, mkt = json.loads(r["product"] or "{}"), json.loads(r["market"] or "{}")
        items.append({"id": r["id"], "code": r["code"], "state": r["state"], "compliance": bool(r["is_compliance"]),
                      "since": r["updated_at"], "case": r["case_id"], "company_id": r["company_id"], "company": r["legal_name"],
                      "product": prod.get("name_brand") or prod.get("category"), "country": mkt.get("country")})
    unverified = [{"id": r["id"], "name": r["legal_name"], "vat": r["vat"]} for r in con.execute(
        "SELECT id, legal_name, vat FROM companies WHERE status='unverified' ORDER BY created_at").fetchall()]
    return 200, {"items": items, "unverified": unverified}


def set_item(con, who, item_id, state):
    """Staff move an item forward. The gates still apply: no work before payment, compliance needs review before delivery."""
    if not _full(who):
        return 403, {"error": "forbidden"}
    if state not in STAFF_TARGETS:
        return 400, {"error": "state not allowed"}
    row = con.execute("SELECT i.state, c.company_id FROM items i JOIN cases c ON c.id=i.case_id WHERE i.id=?", (item_id,)).fetchone()
    if row is None:
        return 404, {"error": "no such item"}
    from . import gates
    try:
        gates.set_state(con, item_id, state, "staff")
    except gates.GateError as e:
        return 400, {"error": "gate", "detail": str(e)}
    con.commit()
    _log(con, who, "staff_change", row["company_id"], action="item_state", item=item_id, old=row["state"], new=state)
    return 200, {"ok": True}


def add_company(con, who, vat, name):
    """Assisted onboarding. Staff create the company record and an owner invite for the client.

    Limits: staff are never a member or owner, never accept terms for the company, and the record shows who created it.
    The client becomes owner by opening the invite link and then accepts the terms themselves.
    """
    if not _full(who):
        return 403, {"error": "forbidden"}
    from . import vat_check
    v, err = vat_check.italian(vat)
    if err:
        return 400, {"error": "invalid_vat", "detail": err}
    name = (name or "").strip()[:200]
    if not name:
        return 400, {"error": "name required"}
    if con.execute("SELECT 1 FROM companies WHERE vat=?", (v,)).fetchone():
        return 409, {"error": "company exists"}
    cid = str(uuid.uuid4())
    con.execute("INSERT INTO companies(id, vat, legal_name, created_by, created_at) VALUES (?,?,?,?,?)",
                (cid, v, name, who["user"], db.now()))
    con.commit()
    _log(con, who, "staff_change", cid, action="add_company", vat=v)
    vat_check.check_company(con, cid)
    return 200, {"ok": True, "company": cid, **owner_invite(con, who, cid)[1]}


def owner_invite(con, who, cid):
    """Single-use owner link for the client (valid 14 days). Staff only; nothing is sent automatically."""
    if not _full(who):
        return 403, {"error": "forbidden"}
    if con.execute("SELECT 1 FROM companies WHERE id=?", (cid,)).fetchone() is None:
        return 404, {"error": "no such company"}
    token = secrets.token_urlsafe(24)
    exp = (datetime.now(timezone.utc) + timedelta(days=team.INVITE_DAYS)).isoformat(timespec="seconds")
    con.execute("INSERT INTO team_invites(token, company_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, cid, "owner", who["user"], exp, db.now()))
    con.commit()
    _log(con, who, "staff_change", cid, action="owner_invite")
    return 200, {"token": token, "expires_at": exp}
