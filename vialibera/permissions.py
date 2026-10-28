"""Who may do what inside a company. One place, used by every handler.

Roles live in memberships (our own database). The company pays, so the plan and the payment sit on the company.
VeriPura staff (Auth0 roles claim) are not handled here yet: they have no access to client companies by default.
"""
ROLES = ("owner", "manager", "member", "reviewer")

# action -> roles allowed
ACTIONS = {
    "read":  ("owner", "manager", "member", "reviewer"),
    "write": ("owner", "manager", "member"),      # chat, upload, edit documents, fill forms
    "order": ("owner", "manager"),                # approve services and pay
    "plan":  ("owner",),                          # choose or change the company plan
    "team":  ("owner",),                          # approve people, change roles, invite, remove
}


def allowed(role, action):
    return role in ACTIONS.get(action, ())


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
    return role_in(con, cid, who["user"]) if cid else "owner"


def case_role(con, case_row, who):
    """Role on one case. Cases of a company follow membership only; other cases belong to whoever started them."""
    if who is None:
        return "owner"
    if case_row["company_id"]:
        return role_in(con, case_row["company_id"], who["user"])
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
