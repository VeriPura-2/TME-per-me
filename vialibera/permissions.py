"""Who may do what inside a company. One place, used by every handler.

Roles live in memberships (our own database). The company pays, so the plan and the payment sit on the company.
VeriPura superadmin: Auth0 roles claim contains STAFF_CLAIM (assigned only in Auth0, never in our database). It works across
all companies, every access to a company case is written to the events log (staff_access), and it cannot pay for a company.
"""
STAFF_CLAIM = "veripura_superadmin"
SUPPORT_CLAIM = "veripura_support"   # read-only helper: sees companies, cases and the work queue, changes nothing
ROLES = ("owner", "manager", "member", "reviewer")  # company roles; "staff" is separate (superadmin)

# action -> roles allowed
ACTIONS = {
    "read":  ("owner", "manager", "member", "reviewer", "staff", "support"),
    "write": ("owner", "manager", "member", "staff"),      # chat, upload, edit documents, fill forms
    "order": ("owner", "manager"),                         # approve services and pay (staff cannot pay for a company)
    "plan":  ("owner", "staff"),                           # choose or change the company plan
    "team":  ("owner", "staff"),                           # approve people, change roles, invite, remove
}


def allowed(role, action):
    return role in ACTIONS.get(action, ())


def is_superadmin(who):
    return bool(who) and STAFF_CLAIM in (who.get("roles") or [])


def is_support(who):
    return bool(who) and SUPPORT_CLAIM in (who.get("roles") or [])


def is_staff(who):
    """Any VeriPura staff member: superadmin (full) or support (read only)."""
    return is_superadmin(who) or is_support(who)


def staff_level(who):
    return "superadmin" if is_superadmin(who) else "support" if is_support(who) else None


def audit_staff(con, who, case_row, action):
    """Log one line each time a superadmin touches a company case that is not their own."""
    from . import db
    db.log_event(con, case_row["id"] if "id" in case_row.keys() else None, who["user"], "staff_access",
                 {"action": action, "company": case_row["company_id"]})


def role_in(con, company_id, user_sub):
    r = con.execute("SELECT role FROM memberships WHERE company_id=? AND user_sub=? AND status='active'",
                    (company_id, user_sub)).fetchone()
    return r["role"] if r else None


def company_of(con, user_sub):
    """The company this person works for (first active membership), or None."""
    r = con.execute("SELECT company_id FROM memberships WHERE user_sub=? AND status='active' ORDER BY created_at LIMIT 1",
                    (user_sub,)).fetchone()
    return r["company_id"] if r else None


def my_role(con, who):
    """Role in the person's own company. No company yet (still exploring) means full rights over their own work."""
    if who is None:
        return "owner"
    cid = company_of(con, who["user"])
    if cid:
        return role_in(con, cid, who["user"])
    return {"superadmin": "staff", "support": "support"}.get(staff_level(who), "owner")


def case_role(con, case_row, who):
    """Role on one case. Cases of a company follow membership only; other cases belong to whoever started them."""
    if who is None:
        return "owner"
    if case_row["company_id"]:
        r = role_in(con, case_row["company_id"], who["user"])
        if r is None and is_staff(who):
            return "staff" if is_superadmin(who) else "support"
        return r
    if case_row["owner_sub"] == who["user"]:
        return "owner"
    if case_row["org_id"] and case_row["org_id"] == who.get("org"):
        return "member"
    return None


def can(con, who, action):
    return allowed(my_role(con, who), action)


def owners_count(con, company_id):
    return con.execute("SELECT COUNT(*) AS n FROM memberships WHERE company_id=? AND role='owner' AND status='active'",
                       (company_id,)).fetchone()["n"]
