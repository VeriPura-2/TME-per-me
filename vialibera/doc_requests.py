"""Document requests from a TEM to a client (C1, 22 Nov 2026).

The TEM picks documents from the client's checklist and asks for them. The client uploads into each request.
Status: requested -> uploaded -> accepted, or needs_change (with a note the client sees) -> uploaded again.
Reminders: an email to the client company's owners after `remind_days` without an upload (0 = off), at most one
per project per reminder period, sent by the daily job. The TEM firm name signs the email.
"""
import uuid
from datetime import datetime

from . import db, notify, requirements_source, verticals

OPEN = ("requested", "needs_change")
STATUSES = ("requested", "uploaded", "accepted", "needs_change")
DEFAULT_DAYS = 3
NOTE_MAX = 500


def _firm_of_case(con, who, case_id):
    """(case row, firm row) when this TEM user works on the case, else (None, None)."""
    from . import tems
    row = tems._case_tem(con, who, case_id)
    if row is None:
        return None, None
    f = tems.firm_of(con, who["user"])
    return row, f


def _checklist(con, case_row):
    case = db.case_read(con, case_row["id"])
    req = requirements_source.get().required(case["product"].get("category"), case["market"].get("country"), set(),
                                             verticals.vertical_of(case))
    return {i["id"]: i for i in (req["data"]["items"] if req else []) if not i["importer_side"]}


def create(con, who, case_id, items, remind_days=DEFAULT_DAYS):
    row, f = _firm_of_case(con, who, case_id)
    if row is None or not f:
        return 404, {"error": "no such project"}
    try:
        days = max(0, min(int(remind_days), 30))
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    checklist = _checklist(con, row)
    items = [str(i) for i in (items or [])][:40]
    bad = [i for i in items if i not in checklist]
    if not items or bad:
        return 400, {"error": "unknown document", "items": bad}
    made = []
    for i in items:
        if con.execute("SELECT 1 FROM doc_requests WHERE case_id=? AND item_id=? AND status IN ('requested','uploaded','needs_change')",
                       (case_id, i)).fetchone():
            continue  # already asked for and not accepted yet
        rid = uuid.uuid4().hex
        it = checklist[i]
        con.execute("INSERT INTO doc_requests(id, case_id, company_id, firm_id, item_id, label_en, label_it, status, remind_days, "
                    "requested_by, requested_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, case_id, row["company_id"], f["firm_id"], i, it["en"], it["it"], "requested", days, who["user"], db.now(), db.now()))
        made.append(rid)
    con.commit()
    db.log_event(con, case_id, who["user"], "doc_requested", {"items": items, "remind_days": days})
    return 200, {"ok": True, "created": len(made)}


def set_status(con, who, request_id, status, note=None):
    r = con.execute("SELECT * FROM doc_requests WHERE id=?", (str(request_id),)).fetchone()
    if r is None:
        return 404, {"error": "no such request"}
    row, f = _firm_of_case(con, who, r["case_id"])
    if row is None or not f or f["firm_id"] != r["firm_id"]:
        return 404, {"error": "no such request"}
    if status not in ("accepted", "needs_change"):
        return 400, {"error": "bad status"}
    note = str(note or "").strip()[:NOTE_MAX] or None
    if status == "needs_change" and not note:
        return 400, {"error": "say what needs changing"}
    con.execute("UPDATE doc_requests SET status=?, change_note=?, updated_at=?, last_reminded_at=NULL WHERE id=?",
                (status, note if status == "needs_change" else None, db.now(), r["id"]))
    con.commit()
    db.log_event(con, r["case_id"], who["user"], "doc_request_" + status, {"item": r["item_id"]})
    return 200, {"ok": True}


def set_reminders(con, who, case_id, days):
    row, f = _firm_of_case(con, who, case_id)
    if row is None or not f:
        return 404, {"error": "no such project"}
    try:
        days = max(0, min(int(days), 30))
    except (TypeError, ValueError):
        return 400, {"error": "bad days"}
    con.execute("UPDATE doc_requests SET remind_days=? WHERE case_id=? AND firm_id=?", (days, case_id, f["firm_id"]))
    con.commit()
    return 200, {"ok": True, "remind_days": days}


def attach(con, who, case_id, request_id, document_id):
    """The client uploaded a file into a request. Called by the upload handler after the file is stored."""
    r = con.execute("SELECT * FROM doc_requests WHERE id=? AND case_id=?", (str(request_id), case_id)).fetchone()
    if r is None or r["status"] not in OPEN:
        return False
    con.execute("UPDATE doc_requests SET status='uploaded', document_id=?, updated_at=? WHERE id=?", (document_id, db.now(), r["id"]))
    con.commit()
    db.log_event(con, case_id, who["user"], "doc_request_uploaded", {"item": r["item_id"]})
    return True


def for_case(con, case_id):
    out = []
    for r in con.execute("SELECT q.*, f.name AS firm FROM doc_requests q JOIN tem_firms f ON f.id=q.firm_id WHERE q.case_id=? "
                         "ORDER BY q.requested_at", (case_id,)).fetchall():
        out.append({"id": r["id"], "item": r["item_id"], "label": {"en": r["label_en"], "it": r["label_it"]}, "status": r["status"],
                    "note": r["change_note"], "document_id": r["document_id"], "firm": r["firm"], "remind_days": r["remind_days"],
                    "requested_at": r["requested_at"]})
    return out


def waiting(con, firm_id, company_id):
    return con.execute("SELECT COUNT(*) AS n FROM doc_requests WHERE firm_id=? AND company_id=? AND status IN ('requested','needs_change')",
                       (firm_id, company_id)).fetchone()["n"]


# reminders ----------------------------------------------------------------------------

def _days_since(at):
    try:
        return (datetime.fromisoformat(db.now()) - datetime.fromisoformat(at)).total_seconds() / 86400
    except (TypeError, ValueError):
        return 0


def _owner_emails(con, company_id):
    return [r["label"] for r in con.execute("SELECT label FROM memberships WHERE company_id=? AND role='owner' AND status='active'",
                                             (company_id,)).fetchall() if r["label"] and "@" in r["label"]]


SUBJECT = {"en": "{firm} is waiting for {n} documents", "it": "{firm} attende {n} documenti"}
BODY = {"en": "Hello, {firm} asked for these documents for your project {project}:\n{list}\n\nYou can upload them in MioTEM: {link}\n"
              "You can reply to {firm} directly if something is unclear.",
        "it": "Buongiorno, {firm} ha chiesto questi documenti per il suo progetto {project}:\n{list}\n\nPuò caricarli in MioTEM: {link}\n"
              "Se qualcosa non è chiaro, può rispondere direttamente a {firm}."}


def send_reminders(con, base_url, send=None, lang="it"):
    """Daily job: one email per project whose open requests have waited `remind_days` since the request or the last reminder."""
    send = send or notify.send_to
    sent = 0
    cases = {}
    for r in con.execute("SELECT q.*, f.name AS firm FROM doc_requests q JOIN tem_firms f ON f.id=q.firm_id "
                         "WHERE q.status IN ('requested','needs_change') AND q.remind_days > 0").fetchall():
        since = r["last_reminded_at"] or r["updated_at"] or r["requested_at"]
        if _days_since(since) >= r["remind_days"]:
            cases.setdefault(r["case_id"], []).append(r)
    for case_id, rows in cases.items():
        to = _owner_emails(con, rows[0]["company_id"])
        if not to:
            continue
        case = db.case_read(con, case_id)
        project = " → ".join(x for x in [case["product"].get("name_brand") or case["product"].get("category"), case["market"].get("country")] if x)
        lab = "label_it" if lang == "it" else "label_en"
        lines = "\n".join("- " + r[lab] for r in rows)
        firm = rows[0]["firm"]
        ok = False
        for addr in to:
            ok = send(addr, SUBJECT[lang].format(firm=firm, n=len(rows)),
                      BODY[lang].format(firm=firm, project=project or "-", list=lines, link=base_url.rstrip("/") + "/")) or ok
        if ok:
            sent += 1
            con.executemany("UPDATE doc_requests SET last_reminded_at=? WHERE id=?", [(db.now(), r["id"]) for r in rows])
            db.log_event(con, case_id, "job", "doc_request_reminder", {"documents": len(rows)})
    con.commit()
    return {"projects_reminded": sent}
