"""Run the known-answer pack LIVE and print PASS / DIFF / SKIP per case.

Usage: python3 scripts/run_known_answers.py
Expected values are never edited to fit a result. A DIFF is reported as is.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vialibera import db  # noqa: E402
from vialibera.adapters.base import AdapterError  # noqa: E402
from vialibera.adapters.tariff import UKTradeTariff, USITCHts  # noqa: E402
from vialibera.known_answers import KNOWN_ANSWERS  # noqa: E402


def check(con, case):
    exp = case["expect"]
    if case["adapter"] == "uk_trade_tariff":
        out = UKTradeTariff().call(con, "fetch", commodity_code=case["commodity_code"], origin="IT")
        p = out["data"]["parsed"]
        got = {"duty_pct": p["duty_pct"], "import_vat_pct": p["import_vat_pct"]}
        return all(got[k] == v for k, v in exp.items()), got
    if case["adapter"] == "usitc_hts":
        out = USITCHts().call(con, "fetch", code=case["code"])
        p = out["data"]["parsed"]
        got = {"duty": p["general"] if p else None}
        want = float(exp["duty"].split()[0])
        return bool(p) and p["cents_per_kg"] == want, got
    return None, "no live parser yet (CBSA not parsed, flagged only)"


def main():
    con = db.connect()
    bad = 0
    for case in KNOWN_ANSWERS:
        try:
            ok, got = check(con, case)
        except AdapterError as e:
            ok, got = False, str(e)
        label = "SKIP" if ok is None else ("PASS" if ok else "DIFF")
        bad += label == "DIFF"
        print(f"{label} {case['id']}: expected {case['expect']} got {got}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
