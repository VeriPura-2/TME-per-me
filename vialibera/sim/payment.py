"""SIMULATED approval and payment. Nothing is charged. Delete when Stripe is live."""
from . import tag
from .. import db


def pay(con, case_id, who, packet):
    ref = "SIM-" + db.now().replace(":", "").replace("-", "")[:14]
    db.log_event(con, case_id, who["user"], "sim_payment", {"ref": ref, "total_cents": packet["total_cents"],
                                                              "items": [i["id"] for i in packet["items"]]})
    return tag("payment", {"ref": ref, "charged": False, "total_cents": packet["total_cents"],
                           "message": {"it": "Nessun addebito. Questa è una simulazione del pagamento.",
                                       "en": "No charge was made. This is a simulation of the payment."}})
