"""Invites and promotional credits.

An invite is a personal link. The invitee signs up as usual. When the invitee's company takes its first
real paid month, both sides receive a credit. Credits reduce item prices and the monthly fee.
Amounts and expiry come from VeriPura (menu.INVITE), never from this code.
No identities leak to the inviter: the list shows only status.
"""
import datetime as dt
import os
import secrets

from . import db, permissions


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_or_create(con, user):
    row = con.execute("SELECT code FROM invites WHERE inviter_sub=?", (user,)).fetchone()
    if row:
        return row["code"]
    code = secrets.token_urlsafe(6)
    con.execute("INSERT INTO invites(code, inviter_sub, created_at) VALUES (?,?,?)", (code, user, db.now()))
    con.commit()
    return code


def accept(con, invitee, code):
    """Tie a new user to an inviter. First invite wins. Returns a status string."""
    row = con.execute("SELECT inviter_sub FROM invites WHERE code=?", (code or "",)).fetchone()
    if row is None:
        return "invalid"
    if row["inviter_sub"] == invitee:
        return "self"
    if con.execute("SELECT 1 FROM invite_uses WHERE invitee_sub=?", (invitee,)).fetchone():
        return "already"
    con.execute("INSERT INTO invite_uses(invitee_sub, code, accepted_at) VALUES (?,?,?)", (invitee, code, db.now()))
    con.commit()
    return "ok"


def stats(con, inviter):
    code = get_or_create(con, inviter)
    rows = con.execute("SELECT accepted_at, granted_at FROM invite_uses WHERE code=? ORDER BY accepted_at", (code,)).fetchall()
    return {"code": code,
            "invitees": [{"n": i + 1, "status": "credited" if r["granted_at"] else "joined"} for i, r in enumerate(rows)],
            "balance_cents": balance(con, inviter)}


def _company(con, sub):
    return permissions.company_of(con, sub)


def holder(con, user):
    """Who holds this person's credit: their company once they have one (the company pays), else the person."""
    cid = _company(con, user)
    return "co:" + cid if cid else user


def _holders(con, user):
    """Where this person can draw credit: the company's, then any they earned before joining one."""
    h = holder(con, user)
    return [h] if h == user else [h, user]


def on_first_paid_month(con, invitee, amount_cents, expiry_days, simulated=False):
    """Grant credit to inviter and invitee. Safe to call repeatedly: it pays out once per invitee."""
    if not amount_cents:
        return "no_amount_set"  # VeriPura has not set the amount yet, so nothing is granted
    use = con.execute("SELECT code, granted_at FROM invite_uses WHERE invitee_sub=?", (invitee,)).fetchone()
    if use is None:
        return "not_invited"
    if use["granted_at"]:
        return "already_granted"
    inviter = con.execute("SELECT inviter_sub FROM invites WHERE code=?", (use["code"],)).fetchone()["inviter_sub"]
    ci, cv = _company(con, inviter), _company(con, invitee)
    if ci and cv and ci == cv:
        return "same_company"
    cap = int(os.environ.get("INVITE_MAX_CREDITED", "10"))
    n = con.execute("SELECT COUNT(*) AS n FROM invite_uses u JOIN invites i ON i.code=u.code "
                    "WHERE i.inviter_sub=? AND u.granted_at IS NOT NULL", (inviter,)).fetchone()["n"]
    if n >= cap:
        return "inviter_cap"
    exp = _iso(_now() + dt.timedelta(days=expiry_days))
    for who in (holder(con, inviter), holder(con, invitee)):
        con.execute("INSERT INTO credit_ledger(user_sub, delta_cents, kind, code, at, expires_at, simulated, note) "
                    "VALUES (?,?,?,?,?,?,?,?)", (who, amount_cents, "grant", use["code"], db.now(), exp,
                                                 1 if simulated else 0, "invite"))
    con.execute("UPDATE invite_uses SET granted_at=? WHERE invitee_sub=?", (db.now(), invitee))
    db.log_event(con, None, invitee, "invite_credit_granted", {"code": use["code"], "cents": amount_cents, "simulated": simulated})
    con.commit()
    return "granted"


def _bal(con, holder_key):
    t = _iso(_now())
    g = con.execute("SELECT COALESCE(SUM(delta_cents),0) AS n FROM credit_ledger WHERE user_sub=? AND kind='grant' "
                    "AND (expires_at IS NULL OR expires_at > ?)", (holder_key, t)).fetchone()["n"]
    u = con.execute("SELECT COALESCE(SUM(delta_cents),0) AS n FROM credit_ledger WHERE user_sub=? AND kind='use'",
                    (holder_key,)).fetchone()["n"]
    return max(0, g + u)


def balance(con, user):
    return sum(_bal(con, h) for h in _holders(con, user))


def has_simulated(con, user):
    return any(con.execute("SELECT 1 FROM credit_ledger WHERE user_sub=? AND simulated=1", (h,)).fetchone()
               for h in _holders(con, user))


def apply(con, user, due_cents, case_ref=None):
    """Use credit against an amount, company credit first. Returns the cents used. Never goes below zero."""
    left = max(0, int(due_cents))
    used = 0
    for h in _holders(con, user):
        take = min(_bal(con, h), left)
        if take > 0:
            sim = 1 if con.execute("SELECT 1 FROM credit_ledger WHERE user_sub=? AND simulated=1", (h,)).fetchone() else 0
            con.execute("INSERT INTO credit_ledger(user_sub, delta_cents, kind, code, at, simulated, note) VALUES (?,?,?,?,?,?,?)",
                        (h, -take, "use", None, db.now(), sim, case_ref))
            left -= take
            used += take
    if used:
        con.commit()
    return used
