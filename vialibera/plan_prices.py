"""The plan price menu, in euro cents. Set by Thomas on 8 Nov 2026.

monthly: the plan fee. levels: price per item by level (see plans.LEVELS): 1 instant (free),
2 checked (document check, label check, landed cost), 3 managed by staff or partners.
None means the plan cannot buy that level: Explore gets one free check, then needs a paid plan.
The TEM plan is not offered to exporters; the TEM pays for checks on client projects at Grow prices.
"""

MENU = {
    "esplora": {"monthly": 0,      "levels": {1: 0, 2: None, 3: None}},
    "parti":   {"monthly": 25000,  "levels": {1: 0, 2: 2900, 3: 9900}},
    "cresci":  {"monthly": 75000,  "levels": {1: 0, 2: 2900, 3: 7900}},
    "tem":     {"monthly": 100000, "levels": {1: 0, 2: 2900, 3: 7900}},
}
