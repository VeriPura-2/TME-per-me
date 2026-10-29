"""Stripe payments. TEST MODE ONLY unless STRIPE_ALLOW_LIVE=1 is set.

Switches on by itself when STRIPE_SECRET_KEY exists (env or Secret Manager). A test key (sk_test_ or
rk_test_) runs in test mode; a live key is refused unless STRIPE_ALLOW_LIVE=1. Without a key everything
falls back to the simulated payment, so nothing breaks before the keys arrive.

What it does:
  - items: one Checkout Session (mode payment) per approved packet, invite credit applied as a coupon
  - plans: Checkout Session (mode subscription) for monthly plans, prices from the price menu
  - portal: Stripe Customer Portal so the company changes plan, card or cancels itself
  - webhook: signed events confirm payments and keep the company's plan in step with Stripe
Prices come from sim/prices.py until VeriPura sets the real menu, and are still marked as simulated.
No card data ever touches our server: Stripe hosts the payment page.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import accounts, db, invites, menu, plans
from .secrets import get_secret

API = "https://api.stripe.com/v1"
MIN_CENTS = 50  # Stripe's minimum charge in euro

_cache = {"key": None, "at": 0.0}


class StripeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _key():
    """The secret key, or None. Looked up at most once a minute, so adding the key needs no redeploy."""
    if time.time() - _cache["at"] < 60:
        return _cache["key"]
    key = None
    try:
        key = (get_secret("STRIPE_SECRET_KEY") or "").strip() or None
    except Exception:
        key = None
    _cache.update(key=key, at=time.time())
    return key


def reset_cache():
    _cache.update(key=None, at=0.0)


def mode():
    """'test', 'live' (only if explicitly allowed), or None."""
    key = _key()
    if not key:
        return None
    if key.startswith(("sk_test_", "rk_test_")):
        return "test"
    if key.startswith(("sk_live_", "rk_live_")) and os.environ.get("STRIPE_ALLOW_LIVE") == "1":
        return "live"
    return None


def enabled():
    return mode() is not None


def status():
    """What the browser may know."""
    return {"enabled": enabled(), "mode": mode()}


def _flat(d, prefix=""):
    out = []
    for k, v in d.items():
        name = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out += _flat(v, name)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                out += _flat(x, f"{name}[{i}]") if isinstance(x, dict) else [(f"{name}[{i}]", x)]
        elif v is not None:
            out.append((name, str(v).lower() if isinstance(v, bool) else str(v)))
    return out


def _call(method, path, data=None, idem=None):
    key = _key()
    if not key:
        raise StripeError(503, "stripe not configured")
    url = API + path
    body = None
    if method == "GET" and data:
        url += "?" + urllib.parse.urlencode(_flat(data))
    elif data:
        body = urllib.parse.urlencode(_flat(data)).encode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Stripe-Version", "2024-06-20")
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if idem:
        req.add_header("Idempotency-Key", idem)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise StripeError(e.code, msg or "stripe error")
    except urllib.error.URLError:
        raise StripeError(502, "stripe unreachable")


# ---- customers and subscriptions (one Stripe customer per paying holder: the company, else the person)

def customer_for(con, user, email=None):
    holder = invites.holder(con, user)
    row = con.execute("SELECT customer_id FROM stripe_customers WHERE holder=?", (holder,)).fetchone()
    if row:
        return holder, row["customer_id"]
    name = None
    if holder.startswith("co:"):
        r = con.execute("SELECT legal_name FROM companies WHERE id=?", (holder[3:],)).fetchone()
        name = r["legal_name"] if r else None
    cust = _call("POST", "/customers", {"name": name or email or user, "email": email,
                                         "metadata": {"holder": holder, "user": user}},
                 idem="cust-" + hashlib.sha1(holder.encode()).hexdigest())
    con.execute("INSERT INTO stripe_customers(holder, customer_id, created_at) VALUES (?,?,?)", (holder, cust["id"], db.now()))
    con.commit()
    return holder, cust["id"]


def subscription_of(con, user):
    return con.execute("SELECT * FROM stripe_subs WHERE holder=?", (invites.holder(con, user),)).fetchone()


def has_active_subscription(con, user):
    s = subscription_of(con, user)
    return bool(s and s["status"] in ("active", "trialing", "past_due"))


def _idem(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


# ---- checkout for approved items

def checkout_items(con, who, case_id, items, total_cents, credit_cents, base_url, lang="it", email=None):
    """items: [{id, name, price_cents}]. Returns {url, id}. The credit is spent only once the payment is confirmed."""
    payable = total_cents - credit_cents
    if payable < MIN_CENTS:
        raise StripeError(400, "amount below the minimum")
    holder, cust = customer_for(con, who["user"], email)
    ids = ",".join(sorted(i["id"] for i in items))
    meta = {"kind": "items", "case_id": case_id, "user": who["user"], "holder": holder, "items": ids,
            "total_cents": total_cents, "credit_cents": credit_cents}
    data = {
        "mode": "payment", "customer": cust, "client_reference_id": str(case_id), "locale": "en" if lang == "en" else "it",
        "line_items": [{"quantity": 1, "price_data": {"currency": "eur", "unit_amount": int(i["price_cents"]),
                                                      "product_data": {"name": i["name"]}}}
                       for i in items if int(i["price_cents"]) > 0],
        "metadata": meta, "payment_intent_data": {"metadata": meta},
        "success_url": f"{base_url}/?paid={{CHECKOUT_SESSION_ID}}", "cancel_url": f"{base_url}/?paycancel=1",
    }
    if credit_cents:
        coupon = _call("POST", "/coupons", {"amount_off": credit_cents, "currency": "eur", "duration": "once",
                                             "max_redemptions": 1, "name": "MioExport credit"},
                       idem="cp-" + _idem(case_id, who["user"], ids, credit_cents, int(time.time() // 60)))
        data["discounts"] = [{"coupon": coupon["id"]}]
    s = _call("POST", "/checkout/sessions", data, idem="co-" + _idem(case_id, who["user"], ids, credit_cents, int(time.time() // 60)))
    return {"url": s["url"], "id": s["id"]}


# ---- checkout for a monthly plan

def plan_price_cents(plan_id):
    from .sim import prices  # example prices until VeriPura sets the menu
    return prices.EXAMPLE[plan_id]["monthly"]


def checkout_plan(con, who, plan_id, base_url, lang="it", email=None):
    p = plans.get(plan_id)
    cents = plan_price_cents(plan_id)
    if not p["monthly"] or cents < MIN_CENTS:
        raise StripeError(400, "not a paid plan")
    holder, cust = customer_for(con, who["user"], email)
    meta = {"kind": "plan", "plan": plan_id, "user": who["user"], "holder": holder}
    s = _call("POST", "/checkout/sessions", {
        "mode": "subscription", "customer": cust, "locale": "en" if lang == "en" else "it", "metadata": meta,
        "line_items": [{"quantity": 1, "price_data": {"currency": "eur", "unit_amount": cents, "recurring": {"interval": "month"},
                                                      "product_data": {"name": "MioExport " + p["name"]["en"]}}}],
        "subscription_data": {"metadata": meta},
        "success_url": f"{base_url}/?paid={{CHECKOUT_SESSION_ID}}", "cancel_url": f"{base_url}/?paycancel=1",
    }, idem="sub-" + _idem(holder, plan_id, int(time.time() // 60)))
    return {"url": s["url"], "id": s["id"]}


def portal(con, who, base_url, email=None):
    holder, cust = customer_for(con, who["user"], email)
    s = _call("POST", "/billing_portal/sessions", {"customer": cust, "return_url": base_url + "/"})
    return {"url": s["url"]}


def retrieve_session(session_id):
    return _call("GET", "/checkout/sessions/" + urllib.parse.quote(session_id, safe=""))


# ---- confirming payments (called by the webhook AND by the return page, so either one is enough)

def record_payment(con, case_id, user, ref, item_ids, total_cents, credit_cents):
    """Record a paid packet once. Returns the stored data, or None if this reference was already recorded."""
    for ev in con.execute("SELECT data FROM events WHERE case_id=? AND kind='payment'", (case_id,)).fetchall():
        d = json.loads(ev["data"] if not isinstance(ev, tuple) else ev[0])
        if d.get("ref") == ref:
            return None
    used = invites.apply(con, user, credit_cents, case_ref=case_id) if credit_cents else 0
    data = {"ref": ref, "total_cents": total_cents, "credit_used_cents": used, "items": item_ids, "stripe": True, "mode": mode()}
    db.log_event(con, case_id, user, "payment", data)
    con.commit()
    return data


def session_paid(con, s):
    """Apply a completed Checkout Session. Safe to call any number of times."""
    meta = s.get("metadata") or {}
    if s.get("payment_status") not in ("paid", "no_payment_required"):
        return {"status": "unpaid"}
    if meta.get("kind") == "items":
        d = record_payment(con, meta["case_id"], meta["user"], s["id"], [x for x in meta.get("items", "").split(",") if x],
                           int(meta.get("total_cents", 0)), int(meta.get("credit_cents", 0)))
        return {"status": "paid", "kind": "items", "case_id": meta["case_id"], "payment": d, "already": d is None}
    if meta.get("kind") == "plan":
        _plan_active(con, meta["user"], meta["plan"], s.get("subscription"), "active", s.get("customer"))
        return {"status": "paid", "kind": "plan", "plan": meta["plan"]}
    return {"status": "ignored"}


def _plan_active(con, user, plan_id, subscription_id, status_, customer_id=None):
    holder = invites.holder(con, user)
    con.execute("DELETE FROM stripe_subs WHERE holder=?", (holder,))
    con.execute("INSERT INTO stripe_subs(holder, subscription_id, plan, status, updated_at) VALUES (?,?,?,?,?)",
                (holder, subscription_id, plan_id, status_, db.now()))
    first = status_ == "active"
    accounts.set_plan(con, user, plan_id)
    con.commit()
    if first:  # first paid month: the invite credit, once per invitee
        amount = menu.INVITE["credit_cents"]
        sim = False
        if not amount and mode() == "test":  # test mode only: use the example amount so the flow can be tried end to end
            from .sim import prices
            amount, sim = prices.INVITE_EXAMPLE["credit_cents"], True
        if amount:
            invites.on_first_paid_month(con, user, amount, menu.INVITE["expiry_days"], simulated=sim)
            con.commit()


# ---- webhook

def verify_webhook(raw, header, secret, tolerance=300, now=None):
    """Stripe-Signature: t=timestamp,v1=hmac. Returns the event dict or raises StripeError(400)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        t = int(parts["t"])
    except Exception:
        raise StripeError(400, "bad signature header")
    sigs = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
    want = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(want, s) for s in sigs):
        raise StripeError(400, "signature mismatch")
    if abs((now if now is not None else time.time()) - t) > tolerance:
        raise StripeError(400, "timestamp outside tolerance")
    return json.loads(raw)


def process_event(con, event):
    """Handle one verified event. Each event id is processed once."""
    try:
        con.execute("INSERT INTO stripe_events(id, type, at) VALUES (?,?,?)", (event["id"], event["type"], db.now()))
        con.commit()
    except Exception:
        con.rollback()
        return "duplicate"
    obj = (event.get("data") or {}).get("object") or {}
    typ = event["type"]
    if typ in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return session_paid(con, obj)["status"]
    if typ in ("customer.subscription.updated", "customer.subscription.deleted"):
        meta = obj.get("metadata") or {}
        if not meta.get("user") or meta.get("plan") not in plans.PLANS:
            return "ignored"
        st = "canceled" if typ.endswith("deleted") else obj.get("status", "")
        if st in ("active", "trialing", "past_due"):
            _plan_active(con, meta["user"], meta["plan"], obj.get("id"), st)
            return "plan_kept"
        if st in ("canceled", "unpaid", "incomplete_expired"):
            holder = invites.holder(con, meta["user"])
            con.execute("DELETE FROM stripe_subs WHERE holder=?", (holder,))
            accounts.set_plan(con, meta["user"], plans.DEFAULT)
            con.commit()
            return "plan_ended"
        return "ignored"
    # recorded in stripe_events only: payment failures, refunds, disputes need a person to look at them
    return "logged"
