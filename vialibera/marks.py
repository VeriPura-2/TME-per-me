"""Checklist items ticked by hand by the exporter ("Marked by you"). Not a confirmation: nobody has checked them."""
from . import db


def apply(con, case_id, req):
    """Tag each ticked item with marked = {at}. Items already on file are left alone."""
    rows = {r["item_id"]: r for r in con.execute("SELECT * FROM checklist_marks WHERE case_id=?", (case_id,)).fetchall()}
    for i in req["data"]["items"]:
        m = rows.get(i["id"])
        if m and not i.get("on_file"):
            i["marked"] = {"at": m["at"]}
    return req


def mark(con, case_id, who, item_id, on, valid_ids):
    """Tick or untick one item. valid_ids: the item ids of the project's checklist."""
    item_id = str(item_id or "")[:60]
    if item_id not in valid_ids:
        return 400, {"error": "unknown_item"}
    con.execute("DELETE FROM checklist_marks WHERE case_id=? AND item_id=?", (case_id, item_id))
    if on:
        con.execute("INSERT INTO checklist_marks(case_id, item_id, marked_by, at) VALUES (?,?,?,?)", (case_id, item_id, who["user"], db.now()))
    con.commit()
    db.log_event(con, case_id, who["user"], "checklist_marked" if on else "checklist_unmarked", {"item": item_id})
    return 200, {"ok": True, "item": item_id, "marked": bool(on)}
