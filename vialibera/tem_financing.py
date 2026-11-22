"""A TEM's financing work per client project (F4, 22 Nov 2026).

Per line: the scheme (from data/funding.json), the client's application status, the deadline and the documents still
missing. The deadline comes from the scheme data when it has a sourced one; otherwise the TEM types it and the page
labels it as entered by the firm. MioTEM never writes the list of missing documents: the TEM writes it from the funder's
form. The client sees a line only when the TEM switches it on. Hours on financing go in the time log (category financing).
"""
import uuid
from datetime import date

from . import db, funding

STATUSES = ("not_started", "preparing", "submitted", "approved", "refused", "client_stopped")
DONE = ("approved", "refused", "client_stopped")


def _ctx(con, who, case_id):
    from . import tems
    row = tems._case_tem(con, who, case_id)
    f = tems.firm_of(con, who["user"]) if row is not None else None
    return row, f


def _schemes():
    return {s["id"]: s for s in funding.schemes()}


def _sourced_deadline(s):
    return (s.get("facts", {}).get("deadline") or {}).get("value")


def save(con, who, case_id, body):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    sch = _schemes()
    sid, status = str(body.get("scheme_id") or ""), str(body.get("status") or "")
    if sid not in sch or status not in STATUSES:
        return 400, {"error": "bad entry"}
    dl = None
    if not _sourced_deadline(sch[sid]) and body.get("deadline"):
        try:
            dl = date.fromisoformat(str(body["deadline"])).isoformat()
        except ValueError:
            return 400, {"error": "bad date"}
    missing = str(body.get("missing") or "").strip()[:1000] or None
    vis = 1 if body.get("client_visible") else 0
    lid = str(body.get("id") or "")
    if lid:
        cur = con.execute("SELECT id FROM tem_financing WHERE id=? AND case_id=? AND firm_id=?", (lid, case_id, f["firm_id"])).fetchone()
        if cur is None:
            return 404, {"error": "no such line"}
        con.execute("UPDATE tem_financing SET scheme_id=?, status=?, deadline=?, missing=?, client_visible=?, updated_by=?, updated_at=? WHERE id=?",
                    (sid, status, dl, missing, vis, who["user"], db.now(), lid))
    else:
        lid = uuid.uuid4().hex
        con.execute("INSERT INTO tem_financing(id, case_id, firm_id, scheme_id, status, deadline, missing, client_visible, updated_by, updated_at, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (lid, case_id, f["firm_id"], sid, status, dl, missing, vis, who["user"], db.now(), db.now()))
    con.commit()
    db.log_event(con, case_id, who["user"], "tem_financing", {"scheme": sid, "status": status, "client_visible": bool(vis)})
    return 200, {"ok": True, "id": lid}


def delete(con, who, case_id, lid):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return 404, {"error": "no such line"}
    n = con.execute("DELETE FROM tem_financing WHERE id=? AND case_id=? AND firm_id=?", (str(lid), case_id, f["firm_id"])).rowcount
    con.commit()
    return (200, {"ok": True}) if n else (404, {"error": "no such line"})


def _line(r, sch, firm=None):
    s = sch.get(r["scheme_id"])
    sourced = _sourced_deadline(s) if s else None
    return {"id": r["id"], "scheme_id": r["scheme_id"], "label": s["label"] if s else {"en": r["scheme_id"], "it": r["scheme_id"]},
            "url": s["url"] if s else None, "scheme_status": s["status"]["value"] if s else None,
            "status": r["status"], "deadline": sourced or r["deadline"], "deadline_by_firm": bool(r["deadline"] and not sourced),
            "missing": r["missing"], "client_visible": bool(r["client_visible"]), "firm": firm}


def for_tem(con, who, case_id):
    row, f = _ctx(con, who, case_id)
    if row is None:
        return None
    sch = _schemes()
    lines = [_line(r, sch) for r in con.execute("SELECT * FROM tem_financing WHERE case_id=? AND firm_id=? ORDER BY created_at",
                                                 (case_id, f["firm_id"])).fetchall()]
    return {"lines": lines, "statuses": list(STATUSES),
            "schemes": [{"id": s["id"], "label": s["label"], "deadline": _sourced_deadline(s)} for s in sch.values()]}


def for_client(con, case_id):
    sch = _schemes()
    return [_line(r, sch, r["firm"]) for r in con.execute(
        "SELECT t.*, f.name AS firm FROM tem_financing t JOIN tem_firms f ON f.id=t.firm_id WHERE t.case_id=? AND t.client_visible=1 "
        "ORDER BY t.created_at", (case_id,)).fetchall()]


def next_deadline(con, firm_id, company_id, today=None):
    """For the TEM workspace: the nearest deadline of an unfinished financing line for this client, from today on."""
    today = (today or date.today()).isoformat()
    sch = _schemes()
    best = None
    for r in con.execute("SELECT t.* FROM tem_financing t JOIN cases c ON c.id=t.case_id WHERE t.firm_id=? AND c.company_id=?",
                         (firm_id, company_id)).fetchall():
        if r["status"] in DONE:
            continue
        ln = _line(r, sch)
        if ln["deadline"] and ln["deadline"] >= today and (best is None or ln["deadline"] < best["date"]):
            best = {"label": ln["label"], "date": ln["deadline"]}
    return best
