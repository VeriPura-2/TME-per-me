"""Run the known-answer pack against the live tariff services.

    python -m vialibera.check_tariffs

Exit code 0 when every implemented known answer matches, 1 otherwise. Run it after any parser
change and before relying on the duty lookups.
"""
import sys

from . import db
from .adapters.tariff import UKTradeTariff, USITCHts, pct, uk_duties, us_general
from .known_answers import KNOWN_ANSWERS


def run():
    con = db.connect()
    ok = True
    for ka in KNOWN_ANSWERS:
        if ka["adapter"] == "uk_trade_tariff":
            d = uk_duties(UKTradeTariff().call(con, "fetch", commodity_code=ka["commodity_code"])["data"]["document"])
            got = {"duty_pct": pct(d["preferential_eu"]), "import_vat_pct": pct(d["vat"])}
        elif ka["adapter"] == "usitc_hts":
            d = us_general(USITCHts().call(con, "fetch", code=ka["code"])["data"]["results"], ka["code"])
            got = {"duty": d["normalised"] if d else None}
        else:
            print(f"SKIP {ka['id']}: adapter {ka['adapter']} not built ({ka['note']})")
            continue
        match = all(got.get(k) == v for k, v in ka["expect"].items())
        ok = ok and match
        print(("PASS " if match else "FAIL ") + ka["id"], got, "expected", ka["expect"])
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
