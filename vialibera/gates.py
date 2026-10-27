"""Hard gates enforced in code. The agent cannot bypass these.

1. No work starts before payment.
2. No item counts as delivered or used before client confirmation.
3. Prices come only from the VeriPura menu.
4. Compliance items need a VeriPura review before delivery.
"""
import uuid

from .db import log_event, now


class GateError(Exception):
    pass


ITEM_ORDER = ["proposed", "selected", "quoted", "approved", "paid", "in progress",
              "review", "delivered", "client confirmed"]


def _item(con, item_id, lock=False):
    suffix = " FOR UPDATE" if lock and getattr(con, "postgres", False) else ""
    row = con.execute("SELECT * FROM items WHERE id=?" + suffix, (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    return row


def add_item(con, case_id, code, menu, actor="agent"):
    """Create an item. The price is read from the menu, never supplied by the caller."""
    if code not in menu:
        raise GateError(f"item code {code!r} is not in the price menu")
    entry = menu[code]
    iid = str(uuid.uuid4())
    con.execute(
        "INSERT INTO items(id, case_id, code, price_cents, is_compliance, updated_at) VALUES (?,?,?,?,?,?)",
        (iid, case_id, code, entry.get("price_cents"), int(entry.get("compliance", False)), now()))
    log_event(con, case_id, actor, "item_added", {"item_id": iid, "code": code,
                                                  "price_cents": entry.get("price_cents")})
    return iid


def set_state(con, item_id, new_state, actor):
    try:
        return _set_state(con, item_id, new_state, actor)
    except Exception:
        if hasattr(con, "rollback"):
            con.rollback()
        raise


def _set_state(con, item_id, new_state, actor):
    row = _item(con, item_id, lock=True)
    old = row["state"]
    if new_state not in ITEM_ORDER and new_state not in ("rejected", "refunded"):
        raise GateError(f"unknown state {new_state!r}")
    if new_state in ("in progress",) and old != "paid":
        raise GateError("work cannot start before payment")
    if new_state == "paid" and row["price_cents"] is None:
        raise GateError("price to be set by VeriPura before this item can be paid")
    if new_state == "delivered":
        if row["is_compliance"] and old != "review":
            raise GateError("compliance items need VeriPura review before delivery")
        if not row["is_compliance"] and old != "in progress":
            raise GateError("only items in progress can be delivered")
    if new_state == "client confirmed":
        raise GateError("use confirm_item, the client confirms with who, when and version")
    con.execute("UPDATE items SET state=?, updated_at=? WHERE id=?", (new_state, now(), item_id))
    log_event(con, row["case_id"], actor, "item_state", {"item_id": item_id, "from": old, "to": new_state})


def confirm_item(con, item_id, client_actor, item_version):
    try:
        return _confirm_item(con, item_id, client_actor, item_version)
    except Exception:
        if hasattr(con, "rollback"):
            con.rollback()
        raise


def _confirm_item(con, item_id, client_actor, item_version):
    """Only a client actor can confirm. Agent and staff are rejected."""
    if not client_actor.startswith("client:"):
        raise GateError("only the client can confirm an item")
    row = _item(con, item_id, lock=True)
    if row["state"] != "delivered":
        raise GateError("only delivered items can be confirmed")
    con.execute("INSERT INTO confirmations(id, case_id, item_id, actor, item_version, at) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), row["case_id"], item_id, client_actor, item_version, now()))
    con.execute("UPDATE items SET state='client confirmed', updated_at=? WHERE id=?", (now(), item_id))
    log_event(con, row["case_id"], client_actor, "client_confirmed",
              {"item_id": item_id, "version": item_version})
