import hashlib
import hmac
import json
import os
import time
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, db, invites, stripe_pay
from test_journey import make_case, who


class FakeStripe:
    """Stands in for the Stripe API. Records every call, returns canned objects."""

    def __init__(self):
        self.calls = []
        self.session = {}

    def __call__(self, method, path, data=None, idem=None):
        self.calls.append((method, path, data, idem))
        if path == "/customers":
            return {"id": "cus_test_1"}
        if path == "/coupons":
            return {"id": "co_test_1"}
        if path == "/checkout/sessions" and method == "POST":
            return {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}
        if path == "/billing_portal/sessions":
            return {"url": "https://billing.stripe.com/p/session/test"}
        if path.startswith("/checkout/sessions/"):
            return self.session
        raise AssertionError(path)


class StripeTestBase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeStripe()
        self._call, stripe_pay._call = stripe_pay._call, self.fake
        self._key, stripe_pay._key = stripe_pay._key, lambda: "sk_test_abc"
        c = app.con()
        for t in ("stripe_customers", "stripe_subs", "stripe_events", "credit_ledger", "invite_uses", "invites"):
            c.execute(f"DELETE FROM {t}")
        c.commit()

    def tearDown(self):
        stripe_pay._call, stripe_pay._key = self._call, self._key


class ModeTest(unittest.TestCase):
    def test_modes(self):
        k = stripe_pay._key
        try:
            stripe_pay._key = lambda: None
            self.assertIsNone(stripe_pay.mode())
            stripe_pay._key = lambda: "sk_test_x"
            self.assertEqual(stripe_pay.mode(), "test")
            stripe_pay._key = lambda: "rk_test_x"
            self.assertEqual(stripe_pay.mode(), "test")
            stripe_pay._key = lambda: "sk_live_x"
            self.assertIsNone(stripe_pay.mode())  # live keys are refused unless explicitly allowed
            os.environ["STRIPE_ALLOW_LIVE"] = "1"
            self.assertEqual(stripe_pay.mode(), "live")
        finally:
            os.environ.pop("STRIPE_ALLOW_LIVE", None)
            stripe_pay._key = k

    def test_off_without_a_key_keeps_the_simulation(self):
        self.assertFalse(stripe_pay.enabled())
        cid = make_case("s0")
        self.assertEqual(app.handle_pay({"case_id": cid, "selected": ["label_check"]}, who("s0"))[0], 501)
        self.assertEqual(app.handle_simpay({"case_id": cid, "selected": ["label_check"]}, who("s0"))[0], 200)


class WebhookSignatureTest(unittest.TestCase):
    def sign(self, raw, secret, t):
        return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()

    def test_valid_bad_and_stale(self):
        raw = json.dumps({"id": "evt_1", "type": "x"}).encode()
        t = int(time.time())
        self.assertEqual(stripe_pay.verify_webhook(raw, self.sign(raw, "whsec_a", t), "whsec_a")["id"], "evt_1")
        with self.assertRaises(stripe_pay.StripeError):
            stripe_pay.verify_webhook(raw, self.sign(raw, "whsec_other", t), "whsec_a")
        with self.assertRaises(stripe_pay.StripeError):
            stripe_pay.verify_webhook(raw + b" ", self.sign(raw, "whsec_a", t), "whsec_a")
        with self.assertRaises(stripe_pay.StripeError):
            stripe_pay.verify_webhook(raw, self.sign(raw, "whsec_a", t - 4000), "whsec_a")
        with self.assertRaises(stripe_pay.StripeError):
            stripe_pay.verify_webhook(raw, "garbage", "whsec_a")

    def test_endpoint_rejects_without_valid_signature(self):
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_a"
        try:
            raw = b'{"id":"evt_9","type":"x"}'
            self.assertEqual(app.handle_stripe_webhook(raw, "t=1,v1=00")[0], 400)
            self.assertEqual(app.handle_stripe_webhook(raw, self.sign(raw, "whsec_a", int(time.time())))[0], 200)
        finally:
            del os.environ["STRIPE_WEBHOOK_SECRET"]



class ItemPaymentTest(StripeTestBase):
    def test_pay_builds_checkout_with_metadata_and_idempotency(self):
        cid = make_case("p1")
        code, out = app.handle_pay({"case_id": cid, "selected": ["label_check"], "lang": "en"}, who("p1"), "example.test")
        self.assertEqual(code, 200)
        self.assertTrue(out["url"].startswith("https://checkout.stripe.com"))
        _, path, data, idem = [c for c in self.fake.calls if c[1] == "/checkout/sessions"][0]
        self.assertEqual(data["mode"], "payment")
        self.assertEqual(data["metadata"]["case_id"], cid)
        self.assertEqual(data["metadata"]["kind"], "items")
        self.assertTrue(data["success_url"].startswith("https://example.test/?paid={CHECKOUT_SESSION_ID}"))
        self.assertTrue(idem.startswith("co-"))
        self.assertTrue(all(li["price_data"]["currency"] == "eur" for li in data["line_items"]))

    def test_double_click_sends_the_same_idempotency_key(self):
        cid = make_case("p2")
        for _ in range(2):
            app.handle_pay({"case_id": cid, "selected": ["label_check"]}, who("p2"), "example.test")
        keys = [c[3] for c in self.fake.calls if c[1] == "/checkout/sessions"]
        self.assertEqual(len(set(keys)), 1)

    def test_other_users_case_is_refused(self):
        cid = make_case("p3")
        self.assertEqual(app.handle_pay({"case_id": cid, "selected": ["label_check"]}, who("intruder"), "h")[0], 404)

    def test_paid_session_is_recorded_once_and_credit_spent_once(self):
        c = app.con()
        c.execute("INSERT INTO credit_ledger(user_sub, delta_cents, kind, code, at, simulated) VALUES (?,?,?,?,?,?)",
                  ("p4", 2000, "grant", None, db.now(), 1)); c.commit()
        cid = make_case("p4")
        s = {"id": "cs_test_4", "payment_status": "paid",
             "metadata": {"kind": "items", "case_id": cid, "user": "p4", "items": "label_check,tariff_lookup",
                          "total_cents": "3900", "credit_cents": "2000"}}
        first = stripe_pay.session_paid(c, s)
        again = stripe_pay.session_paid(c, s)
        self.assertEqual(first["status"], "paid")
        self.assertTrue(again["already"])
        n = c.execute("SELECT COUNT(*) FROM events WHERE case_id=? AND kind='payment'", (cid,)).fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(invites.balance(c, "p4"), 0)

    def test_unpaid_session_records_nothing(self):
        cid = make_case("p5")
        s = {"id": "cs_test_5", "payment_status": "unpaid",
             "metadata": {"kind": "items", "case_id": cid, "user": "p5", "items": "label_check", "total_cents": "3900", "credit_cents": "0"}}
        self.assertEqual(stripe_pay.session_paid(app.con(), s)["status"], "unpaid")
        self.assertIsNone(app.con().execute("SELECT 1 FROM events WHERE case_id=? AND kind='payment'", (cid,)).fetchone())

    def test_simulated_payment_is_closed_while_stripe_is_on(self):
        cid = make_case("p6")
        self.assertEqual(app.handle_simpay({"case_id": cid, "selected": ["label_check"]}, who("p6"))[0], 409)

    def test_confirm_checks_the_session_belongs_to_the_caller(self):
        cid = make_case("p7")
        self.fake.session = {"id": "cs_test_7", "payment_status": "paid",
                             "metadata": {"kind": "items", "case_id": cid, "user": "p7", "holder": "p7",
                                          "items": "label_check", "total_cents": "3900", "credit_cents": "0"}}
        self.assertEqual(app.handle_pay_confirm({"session_id": "cs_test_7"}, who("someone_else"))[0], 404)
        code, out = app.handle_pay_confirm({"session_id": "cs_test_7"}, who("p7"))
        self.assertEqual((code, out["status"]), (200, "paid"))
        self.assertEqual(app.handle_pay_confirm({"session_id": "nope"}, who("p7"))[0], 400)


class PlanTest(StripeTestBase):
    def test_paid_plans_only_change_through_stripe(self):
        self.assertEqual(app.handle_plan({"plan": "parti"}, who("q1"))[0], 409)
        code, out = app.handle_plan_checkout({"plan": "parti"}, who("q1"), "example.test")
        self.assertEqual(code, 200)
        data = [c for c in self.fake.calls if c[1] == "/checkout/sessions"][0][2]
        self.assertEqual(data["mode"], "subscription")
        self.assertEqual(data["line_items"][0]["price_data"]["recurring"], {"interval": "month"})
        self.assertEqual(data["line_items"][0]["price_data"]["unit_amount"], 2900)

    def test_free_plan_is_not_a_checkout(self):
        self.assertEqual(app.handle_plan_checkout({"plan": "esplora"}, who("q2"), "h")[0], 400)

    def test_subscription_paid_sets_plan_and_invite_credit_once_in_test_mode(self):
        c = app.con(); code = invites.get_or_create(c, "inviter"); invites.accept(c, "q3", code)
        s = {"id": "cs_test_p", "payment_status": "paid", "subscription": "sub_1",
             "metadata": {"kind": "plan", "plan": "parti", "user": "q3", "holder": "q3"}}
        stripe_pay.session_paid(c, s); stripe_pay.session_paid(c, s)
        self.assertEqual(app.handle_plan({}, who("q3"))[1]["plan"], "parti")
        self.assertEqual(invites.balance(c, "q3"), 2000)  # example amount, labelled simulated, test mode only
        self.assertTrue(invites.has_simulated(c, "q3"))
        self.assertTrue(stripe_pay.has_active_subscription(c, "q3"))

    def test_active_subscriber_is_sent_to_the_portal(self):
        c = app.con()
        stripe_pay.session_paid(c, {"id": "cs_t", "payment_status": "paid", "subscription": "sub_2",
                                    "metadata": {"kind": "plan", "plan": "parti", "user": "q4", "holder": "q4"}})
        out = app.handle_plan_checkout({"plan": "cresci"}, who("q4"), "h")[1]
        self.assertIn("billing.stripe.com", out["url"])
        self.assertEqual(app.handle_plan({"plan": "esplora"}, who("q4"))[0], 409)

    def test_cancelled_subscription_returns_to_free_and_events_run_once(self):
        c = app.con()
        stripe_pay.session_paid(c, {"id": "cs_c", "payment_status": "paid", "subscription": "sub_3",
                                    "metadata": {"kind": "plan", "plan": "cresci", "user": "q5", "holder": "q5"}})
        ev = {"id": "evt_del_1", "type": "customer.subscription.deleted",
              "data": {"object": {"id": "sub_3", "status": "canceled", "metadata": {"user": "q5", "plan": "cresci"}}}}
        self.assertEqual(stripe_pay.process_event(c, ev), "plan_ended")
        self.assertEqual(stripe_pay.process_event(c, ev), "duplicate")
        self.assertEqual(app.handle_plan({}, who("q5"))[1]["plan"], "esplora")
        self.assertFalse(stripe_pay.has_active_subscription(c, "q5"))

    def test_unknown_events_are_logged_not_acted_on(self):
        ev = {"id": "evt_x", "type": "charge.refunded", "data": {"object": {}}}
        self.assertEqual(stripe_pay.process_event(app.con(), ev), "logged")


if __name__ == "__main__":
    unittest.main()
