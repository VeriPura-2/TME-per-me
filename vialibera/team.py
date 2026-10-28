"""Team management for a company. Only owners may change people; everyone active may see the list."""
import secrets
from datetime import datetime, timedelta, timezone

from . import db, permissions

INVITE_DAYS = 14


def _label(con, who, label):
    """Remember what the browser calls this person (their email). Display only."""
    cid = permissions.company_of(con, who["user"])
    if cid and label:
        con.execute("UPDATE memberships SET label=? WHERE company_id=? AND user_sub=?",
                    (str(label)[:120], cid, who["user"]))
        con.commit()


def overview(con, who, label=None):
    cid = permissions.company_of(con, who["user"])
    if not cid:
        return 200, {"company": None, "role": None, "members": [], "roles": list(permissions.ROLES)}
    _label(con, who, label)
    role = permissions.role_in(con, cid, who["user"])
    co = con.execute("SELECT legal_name, vat, plan FROM companies WHERE id=?", (cid,)).fetchone()
    rows = con.execute("SELECT user_sub, role, status, label FROM memberships WHERE company_id=? ORDER BY created_at", (cid,)).fetchall()
    members = [{"user": r["user_sub"], "label": r["label"] or "", "role": r["role"], "status": r["status"],
                "me": r["user_sub"] == who["user"]} for r in rows
               if r["status"] == "active" or role == "owner"]  # only owners see pending requests
    out = {"company": {"name": co["legal_name"], "vat": co["vat"], "plan": co["plan"]}, "role": role,
           "members": members, "roles": list(permissions.ROLES), "can_manage": permissions.allowed(role, "team")}
    return 200, out


def _owner_only(con, who):
    cid = permissions.company_of(con, who["user"])
    if not cid or not permissions.allowed(permissions.role_in(con, cid, who["user"]), "team"):
        return None
    return cid


def decide(con, who, user, approve):
    cid = _owner_only(con, who)
    if not cid:
        return 403, {"error": "forbidden"}
    row = con.execute("SELECT status FROM memberships WHERE company_id=? AND user_sub=?", (cid, user)).fetchone()
    if row is None or row["status"] != "pending":
        return 404, {"error": "no pending request"}
    if approve:
        con.execute("UPDATE memberships SET status='active', role='member' WHERE company_id=? AND user_sub=?", (cid, user))
        con.execute("UPDATE documents SET company_id=? WHERE owner_sub=? AND company_id IS NULL", (cid, user))
    else:
        con.execute("DELETE FROM memberships WHERE company_id=? AND user_sub=?", (cid, user))
    con.commit()
    db.log_event(con, None, who["user"], "team_decision", {"company": cid, "user": user, "approved": bool(approve)})
    return 200, {"ok": True}


def set_role(con, who, user, role):
    cid = _owner_only(con, who)
    if not cid:
        return 403, {"error": "forbidden"}
    if role not in permissions.ROLES:
        return 400, {"error": "unknown role"}
    cur = permissions.role_in(con, cid, user)
    if cur is None:
        return 404, {"error": "not a member"}
    if cur == "owner" and role != "owner" and permissions.owners_count(con, cid) <= 1:
        return 400, {"error": "last_owner"}
    con.execute("UPDATE memberships SET role=? WHERE company_id=? AND user_sub=?", (role, cid, user))
    con.commit()
    db.log_event(con, None, who["user"], "team_role", {"company": cid, "user": user, "role": role})
    return 200, {"ok": True}


def remove(con, who, user):
    cid = _owner_only(con, who)
    if not cid:
        return 403, {"error": "forbidden"}
    cur = permissions.role_in(con, cid, user)
    if cur is None:
        return 404, {"error": "not a member"}
    if cur == "owner" and permissions.owners_count(con, cid) <= 1:
        return 400, {"error": "last_owner"}
    con.execute("DELETE FROM memberships WHERE company_id=? AND user_sub=?", (cid, user))
    con.commit()
    db.log_event(con, None, who["user"], "team_removed", {"company": cid, "user": user})
    return 200, {"ok": True}


def invite(con, who, role):
    cid = _owner_only(con, who)
    if not cid:
        return 403, {"error": "forbidden"}
    if role not in permissions.ROLES:
        return 400, {"error": "unknown role"}
    token = secrets.token_urlsafe(24)
    exp = (datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)).isoformat(timespec="seconds")
    con.execute("INSERT INTO team_invites(token, company_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, cid, role, who["user"], exp, db.now()))
    con.commit()
    return 200, {"token": token, "role": role, "expires_at": exp}


def accept(con, who, token):
    r = con.execute("SELECT * FROM team_invites WHERE token=?", (token,)).fetchone()
    if r is None or r["used_by"] or r["expires_at"] < db.now():
        return 400, {"error": "invite_invalid"}
    existing = con.execute("SELECT status FROM memberships WHERE company_id=? AND user_sub=?", (r["company_id"], who["user"])).fetchone()
    if existing:
        con.execute("UPDATE memberships SET status='active', role=? WHERE company_id=? AND user_sub=?", (r["role"], r["company_id"], who["user"]))
    else:
        con.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                    (r["company_id"], who["user"], r["role"], "active", db.now()))
    con.execute("UPDATE team_invites SET used_by=? WHERE token=?", (who["user"], token))
    con.execute("UPDATE documents SET company_id=? WHERE owner_sub=? AND company_id IS NULL", (r["company_id"], who["user"]))
    con.commit()
    db.log_event(con, None, who["user"], "team_joined", {"company": r["company_id"], "role": r["role"]})
    return 200, {"ok": True, "role": r["role"]}
