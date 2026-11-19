"""Team management for a company. Only owners may change people; everyone active may see the list."""
import secrets
from datetime import datetime, timedelta, timezone

import re

from . import db, notify, permissions

INVITE_DAYS = 14
INVITE_EMAILS_PER_DAY = 20  # per company: an invitation email goes to an address the owner types, so it is capped
_EMAIL = re.compile(r"^[^@\s<>,;\"']{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")

INVITE_MAIL = {
    "it": ("Invito a entrare nel team di {co} su MioTEM",
           "Buongiorno,\n\n{by} La invita a entrare nel team di {co} su MioTEM, con il ruolo {role}.\n\n"
           "Per accettare apra questo link e acceda, o si registri, con questo indirizzo email:\n{link}\n\n"
           "Il link vale {days} giorni e può essere usato una sola volta. Se non conosce chi La invita, ignori questo messaggio.\n\n"
           "MioTEM è gestito da A&O CONSULT S.A.S., Vesime (AT), Italia."),
    "en": ("Invitation to join the team of {co} on MioTEM",
           "Hello,\n\n{by} invites you to join the team of {co} on MioTEM, with the role {role}.\n\n"
           "To accept, open this link and sign in, or sign up, with this email address:\n{link}\n\n"
           "The link is valid for {days} days and can be used once. If you do not know the person inviting you, ignore this message.\n\n"
           "MioTEM is operated by A&O CONSULT S.A.S., Vesime (AT), Italy."),
}
ROLE_NAMES = {"it": {"owner": "Titolare", "manager": "Manager", "member": "Membro", "reviewer": "Revisore"},
              "en": {"owner": "Owner", "manager": "Manager", "member": "Member", "reviewer": "Reviewer"}}


def valid_email(raw):
    e = str(raw or "").strip()
    return e if _EMAIL.match(e) and ".." not in e else None


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
    co = con.execute("SELECT legal_name, vat, plan, created_by, vies_state, vies_checked_at FROM companies WHERE id=?", (cid,)).fetchone()
    rows = con.execute("SELECT user_sub, role, status, label FROM memberships WHERE company_id=? ORDER BY created_at", (cid,)).fetchall()
    members = [{"user": r["user_sub"], "label": r["label"] or "", "role": r["role"], "status": r["status"],
                "me": r["user_sub"] == who["user"]} for r in rows
               if r["status"] == "active" or role == "owner"]  # only owners see pending requests
    from . import accounts
    from .terms import TERMS_VERSION
    cc = con.execute("SELECT at FROM company_consents WHERE company_id=? AND terms_version=?", (cid, TERMS_VERSION)).fetchone()
    from . import vat_check
    out = {"company": {"name": co["legal_name"], "vat": co["vat"], "plan": co["plan"], "vies": co["vies_state"],
                       "vies_checked_at": co["vies_checked_at"],
                       "vies_enrol": {"steps": vat_check.ENROL, "link": vat_check.ENROL_LINK} if co["vies_state"] == "not_in_vies" else None,
                       "terms_accepted_at": cc["at"] if cc else None, "created_by_staff": bool(co["created_by"]),
                       "owner_confirmed": permissions.owner_confirmed(con, cid),
                       "vies_match": vat_check.vies_matched(con, cid)}, "role": role,
           "members": members, "roles": list(permissions.ROLES), "can_manage": permissions.allowed(role, "team")}
    return 200, out


def _owner_only(con, who, company=None, action="team"):
    """The company the caller may manage. A superadmin names the company; the change is logged as staff_change."""
    if company and permissions.is_superadmin(who):
        if con.execute("SELECT 1 FROM companies WHERE id=?", (company,)).fetchone() is None:
            return None
        db.log_event(con, None, who["user"], "staff_change", {"company": company, "action": action})
        return company
    cid = permissions.company_of(con, who["user"])
    if not cid or not permissions.allowed(permissions.role_in(con, cid, who["user"]), "team"):
        return None
    return cid


def decide(con, who, user, approve, company=None):
    cid = _owner_only(con, who, company, "decide")
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


def set_role(con, who, user, role, company=None):
    cid = _owner_only(con, who, company, "set_role")
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


def remove(con, who, user, company=None):
    cid = _owner_only(con, who, company, "remove")
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


def invite(con, who, role, company=None, email=None, lang="en", base_url=""):
    """Create a single-use invite link. With an email address, also send the link to that person.
    The response says what happened to the email: sent, not_configured (no mail settings), failed, or limit."""
    cid = _owner_only(con, who, company, "invite")
    if not cid:
        return 403, {"error": "forbidden"}
    if role not in permissions.ROLES:
        return 400, {"error": "unknown role"}
    to = None
    if email not in (None, ""):
        to = valid_email(email)
        if not to:
            return 400, {"error": "invalid_email"}
    token = secrets.token_urlsafe(24)
    exp = (datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)).isoformat(timespec="seconds")
    con.execute("INSERT INTO team_invites(token, company_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, cid, role, who["user"], exp, db.now()))
    con.commit()
    out = {"token": token, "role": role, "expires_at": exp}
    if to:
        out["email"] = to
        out["email_state"] = _mail_invite(con, who, cid, role, token, to, "it" if lang == "it" else "en", base_url)
    return 200, out


def _mail_invite(con, who, cid, role, token, to, lang, base_url):
    if not notify.can_send() or not base_url:
        return "not_configured"
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    sent = con.execute("SELECT data FROM events WHERE kind='team_invite_emailed' AND at>=?", (since,)).fetchall()
    if sum(1 for r in sent if ('"company": "%s"' % cid) in (r["data"] or "")) >= INVITE_EMAILS_PER_DAY:
        return "limit"
    co = con.execute("SELECT legal_name, vat FROM companies WHERE id=?", (cid,)).fetchone()
    me = con.execute("SELECT label FROM memberships WHERE company_id=? AND user_sub=?", (cid, who["user"])).fetchone()
    subject, body = INVITE_MAIL[lang]
    name = (co["legal_name"] or co["vat"]) if co else ""
    by = (me["label"] if me and me["label"] else None) or {"it": "Un collega", "en": "A colleague"}[lang]
    text = body.format(by=by, co=name, role=ROLE_NAMES[lang][role], link=base_url.rstrip("/") + "/?team=" + token, days=INVITE_DAYS)
    if not notify.send_to(to, subject.format(co=name), text):
        return "failed"
    db.log_event(con, None, who["user"], "team_invite_emailed", {"company": cid, "to": to, "role": role})
    return "sent"


def accept(con, who, token):
    if permissions.is_staff(who):  # staff never become members or owners of a client company
        return 403, {"error": "staff_cannot_join"}
    r = con.execute("SELECT * FROM team_invites WHERE token=?", (token,)).fetchone()
    if r is None or r["used_by"] or r["expires_at"] < db.now():
        return 400, {"error": "invite_invalid"}
    existing = con.execute("SELECT status, role FROM memberships WHERE company_id=? AND user_sub=?", (r["company_id"], who["user"])).fetchone()
    if existing and existing["status"] == "active":
        # already in this company (the owner testing their own link, say): change nothing, keep the link unused.
        # Before 19 Nov 2026 this rewrote the person's role to the invite's role, so an owner could demote themselves.
        db.log_event(con, None, who["user"], "team_accept_already_member", {"company": r["company_id"]})
        return 200, {"ok": True, "role": existing["role"], "already_member": True}
    other = permissions.company_of(con, who["user"])
    if other and other != r["company_id"]:
        # the app works with one company per person; joining a second would burn the link and change nothing the person sees
        return 400, {"error": "already_in_company"}
    if existing:
        con.execute("UPDATE memberships SET status='active', role=? WHERE company_id=? AND user_sub=?", (r["role"], r["company_id"], who["user"]))
    else:
        con.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                    (r["company_id"], who["user"], r["role"], "active", db.now()))
    con.execute("UPDATE team_invites SET used_by=? WHERE token=?", (who["user"], token))
    moved = con.execute("UPDATE documents SET company_id=? WHERE owner_sub=? AND company_id IS NULL", (r["company_id"], who["user"])).rowcount
    con.commit()
    db.log_event(con, None, who["user"], "team_joined", {"company": r["company_id"], "role": r["role"], "documents_moved": moved})
    return 200, {"ok": True, "role": r["role"], "documents_moved": moved}
