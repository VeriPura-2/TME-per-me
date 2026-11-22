"""Work record: every importer a TEM contacts for a client project (R2b, 22 Nov 2026).

The TEM adds and updates the lines; the client always sees them, read-only, so the work done is visible.
Importers are not exclusive: the same importer may appear in several exporters' records.
"""
import re
import uuid
from datetime import date

from . import db

CHANNELS = ("email", "call", "fair", "visit", "other")
OUTCOMES = ("contacted", "replied", "samples", "meeting", "not_interested", "order")
URL = re.compile(r"^https?://[^\s]{3,300}$")


def _ctx(con, who, case_id):
    from . import tems
    row = tems._case_tem(con, who, case_id)
    f = tems.firm_of(con, who["user"]) if row is not None else None
    return row, f


def save(con, who, case_id, body):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    name = str(body.get("importer") or "").strip()[:160]
    ch, oc = str(body.get("channel") or ""), str(body.get("outcome") or "")
    web = str(body.get("website") or "").strip() or None
    if not name or ch not in CHANNELS or oc not in OUTCOMES or (web and not URL.match(web)):
        return 400, {"error": "bad entry"}
    try:
        day = date.fromisoformat(str(body.get("day") or date.today().isoformat())).isoformat()
    except ValueError:
        return 400, {"error": "bad date"}
    note = str(body.get("note") or "").strip()[:500] or None
    lid = str(body.get("id") or "")
    if lid:
        n = con.execute("UPDATE importer_contacts SET importer=?, website=?, day=?, channel=?, outcome=?, note=?, updated_at=? "
                        "WHERE id=? AND case_id=? AND firm_id=?", (name, web, day, ch, oc, note, db.now(), lid, case_id, f["firm_id"])).rowcount
        if not n:
            return 404, {"error": "no such line"}
    else:
        lid = uuid.uuid4().hex
        con.execute("INSERT INTO importer_contacts(id, case_id, firm_id, importer, website, day, channel, outcome, note, created_by, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (lid, case_id, f["firm_id"], name, web, day, ch, oc, note, who["user"], db.now(), db.now()))
    con.commit()
    db.log_event(con, case_id, who["user"], "importer_contact", {"outcome": oc})
    return 200, {"ok": True, "id": lid}


def delete(con, who, case_id, lid):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such line"}
    n = con.execute("DELETE FROM importer_contacts WHERE id=? AND case_id=? AND firm_id=?", (str(lid), case_id, f["firm_id"])).rowcount
    con.commit()
    if n:
        db.log_event(con, case_id, who["user"], "importer_contact_deleted", {})
    return (200, {"ok": True}) if n else (404, {"error": "no such line"})


def for_case(con, case_id):
    return [{"id": r["id"], "importer": r["importer"], "website": r["website"], "day": r["day"], "channel": r["channel"],
             "outcome": r["outcome"], "note": r["note"], "firm": r["firm"]}
            for r in con.execute("SELECT i.*, f.name AS firm FROM importer_contacts i JOIN tem_firms f ON f.id=i.firm_id "
                                 "WHERE i.case_id=? ORDER BY i.day DESC, i.created_at DESC", (case_id,)).fetchall()]
