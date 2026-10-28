"""SIMULATED trigger for invite credits. In the real product the credit is granted after the invitee's
first real paid month, from the payment system. Here, choosing a paid plan counts as that month.
Delete this file when payments are live, call invites.on_first_paid_month from the payment webhook,
and set "invite_trigger" to live."""
from . import prices
from .. import invites, plans


def on_plan_chosen(con, user, plan_id):
    if not plans.get(plan_id)["monthly"]:
        return None
    return invites.on_first_paid_month(con, user, prices.INVITE_EXAMPLE["credit_cents"],
                                       prices.INVITE_EXAMPLE["expiry_days"], simulated=True)
