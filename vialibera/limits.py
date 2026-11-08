"""Project limits and the free check, from plans.py.

Covered project: a product and destination MioTEM has verified requirements for (requirements.covers).
Uncovered project: anything else. It is created, has no checklist, and never counts toward the covered limit.

Explore: the covered slot is used up for good once taken (deleting does not restore it). Paid plans count live projects.
Uncovered projects always count live, because they are deleted after 90 days.
Accounts that already had a project before LIMITS_START are grandfathered (test accounts at launch).
"""
from . import plans, permissions, requirements, accounts, db

LIMITS_START = "2026-11-09"


def owner_key(con, user_sub):
    return permissions.company_of(con, user_sub) or "u:" + user_sub


def _grandfathered(con, user_sub):
    key = owner_key(con, user_sub)
    if key.startswith("u:"):
        r = con.execute("SELECT MIN(created_at) AS m FROM cases WHERE owner_sub=?", (user_sub,)).fetchone()
    else:
        r = con.execute("SELECT MIN(created_at) AS m FROM cases WHERE company_id=? OR owner_sub=?", (key, user_sub)).fetchone()
    return bool(r and r["m"] and r["m"] < LIMITS_START)


def _live(con, key, kind):
    return con.execute("SELECT COUNT(*) AS n FROM counted_cases c JOIN cases k ON k.id=c.case_id "
                       "WHERE c.owner_key=? AND c.kind=?", (key, kind)).fetchone()["n"]


def _ever(con, key, kind):
    r = con.execute("SELECT n FROM usage_counts WHERE owner_key=? AND kind=?", (key, kind)).fetchone()
    return r["n"] if r else 0


def _bump(con, key, kind):
    if con.execute("SELECT 1 FROM usage_counts WHERE owner_key=? AND kind=?", (key, kind)).fetchone():
        con.execute("UPDATE usage_counts SET n=n+1 WHERE owner_key=? AND kind=?", (key, kind))
    else:
        con.execute("INSERT INTO usage_counts(owner_key, kind, n) VALUES (?,?,1)", (key, kind))


def _room(con, user_sub, kind):
    plan_id = accounts.get_plan(con, user_sub) or plans.DEFAULT
    plan = plans.get(plan_id)
    key = owner_key(con, user_sub)
    if kind == "covered":
        cap = plan["max_projects"]
        used = _ever(con, key, "covered") if plan_id == plans.DEFAULT else _live(con, key, "covered")
    else:
        cap = plan["max_uncovered"]
        used = _live(con, key, "uncovered")
    return plan_id, cap is None or used < cap


def check_new(con, who, category=None, country=None):
    """Refusal (status, body) when the account has no room for one more project, else None.
    With product or country still unknown the project cannot be classified yet: refused only when neither kind has room."""
    if not who or _grandfathered(con, who["user"]):
        return None
    if category and country:
        kinds = ["covered" if requirements.covers(category, country) else "uncovered"]
    else:
        kinds = ["covered", "uncovered"]
    for kind in kinds:
        plan_id, ok = _room(con, who["user"], kind)
        if ok:
            return None
    return 403, {"error": "plan_limit", "limit": kinds[0] if len(kinds) == 1 else "projects", "plan": plan_id}


def register(con, who, case_id):
    """Count a project once, when it has a product and destination. Safe to call after every change."""
    if not who:
        return
    if con.execute("SELECT 1 FROM counted_cases WHERE case_id=?", (case_id,)).fetchone():
        return
    case = db.case_read(con, case_id)
    cat, country = case["product"].get("category"), case["market"].get("country")
    if not (cat and country):
        return
    kind = "covered" if requirements.covers(cat, country) else "uncovered"
    key = owner_key(con, who["user"])
    con.execute("INSERT INTO counted_cases(case_id, owner_key, kind) VALUES (?,?,?)", (case_id, key, kind))
    if kind == "covered":
        _bump(con, key, "covered")
    con.commit()


def take_free_check(con, who, case_id):
    """Explore: one document or label check in total, on a covered project. Paid plans: always allowed.
    Returns True and uses the check, or False. Nothing in the app calls this yet (see docs)."""
    plan_id = accounts.get_plan(con, who["user"]) or plans.DEFAULT
    allowed = plans.get(plan_id)["free_checks"]
    if plan_id != plans.DEFAULT and allowed is None:
        return True
    key = owner_key(con, who["user"])
    row = con.execute("SELECT kind FROM counted_cases WHERE case_id=?", (case_id,)).fetchone()
    if not row or row["kind"] != "covered":
        return False
    if _grandfathered(con, who["user"]):
        return True
    if _ever(con, key, "free_check") >= (allowed or 0):
        return False
    _bump(con, key, "free_check")
    con.commit()
    return True


def usage(con, user_sub):
    """What the Account page shows: plan, covered and uncovered projects against the caps, and the free check."""
    plan_id = accounts.get_plan(con, user_sub) or plans.DEFAULT
    plan = plans.get(plan_id)
    key = owner_key(con, user_sub)
    cov = _ever(con, key, "covered") if plan_id == plans.DEFAULT else _live(con, key, "covered")
    return {"plan": plan_id,
            "covered": {"used": cov, "cap": plan["max_projects"]},
            "uncovered": {"used": _live(con, key, "uncovered"), "cap": plan["max_uncovered"]},
            "free_check": {"allowed": plan["free_checks"], "used": _ever(con, key, "free_check")},
            "grandfathered": _grandfathered(con, user_sub)}
