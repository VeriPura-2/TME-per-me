"""Sending project documents to VeriPura Core and showing the results.

Default: staff send each document ("Send to CORE"). A superadmin can switch on automatic sending,
which sends a document when it is uploaded to a paid project. Every send is one paid Core call, so
nothing is ever retried automatically: an unknown outcome is recorded as "unknown" and staff check
the status before sending again.

What the client sees: matched, flagged, flagged_critical or not_checked per document. Never
"approved" or "rejected": Core flags, people decide.
"""
import base64
import json
import uuid

from . import db, docs, permissions, requirements, storage, verticals
from .adapters.base import AdapterError
from .adapters.core import COUNTRY, DOC_TYPE, HS, PRODUCT, VeriPuraCore, outcome

AUTO_KEY = "core_auto_send"
PAID_STATES = ("paid", "in progress", "delivered", "follow-up active")
LABELS = {
    "matched": {"it": "Corrisponde", "en": "Matched"},
    "flagged": {"it": "Segnalato per verifica", "en": "Flagged for review"},
    "flagged_critical": {"it": "Segnalato: critico", "en": "Flagged: critical"},
    "not_checked": {"it": "Non verificato", "en": "Not checked"},
    "unknown": {"it": "Esito non noto, verificare lo stato", "en": "Outcome unknown, check status"},
    "error": {"it": "Errore di invio", "en": "Send error"},
}


def adapter():
    return VeriPuraCore()


# switch -------------------------------------------------------------------

def auto_enabled(con):
    r = con.execute("SELECT value FROM settings WHERE key=?", (AUTO_KEY,)).fetchone()
    return bool(r and r["value"] == "on")


def set_auto(con, who, on):
    if not permissions.is_superadmin(who):
        return 403, {"error": "forbidden"}
    val = "on" if on else "off"
    if con.execute("SELECT 1 FROM settings WHERE key=?", (AUTO_KEY,)).fetchone():
        con.execute("UPDATE settings SET value=?, updated_by=?, updated_at=? WHERE key=?", (val, who["user"], db.now(), AUTO_KEY))
    else:
        con.execute("INSERT INTO settings(key, value, updated_by, updated_at) VALUES (?,?,?,?)", (AUTO_KEY, val, who["user"], db.now()))
    con.commit()
    db.log_event(con, None, who["user"], "staff_change", {"action": "core_auto_send", "value": val})
    return 200, {"auto": on}


# helpers ------------------------------------------------------------------

def _case(con, case_id):
    return con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()


def shipment_for(case_row):
    """Core shipment fields from the case file. None when the lane is not known yet."""
    prod, mkt, comp = (json.loads(case_row[k] or "{}") for k in ("product", "market", "company"))
    ln = requirements.lane(prod.get("category"), mkt.get("country"), verticals.vertical_of(case_row))
    if not ln:
        return None
    p, d = ln
    out = {"exportFrom": "Italy", "importTo": COUNTRY[d], "product": prod.get("name_brand") or PRODUCT[p], "hsCode": HS[p]}
    if comp.get("legal_name"):
        out["sellerName"] = comp["legal_name"]
    if mkt.get("importer_name"):
        out["buyerName"] = mkt["importer_name"]
    return out


def _consignment(con, case_id):
    return con.execute("SELECT * FROM core_consignments WHERE case_id=?", (case_id,)).fetchone()


def _linked(con, case_id, doc_id):
    return con.execute("SELECT 1 FROM project_docs WHERE case_id=? AND document_id=?", (case_id, doc_id)).fetchone() is not None


# send -----------------------------------------------------------------------

def send(con, who, case_id, doc_id, via="staff", core=None):
    """Send one project document to Core. Staff (superadmin) or the automatic switch only."""
    if via == "staff" and not permissions.is_superadmin(who):
        return 403, {"error": "forbidden"}
    case = _case(con, case_id)
    if case is None:
        return 404, {"error": "no such case"}
    if not _linked(con, case_id, doc_id):
        return 404, {"error": "document is not in this project"}
    doc = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if case["company_id"] and doc["company_id"] != case["company_id"]:
        return 403, {"error": "document belongs to another company"}
    last = con.execute("SELECT state FROM core_checks WHERE case_id=? AND document_id=? ORDER BY at DESC LIMIT 1",
                       (case_id, doc_id)).fetchone()
    if last and last["state"] == "unknown":
        return 409, {"error": "last send outcome unknown: refresh status before sending again"}
    core = core or adapter()
    cons = _consignment(con, case_id)
    if cons and cons["simulated"] and core.mode == "live":
        # A test-mode consignment does not exist in Core: start a real one.
        con.execute("DELETE FROM core_consignments WHERE case_id=?", (case_id,))
        cons = None
    shipment = None if cons else shipment_for(case)
    if not cons and not shipment:
        return 400, {"error": "product and destination must be a Wave 1 lane before sending to Core"}
    simulated = core.mode != "live"
    actor = who["user"] if who else "auto"
    cid = str(uuid.uuid4())
    payload = base64.b64encode(storage.store().get(doc["store_key"])).decode()
    try:
        res = core.call(con, "submit", case_id=case_id, file_name=doc["filename"], content_type=doc["mime"],
                        file_b64=payload, consignment_id=cons["consignment_id"] if cons else None,
                        shipment=shipment, doc_type=DOC_TYPE.get(doc["doc_type"]))
    except AdapterError as e:
        # A send that may have reached Core is "unknown", never retried automatically.
        state = "unknown" if e.kind == "unavailable" and "HTTP" not in str(e) else "error"
        con.execute("INSERT INTO core_checks(id, case_id, document_id, via, actor, simulated, state, error, at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (cid, case_id, doc_id, via, actor, int(simulated), state, str(e)[:300], db.now()))
        con.commit()
        db.log_event(con, case_id, actor, "core_send_" + state, {"document": doc_id, "via": via})
        return 502, {"error": state, "detail": str(e)[:300]}
    r = res["data"]
    if not cons:
        con.execute("INSERT INTO core_consignments(case_id, consignment_id, simulated, created_at) VALUES (?,?,?,?)",
                    (case_id, r["consignmentId"], int(simulated), db.now()))
    out = outcome(r.get("status"), r.get("validationLevel"), r.get("requiresHumanReview"))
    con.execute("INSERT INTO core_checks(id, case_id, document_id, via, actor, simulated, state, core_status, validation_level, "
                "requires_review, outcome, alerts, raw_ref, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, case_id, doc_id, via, actor, int(simulated), "done", r.get("status"), r.get("validationLevel"),
                 int(bool(r.get("requiresHumanReview"))), out, json.dumps(r.get("alerts") or []), res["raw_ref"], db.now()))
    con.commit()
    db.log_event(con, case_id, actor, "core_sent", {"document": doc_id, "via": via, "outcome": out, "simulated": simulated})
    return 200, {"outcome": out, "simulated": simulated, "consignment": r["consignmentId"]}


def on_upload(con, case_id, doc_id):
    """Automatic sending, only when switched on and the project is paid. Never raises."""
    try:
        if not case_id or not auto_enabled(con):
            return None
        case = _case(con, case_id)
        if case is None or case["status"] not in PAID_STATES:
            return None
        if not permissions.owner_confirmed(con, case["company_id"]):  # provisional owner: nothing goes for validation yet
            db.log_event(con, case_id, "auto", "core_auto_held", {"document": doc_id, "reason": "owner_not_confirmed"})
            return None
        return send(con, None, case_id, doc_id, via="auto")
    except Exception as e:  # an upload must never fail because Core did
        db.log_event(con, case_id, "auto", "core_auto_error", {"document": doc_id, "error": type(e).__name__})
        return None


# status -----------------------------------------------------------------------

def refresh(con, who, case_id, core=None):
    """Ask Core for the consignment status. Staff only. Clears an "unknown" send once Core has answered."""
    if not permissions.is_staff(who):
        return 403, {"error": "forbidden"}
    cons = _consignment(con, case_id)
    if cons is None:
        return 404, {"error": "nothing sent to Core for this project yet"}
    core = core or adapter()
    try:
        res = core.call(con, "status", case_id=case_id, consignment_id=cons["consignment_id"])
    except AdapterError as e:
        return 502, {"error": "core_unavailable", "detail": str(e)[:300]}
    con.execute("UPDATE core_consignments SET last_status=?, checked_at=? WHERE case_id=?",
                (json.dumps(res["data"]), db.now(), case_id))
    con.execute("UPDATE core_checks SET state='error', error='superseded by status check' WHERE case_id=? AND state='unknown'",
                (case_id,))
    con.commit()
    db.log_event(con, case_id, who["user"], "core_status", {"status": res["data"].get("status")})
    return 200, {"status": res["data"]}


# view -------------------------------------------------------------------------

def summary(con, case_id, staff=False):
    """Latest result per project document, plus Core's own roadmap for staff."""
    cons = _consignment(con, case_id)
    rows = con.execute(
        "SELECT d.id, d.filename, d.doc_type FROM project_docs p JOIN documents d ON d.id=p.document_id WHERE p.case_id=? "
        "ORDER BY d.created_at", (case_id,)).fetchall()
    docs_out = []
    for d in rows:
        last = con.execute("SELECT * FROM core_checks WHERE case_id=? AND document_id=? ORDER BY at DESC LIMIT 1",
                           (case_id, d["id"])).fetchone()
        res = None
        if last:
            key = last["outcome"] if last["state"] == "done" else last["state"]
            res = {"result": key, "label": LABELS.get(key, LABELS["not_checked"]), "simulated": bool(last["simulated"]),
                   "alerts": json.loads(last["alerts"] or "[]"), "at": last["at"]}
            if staff:
                res.update({"core_status": last["core_status"], "level": last["validation_level"], "via": last["via"],
                            "error": last["error"]})
        docs_out.append({"id": d["id"], "filename": d["filename"], "doc_type": d["doc_type"], "check": res})
    out = {"mode": adapter().mode, "consignment": bool(cons), "documents": docs_out,
           "simulated": bool(cons and cons["simulated"])}
    if staff:
        out["auto"] = auto_enabled(con)
        out["consignment_id"] = cons["consignment_id"] if cons else None
        out["core_status"] = json.loads(cons["last_status"]) if cons and cons["last_status"] else None
        out["checked_at"] = cons["checked_at"] if cons else None
    return out


def view(con, who, case_id):
    case = _case(con, case_id)
    if case is None:
        return 404, {"error": "no such case"}
    role = permissions.case_role(con, case, who)
    if role is None:
        return 404, {"error": "no such case"}
    staff = permissions.is_staff(who)
    if staff and role in ("staff", "support"):
        permissions.audit_staff(con, who, case, "core_view")
    return 200, summary(con, case_id, staff=staff)
