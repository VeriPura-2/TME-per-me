"""Duties for the reference lanes, from official tariff sources.

Lanes (approved 1 Nov 2026): dried pasta Italy -> UK, olive oil Italy -> US. Canada (Parmigiano
Reggiano, CETA quota and import permit) is flagged for staff. Every answer carries its source,
the date it was read, and its limits. Answers are cached for a day, so a page load never waits
on the tariff service more than once a day per code.
"""
import json
from datetime import datetime, timedelta, timezone

from . import db, requirements
from .adapters.base import AdapterError
from .adapters.tariff import UKTradeTariff, USITCHts, pct, uk_duties, us_general

CACHE_HOURS = 24

UK_SRC = "https://www.trade-tariff.service.gov.uk/commodities/{code}"
US_SRC = "https://hts.usitc.gov/search?query={code}"

US_LIMIT = {"it": "Solo dazio generale USA (colonna 1). Non include i dazi aggiuntivi USA del capitolo 99 dell'HTS "
                  "(per esempio sui prodotti UE) né eventuali dazi antidumping: verifica dello staff.",
            "en": "US general duty (column 1) only. It does not include additional US duties under HTS chapter 99 "
                  "(for example on EU goods) or any antidumping duties: staff to check."}
UK_LIMIT = {"it": "Il dazio preferenziale richiede la dichiarazione di origine UE in fattura.",
            "en": "The preferential duty needs the EU origin statement on the invoice."}
CA_STAFF = {"it": "Canada: dazio e quota CETA per il formaggio (permesso di importazione) da verificare dallo staff.",
            "en": "Canada: duty and CETA cheese quota (import permit) to be checked by staff."}
EGG_STAFF = {"it": "Pasta all'uovo: codice doganale diverso, da verificare dallo staff.",
             "en": "Egg pasta: different commodity code, to be checked by staff."}


def _cached(con, key, fetch):
    r = con.execute("SELECT at, data FROM tariff_cache WHERE key=?", (key,)).fetchone()
    if r and datetime.fromisoformat(r["at"]) > datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS):
        return json.loads(r["data"]), r["at"]
    data = fetch()
    at = db.now()
    con.execute("DELETE FROM tariff_cache WHERE key=?", (key,))
    con.execute("INSERT INTO tariff_cache(key, at, data) VALUES (?,?,?)", (key, at, json.dumps(data)))
    con.commit()
    return data, at


def uk_pasta(con, uk=None):
    code = "1902199090"
    uk = uk or UKTradeTariff()

    def fetch():
        res = uk.call(con, "fetch", commodity_code=code)
        return uk_duties(res["data"]["document"])
    d, at = _cached(con, "uk:" + code, fetch)
    return {"destination": "UK", "code": code, "description": d.get("description") or "Dried pasta, no egg (other)",
            "lines": [{"label": {"it": "Dazio con origine UE (accordo UE-UK)", "en": "Duty with EU origin (EU-UK TCA)"}, "value": d["preferential_eu"]},
                      {"label": {"it": "Dazio senza prova di origine", "en": "Duty without proof of origin"}, "value": d["third_country"]},
                      {"label": {"it": "IVA all'importazione UK", "en": "UK import VAT"}, "value": d["vat"]}],
            "zero_duty": pct(d["preferential_eu"]) == 0.0, "limit": UK_LIMIT,
            "source": UK_SRC.format(code=code), "retrieved_at": at}


def us_oil(con, us=None):
    us = us or USITCHts()
    lines = []
    at = None
    for code, lab in (("1509.20.20", {"it": "Confezioni sotto i 18 kg", "en": "Packs under 18 kg"}),
                      ("1509.20.90", {"it": "Altre confezioni", "en": "Other packs"})):
        def fetch(code=code):
            res = us.call(con, "fetch", code=code)
            return us_general(res["data"]["results"], code)
        d, at = _cached(con, "us:" + code, fetch)
        lines.append({"label": lab, "value": d["normalised"] if d else None, "code": code})
    return {"destination": "US", "code": "1509.20", "description": "Extra virgin olive oil",
            "lines": lines, "limit": US_LIMIT, "source": US_SRC.format(code="1509.20"), "retrieved_at": at}


def for_case(con, case, uk=None, us=None):
    """Duties block for the Journey and the TEM workspace. None when the lane has no duty lookup yet."""
    ln = requirements.lane(case["product"].get("category"), case["market"].get("country"))
    if not ln:
        return None
    p, d = ln
    try:
        if (p, d) == ("pasta", "UK"):
            egg = str(case["product"].get("egg_wheat_type") or "").lower()
            if "egg" in egg and "no egg" not in egg:
                return {"staff": EGG_STAFF}
            return uk_pasta(con, uk)
        if (p, d) == ("oil", "US"):
            return us_oil(con, us)
        if (p, d) == ("cheese", "CA"):
            return {"staff": CA_STAFF}
    except AdapterError as e:
        db.log_event(con, case.get("id"), "system", "tariff_unavailable", {"error": str(e)[:200]})
        return {"unavailable": True}
    return None
