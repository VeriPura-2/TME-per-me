"""Run the known-answer pack against LIVE sources. Prints PASS, DIFF or UNVERIFIED per case.

Run from the repo root:  python3 scripts/run_known_answers.py
Exit code 0 only if every checked case passes. Expected values are never edited to fit a result.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from vialibera import db  # noqa: E402
from vialibera.adapters.base import AdapterError  # noqa: E402
from vialibera.adapters.tariff import (CBSA_CH4, USITCHts, UKTradeTariff, http_get,  # noqa: E402
                                       parse_cbsa_rows)
from vialibera.known_answers import KNOWN_ANSWERS  # noqa: E402


def check(con, ka):
    if ka["adapter"] == "uk_trade_tariff":
        p = UKTradeTariff().call(con, "fetch", commodity_code=ka["commodity_code"])["data"]["parsed"]
        got = {"duty_pct": p["duty_pct"], "import_vat_pct": p["import_vat_pct"]}
        return got == ka["expect"], got
    if ka["adapter"] == "usitc_hts":
        p = USITCHts().call(con, "fetch", code=ka["code"])["data"]["parsed"]
        if p is None:
            return False, "code not found"
        cents = p["cents_per_kg"]
        got = {"duty": None if cents is None else f"{cents:g} cents/kg", "raw": p["general"]}
        return got["duty"] == ka["expect"]["duty"], got
    if ka["adapter"] == "cbsa":
        rows = parse_cbsa_rows(http_get(CBSA_CH4), "0406.90.9")
        got = [(r["item"], r["mfn"], r["ceta_in_preference_list"]) for r in rows if r["item"] in ("0406.90.93", "0406.90.94")]
        return None, {"table_rows": got,
                      "note": "TRQ volume and import permit are not on the CBSA tariff page; flags stay UNVERIFIED"}
    return None, "no checker"


def main():
    con = db.connect()
    failed = 0
    for ka in KNOWN_ANSWERS:
        try:
            ok, got = check(con, ka)
        except AdapterError as e:
            print(f"UNVERIFIED {ka['id']}: {e}")
            failed += 1
            continue
        if ok is None:
            print(f"UNVERIFIED {ka['id']}: {got}")
        elif ok:
            print(f"PASS       {ka['id']}: {got}")
        else:
            failed += 1
            print(f"DIFF       {ka['id']}: expected {ka['expect']}, live {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
