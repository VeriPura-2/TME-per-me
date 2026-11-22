"""Certificates and approvals tracker (B2, 22 Nov 2026).

A company keeps each certificate or approval in one list: type, product, who issued it, valid until, the document.
The type list holds only types the checklist data (requirements) or the MASAF control body lists name, each with its
source, plus "other". Listing a type here never says it is required: the checklist does that.
Status: claimed until staff have seen the document (seen_staff). checked_core is set only by a real VeriPura Core check,
which is not connected yet, so nothing sets it today. Expired is worked out from the date.
Reminder: one email to the company owners 30 days before the expiry date, from the daily job.
"""
import uuid
from datetime import date, timedelta

from . import db, docs, permissions, requirements_source

REMIND_DAYS = 30
STATUSES = ("claimed", "seen_staff", "checked_core")
MASAF = {"en": "MASAF control body lists", "it": "elenchi MASAF degli organismi di controllo"}


def _row_type(row_id):
    r = next((x for x in requirements_source.get().rows if x["id"] == row_id), None)
    return {"name": {"en": r["en"], "it": r["it"]}, "source": r.get("source"), "source_label": None} if r and r.get("source") else None


def types():
    out = {}
    for tid, rid in (("uk_ehc", "uk_ehc"), ("ttb_cert", "ttb_cert"), ("cola", "cola")):
        t = _row_type(rid)
        if t:
            out[tid] = t
    for tid, en, it in (("dop", "DOP certificate (protected designation of origin)", "Certificato DOP (denominazione di origine protetta)"),
                        ("igp", "IGP certificate (protected geographical indication)", "Certificato IGP (indicazione geografica protetta)"),
                        ("docg", "DOCG certificate (wine)", "Certificato DOCG (vino)")):
        out[tid] = {"name": {"en": en, "it": it}, "source": None, "source_label": MASAF}
    out["other"] = {"name": {"en": "Other certificate or approval", "it": "Altro certificato o approvazione"}, "source": None, "source_label": None}
    return out


def _clean(v, n=160):
    return str(v or "").strip()[:n] or None


def save(con, who, key, body):
    ts = types()
    t = str(body.get("type") or "")
    if t not in ts:
        return 400, {"error": "bad type"}
    name = _clean(body.get("name")) if t == "other" else None
    if t == "other" and not name:
        return 400, {"error": "name needed"}
    vu = None
    if body.get("valid_until"):
        try:
            vu = date.fromisoformat(str(body["valid_until"])).isoformat()
        except ValueError:
            return 400, {"error": "bad date"}
    did = _clean(body.get("document_id"), 64)
    if did and docs.get_doc(con, did, who) is None:
        return 400, {"error": "no such document"}
    cid = str(body.get("id") or "")
    vals = (t, name, _clean(body.get("product")), _clean(body.get("issued_by")), vu, did)
    if cid:
        cur = con.execute("SELECT valid_until, document_id FROM certificates WHERE id=? AND owner_key=?", (cid, key)).fetchone()
        if cur is None:
            return 404, {"error": "no such certificate"}
        # a new document or date goes back to claimed until someone has seen it
        back = cur["document_id"] != did or cur["valid_until"] != vu
        con.execute("UPDATE certificates SET type=?, name=?, product=?, issued_by=?, valid_until=?, document_id=?, updated_at=?"
                    + (", status='claimed'" if back else "") + " WHERE id=?", vals + (db.now(), cid))
    else:
        cid = uuid.uuid4().hex
        con.execute("INSERT INTO certificates(id, owner_key, type, name, product, issued_by, valid_until, document_id, status, created_by, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (cid, key) + vals + ("claimed", who["user"], db.now(), db.now()))
    con.commit()
    db.log_event(con, None, who["user"], "certificate_saved", {"type": t})
    return 200, {"ok": True, "id": cid}


def delete(con, who, key, cid):
    n = con.execute("DELETE FROM certificates WHERE id=? AND owner_key=?", (str(cid), key)).rowcount
    con.commit()
    return (200, {"ok": True}) if n else (404, {"error": "no such certificate"})


def mark_seen(con, who, cid):
    """Staff only: the document was seen."""
    if not permissions.is_staff(who):
        return 403, {"error": "staff only"}
    n = con.execute("UPDATE certificates SET status='seen_staff', updated_at=? WHERE id=? AND document_id IS NOT NULL", (db.now(), str(cid))).rowcount
    con.commit()
    if n:
        db.log_event(con, None, who["user"], "certificate_seen", {"id": str(cid)})
    return (200, {"ok": True}) if n else (404, {"error": "no such certificate with a document"})


def listing(con, key, today=None):
    today = (today or date.today()).isoformat()
    ts = types()
    out = []
    for r in con.execute("SELECT * FROM certificates WHERE owner_key=? ORDER BY COALESCE(valid_until, '9999'), created_at", (key,)).fetchall():
        t = ts.get(r["type"], ts["other"])
        out.append({"id": r["id"], "type": r["type"], "name": {"en": r["name"], "it": r["name"]} if r["name"] else t["name"],
                    "product": r["product"], "issued_by": r["issued_by"], "valid_until": r["valid_until"], "document_id": r["document_id"],
                    "status": "expired" if r["valid_until"] and r["valid_until"] < today else r["status"]})
    return out


SUBJECT = {"en": "{name} expires on {date}", "it": "{name} scade il {date}"}
BODY = {"en": "Hello, {name}{about} expires on {date}, according to the date entered in MioTEM.\n\nYou can update it in MioTEM: {app}",
        "it": "Buongiorno, {name}{about} scade il {date}, secondo la data inserita in MioTEM.\n\nPuò aggiornarlo in MioTEM: {app}"}


def send_reminders(con, base_url, send=None, today=None, lang="it"):
    """Daily job: one email per certificate, 30 days or less before its expiry date, to the company owners."""
    from . import doc_requests, funding_check, notify
    send = send or notify.send_to
    today = today or date.today()
    edge = (today + timedelta(days=REMIND_DAYS)).isoformat()
    ts = types()
    sent = 0
    for r in con.execute("SELECT * FROM certificates WHERE valid_until IS NOT NULL AND valid_until>=? AND valid_until<=? "
                         "AND (reminded_for IS NULL OR reminded_for<>valid_until)", (today.isoformat(), edge)).fetchall():
        if r["owner_key"].startswith("u:"):
            continue
        to = doc_requests._owner_emails(con, r["owner_key"])
        if not to:
            continue
        name = r["name"] or ts.get(r["type"], ts["other"])["name"][lang]
        bits = [x for x in (r["product"], r["issued_by"]) if x]
        about = " (" + ", ".join(bits) + ")" if bits else ""
        d = funding_check.fday(r["valid_until"], lang)
        ok = False
        for a in to:
            ok = send(a, SUBJECT[lang].format(name=name, date=d), BODY[lang].format(name=name, about=about, date=d, app=base_url.rstrip("/") + "/")) or ok
        if ok:
            con.execute("UPDATE certificates SET reminded_for=? WHERE id=?", (r["valid_until"], r["id"]))
            sent += 1
    con.commit()
    return {"certificate_reminders": sent}
