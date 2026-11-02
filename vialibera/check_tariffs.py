"""Run the known-answer pack against the live tariff services.

    python -m vialibera.check_tariffs

Exit code 0 when every implemented known answer matches, 1 otherwise. Run it after any parser
change and before relying on the duty lookups.
"""
import sys

from . import db
from .adapters.tariff import UKTradeTariff, USITCHts, pct, uk_duties, us_general
from .known_answers import KNOWN_ANSWERS


def results(uk=None, us=None):
    """[(id, matches, got, expected)] for every implemented known answer. Raises AdapterError when a service is down."""
    con = db.connect()
    uk, us = uk or UKTradeTariff(), us or USITCHts()
    out = []
    for ka in KNOWN_ANSWERS:
        if ka["adapter"] == "uk_trade_tariff":
            d = uk_duties(uk.call(con, "fetch", commodity_code=ka["commodity_code"])["data"]["document"])
            got = {"duty_pct": pct(d["preferential_eu"]), "import_vat_pct": pct(d["vat"])}
        elif ka["adapter"] == "usitc_hts":
            d = us_general(us.call(con, "fetch", code=ka["code"])["data"]["results"], ka["code"])
            got = {"duty": d["normalised"] if d else None}
        else:
            continue
        out.append((ka["id"], all(got.get(k) == v for k, v in ka["expect"].items()), got, ka["expect"]))
    return out


def run():
    ok = True
    for ka_id, match, got, expect in results():
        ok = ok and match
        print(("PASS " if match else "FAIL ") + ka_id, got, "expected", expect)
    for ka in KNOWN_ANSWERS:
        if ka["adapter"] not in ("uk_trade_tariff", "usitc_hts"):
            print(f"SKIP {ka['id']}: adapter {ka['adapter']} not built ({ka['note']})")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
