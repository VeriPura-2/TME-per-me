"""Known-answer test pack for tariff adapters (spec section 3, BorderSage lesson).

Expected values come from official sources checked on 23 Oct 2026 (see the
calculator build handoff). An adapter may not go live until it reproduces these.
"""

KNOWN_ANSWERS = [
    {"id": "pasta_it_uk", "adapter": "uk_trade_tariff", "commodity_code": "1902199090",
     "expect": {"duty_pct": 0, "import_vat_pct": 0}, "note": "EU origin 0% duty, UK import VAT 0%"},
    {"id": "evoo_it_us_retail", "adapter": "usitc_hts", "code": "1509.20.20",
     "expect": {"duty": "5 cents/kg"}, "note": "retail packs under 18 kg"},
    {"id": "evoo_it_us_bulk", "adapter": "usitc_hts", "code": "1509.20.90",
     "expect": {"duty": "3.4 cents/kg"}, "note": "other"},
    {"id": "parmigiano_it_ca", "adapter": "cbsa", "code": "0406.90",
     "expect": {"flags": ["CETA tariff rate quota 16,000,000 kg", "import permit required"]},
     "note": "partial: in-quota duty and GST not yet read, flagged only"},
]
