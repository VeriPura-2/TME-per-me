import pathlib
from vialibera import ocqpr

FX = pathlib.Path(__file__).parent / "fixtures"
RES = (FX / "ocqpr_results.html").read_text()
DET = (FX / "ocqpr_detail.html").read_text()
VAT = "00182350363"


def fake(url):
    return DET if "/c3014" in url else RES


def test_normalise():
    assert ocqpr.normalise_vat("IT 00182350363") == VAT
    assert ocqpr.normalise_vat("0018235036") is None
    assert ocqpr.normalise_vat(None) is None


def test_parse_results():
    r = ocqpr.parse_results(RES)
    assert len(r) == 1 and r[0]["name"].startswith("4 MADONNE")
    assert r[0]["chain"] == "DOP PARMIGIANO REGGIANO" and r[0]["validity_status"] == "ATTIVO"
    assert r[0]["municipality"] == "SERRAMAZZONI (MO)" and r[0]["detail"] == "/aziende-certificate/c3014"
    assert ocqpr.list_date(RES) == "2026-11-03"


def test_list_date_formats():
    assert ocqpr.list_date("<p>aggiornato al 03 novembre 2026</p>") == "2026-11-03"
    assert ocqpr.list_date("aggiornato al 3/1/2026") == "2026-01-03"


def test_many_productions_one_company():
    page = RES + RES.replace("c3014", "m329").replace("DOP PARMIGIANO REGGIANO", "ACETO BALSAMICO")
    r = ocqpr.check_vat(VAT, fetcher=lambda u: DET if "/c3014" in u else page)
    assert len(r["records"]) == 2 and len(r["companies"]) == 1


def test_parse_detail():
    d = ocqpr.parse_detail(DET)
    assert d["vat"] == VAT and d["certificate_no"] == "12/14" and d["issued"] == "23/10/14" and d["valid_from"] == "19/11/13"


def test_check_listed_and_mismatch():
    r = ocqpr.check_vat("IT" + VAT, "en", fetcher=fake)
    assert r["status"] == "listed" and r["confirmed_vat"] is True and r["companies"] == ["4 MADONNE CASEIFICIO DELL'EMILIA S.C.A."] and r["list_date"] == "2026-11-03"
    assert ocqpr.check_vat("11111111111", fetcher=fake)["status"] == "not_listed"


def test_unavailable_and_invalid():
    def boom(u):
        raise OSError("down")
    assert ocqpr.check_vat(VAT, fetcher=boom)["status"] == "unavailable"
    assert ocqpr.check_vat("abc")["status"] == "invalid"


def test_host_restricted():
    import pytest
    with pytest.raises(ValueError):
        ocqpr.fetch("https://example.com/")




def test_exporter_only_own_vat_tem_any(monkeypatch):
    import os
    os.environ.setdefault("DB_PATH", ":memory:")
    from vialibera import app, db, permissions
    from test_journey import who
    c = app.con()
    cid = db.create_case(c, 1, owner_sub="oq1")
    db.case_write(c, cid, "company", {"legal_name": "Rossi", "vat_number": "IT01234567890"})
    c.commit()
    seen = []
    monkeypatch.setattr(ocqpr, "check_vat", lambda v, lang="it": seen.append(v) or {"status": "not_listed"})
    assert app.handle_ocqpr({"case_id": cid, "info": True}, who("oq1"))[1] == {"mode": "own", "vat": "01234567890"}
    app.handle_ocqpr({"case_id": cid, "vat": "99999999999"}, who("oq1"))
    assert seen == ["IT01234567890"]
    monkeypatch.setattr(permissions, "case_role", lambda *a: "tem")
    assert app.handle_ocqpr({"case_id": cid, "info": True}, who("oq1"))[1]["mode"] == "any"
    app.handle_ocqpr({"case_id": cid, "vat": "99999999999"}, who("oq1"))
    assert seen[-1] == "99999999999"
