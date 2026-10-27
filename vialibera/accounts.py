"""Company accounts built from interview answers. The VAT number is the unique key."""
import re
import uuid

from . import db


EU = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "GB", "HR", "HU", "IE", "LT", "LU",
      "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI"}


def normalise_vat(raw):
    """Return (vat, error). Italian numbers are checked with the standard checksum."""
    v = re.sub(r"[\s.\-/]", "", str(raw or "")).upper()
    if re.fullmatch(r"\d{11}", v):
        v = "IT" + v
    if v.startswith("IT"):
        d = v[2:]
        if not re.fullmatch(r"\d{11}", d):
            return None, "Italian VAT numbers have 11 digits"
        total = 0
        for i, ch in enumerate(d[:10]):
            n = int(ch)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        if (10 - total % 10) % 10 != int(d[10]):
            return None, "VAT number checksum does not match"
        return v, None
    if v[:2] in EU and re.fullmatch(r"[A-Z]{2}[A-Z0-9]{2,12}", v) and any(ch.isdigit() for ch in v):
        return v, None
    return None, "VAT number format not recognised"


def is_member(con, company_id, user_sub, active_only=True):
    row = con.execute("SELECT status FROM memberships WHERE company_id=? AND user_sub=?",
                      (company_id, user_sub)).fetchone()
    return bool(row) and (row["status"] == "active" or not active_only)


def can_access(con, case_row, who):
    """who is None only when sign-in is switched off (dev)."""
    if who is None:
        return True
    if case_row["owner_sub"] == who["user"]:
        return True
    if case_row["company_id"] and is_member(con, case_row["company_id"], who["user"]):
        return True
    return bool(case_row["org_id"]) and case_row["org_id"] == who.get("org")


def attach_company(con, case_id, who):
    """Called after each turn. When the interview has a valid VAT number, create or join the company.

    Returns None, {"status": "created"|"joined"|"access_requested"|"invalid_vat", ...}.
    """
    case = db.case_read(con, case_id)
    raw = case["company"].get("vat_number")
    if not who or not raw or str(raw).lower() == "unknown" or case.get("company_id"):
        return None
    vat, err = normalise_vat(raw)
    if err:
        return {"status": "invalid_vat", "detail": err}
    name = case["company"].get("legal_name")
    row = con.execute("SELECT id FROM companies WHERE vat=?", (vat,)).fetchone()
    t = db.now()
    if row is None:
        cid = str(uuid.uuid4())
        con.execute("INSERT INTO companies(id, vat, legal_name, created_at) VALUES (?,?,?,?)", (cid, vat, name, t))
        con.execute("INSERT INTO memberships(company_id, user_sub, role, created_at) VALUES (?,?,?,?)",
                    (cid, who["user"], "owner", t))
        con.execute("UPDATE cases SET company_id=? WHERE id=?", (cid, case_id))
        con.execute("UPDATE documents SET company_id=? WHERE owner_sub=? AND company_id IS NULL", (cid, who["user"]))
        db.log_event(con, case_id, "system", "company_created", {"vat": vat})
        return {"status": "created", "vat": vat}
    cid = row["id"]
    if is_member(con, cid, who["user"], active_only=False):
        status = "joined" if is_member(con, cid, who["user"]) else "access_requested"
        if status == "joined":
            con.execute("UPDATE cases SET company_id=? WHERE id=?", (cid, case_id))
            con.execute("UPDATE documents SET company_id=? WHERE owner_sub=? AND company_id IS NULL", (cid, who["user"]))
            con.commit()
        return {"status": status, "vat": vat}
    con.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                (cid, who["user"], "member", "pending", t))
    db.log_event(con, case_id, "system", "access_requested", {"vat": vat, "user": who["user"]})
    return {"status": "access_requested", "vat": vat}


def has_consent(con, user_sub, terms_version):
    return con.execute("SELECT 1 FROM consents WHERE user_sub=? AND terms_version=?",
                       (user_sub, terms_version)).fetchone() is not None


def record_consent(con, user_sub, terms_version, lang, onerous):
    con.execute("INSERT INTO consents(user_sub, terms_version, lang, onerous_clauses, at) VALUES (?,?,?,?,?)",
                (user_sub, terms_version, lang, 1 if onerous else 0, db.now()))
    con.commit()


def get_profile(con, user_sub):
    row = con.execute("SELECT persona_id, style FROM profiles WHERE user_sub=?", (user_sub,)).fetchone()
    return {"persona_id": row["persona_id"], "style": row["style"]} if row else {"persona_id": None, "style": None}


def save_profile(con, user_sub, persona_id=None, style=None):
    cur = get_profile(con, user_sub)
    persona_id = persona_id or cur["persona_id"]
    style = style or cur["style"]
    con.execute("INSERT INTO profiles(user_sub, persona_id, style, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT (user_sub) DO UPDATE SET persona_id=excluded.persona_id, style=excluded.style, "
                "updated_at=excluded.updated_at", (user_sub, persona_id, style, db.now()))
    con.commit()
