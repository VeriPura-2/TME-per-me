"""Control-body request helper (Valoritalia, Kiwa): prefill, consent, states, who may act. Offline, no AI calls."""
import os

os.environ.setdefault("DB_PATH", ":memory:")

from vialibera import app, cert_requests, db, permissions  # noqa: E402


def who(u):
    return {"user": u, "org": None, "roles": []}


def make(owner="cr1", denomination="Barolo", vat="IT01234567890", address="Via Roma 1, 12051 Alba (CN)"):
    c = app.con()
    cid = db.create_case(c, 1, owner_sub=owner)
    db.case_write(c, cid, "company", {"legal_name": "Cantina Rossi Srl", "vat_number": vat, "address_region": address, "contact": "Anna Rossi"})
    db.case_write(c, cid, "product", {"category": "wine", "name_brand": "Barolo Rossi", "denomination": denomination})
    c.commit()
    return c, cid, c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()


def test_info_names_the_body_and_prefills_the_text():
    c, cid, row = make()
    d = cert_requests.info(c, row, "it")
    assert [b["body_id"] for b in d["bodies"]] == ["valoritalia"]
    b = d["bodies"][0]
    assert b["supported"] and b["page"].startswith("https://www.valoritalia.it")
    for part in ("Cantina Rossi Srl", "IT01234567890", "Via Roma 1", "Barolo"):
        assert part in b["text"]
    assert d["missing"] == [] and "verific" in d["note"].lower()


def test_text_makes_no_certification_claim():
    c, cid, row = make()
    t = cert_requests.info(c, row)["bodies"][0]["text"].lower()
    assert "è certificat" not in t and "certificata" not in t


def test_kiwa_product_is_supported_and_unknown_name_has_no_body():
    c, cid, row = make(denomination="Aceto Balsamico Tradizionale di Modena")
    assert [b["body_id"] for b in cert_requests.info(c, row)["bodies"]] == ["kiwa"]
    c, cid, row = make(denomination="Zzz Not A Cheese")
    assert cert_requests.info(c, row)["bodies"] == []


def test_other_bodies_are_listed_but_not_supported():
    c, cid, row = make(denomination="Parmigiano Reggiano")
    b = cert_requests.info(c, row)["bodies"][0]
    assert not b["supported"] and b["text"] is None
    assert "error" in cert_requests.prepare(c, row, "s", b["body_id"], True)


def test_prepare_needs_consent_and_a_complete_record():
    c, cid, row = make()
    assert "consent" in cert_requests.prepare(c, row, "s", "valoritalia", False)["error"]
    c, cid, row = make(vat="")
    assert "vat" in cert_requests.prepare(c, row, "s", "valoritalia", True)["error"]
    c, cid, row = make()
    assert "not list" in cert_requests.prepare(c, row, "s", "kiwa", True)["error"]  # Barolo is not Kiwa's


def test_states_go_in_order_and_cert_status_is_untouched():
    c, cid, row = make()
    db.case_write(c, cid, "company", {"cert_status": "claimed"})
    rid = cert_requests.prepare(c, row, "staff1", "valoritalia", True)["request_id"]
    assert "error" in cert_requests.set_state(c, who("staff1"), row, rid, "reply_received")  # cannot skip "sent"
    assert cert_requests.set_state(c, who("staff1"), row, rid, "sent") == {"ok": True}
    assert "error" in cert_requests.set_state(c, who("staff1"), row, rid, "sent")  # not twice
    assert cert_requests.set_state(c, who("staff1"), row, rid, "reply_received", "no-such-doc") == {"error": "document not found"}
    assert cert_requests.set_state(c, who("staff1"), row, rid, "reply_received") == {"ok": True}
    q = cert_requests.listing(c, cid)[0]
    assert (q["state"], q["sent_by"], q["reply_by"], q["consent"]) == ("reply_received", "staff1", "staff1", 1)
    assert db.case_read(c, cid)["company"]["cert_status"] == "claimed"
    kinds = [r["data"] for r in c.execute("SELECT data FROM events WHERE kind='cert_request' AND case_id=?", (cid,))]
    assert len(kinds) == 3


def test_only_staff_and_tem_may_change_exporter_may_look(monkeypatch):
    c, cid, row = make(owner="cr9")
    body = {"case_id": cid, "action": "prepare", "body_id": "valoritalia", "consent": True}
    code, d = app.handle_certreq({"case_id": cid}, who("cr9"))
    assert code == 200 and d["can_edit"] is False and d["bodies"]
    assert app.handle_certreq(body, who("cr9"))[0] == 403
    assert cert_requests.listing(c, cid) == []
    monkeypatch.setattr(permissions, "case_role", lambda *a: "tem")
    code, d = app.handle_certreq({"case_id": cid}, who("cr9"))
    assert d["can_edit"] is True
    code, r = app.handle_certreq(body, who("cr9"))
    assert code == 200 and r["ok"]
    assert app.handle_certreq({"case_id": cid, "action": "sent", "request_id": r["request_id"]}, who("cr9"))[0] == 200
    assert app.handle_certreq({"case_id": cid, "action": "nonsense"}, who("cr9"))[0] == 400
    monkeypatch.setattr(permissions, "case_role", lambda *a: "support")
    assert app.handle_certreq(body, who("cr9"))[0] == 403  # read-only staff cannot change


def test_schema_has_the_table_and_the_route_is_listed():
    assert "cert_requests" in db.SCHEMA
    import inspect
    assert '"/certreq"' in inspect.getsource(app)
