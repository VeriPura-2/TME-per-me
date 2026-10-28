"""Usage plans. Structure only, no money. Prices and discounts come from the
VeriPura price menu (sim/prices.py until VeriPura supplies real values).

Item levels: 1 instant, 2 checked, 3 managed by staff or partners.
"""

PLANS = {
    "esplora": {"rank": 0, "name": {"it": "Esplora", "en": "Explore"}, "tier": {"it": "Gratuito", "en": "Free"},
                "monthly": False, "max_projects": 1, "team_members": 1, "alerts": False, "priority_help": False},
    "parti":   {"rank": 1, "name": {"it": "Parti", "en": "Start"}, "tier": {"it": "Base", "en": "Basic"},
                "monthly": True, "max_projects": 5, "team_members": 3, "alerts": False, "priority_help": False},
    "cresci":  {"rank": 2, "name": {"it": "Cresci", "en": "Grow"}, "tier": {"it": "Avanzato", "en": "Advanced"},
                "monthly": True, "max_projects": None, "team_members": 10, "alerts": True, "priority_help": True},
}

LEVELS = {
    1: {"name": {"it": "Immediato", "en": "Instant"}, "items": ["required_docs", "tariff_lookup", "export_documents"]},
    2: {"name": {"it": "Verificato", "en": "Checked"}, "items": ["document_check", "label_check", "landed_cost"]},
    3: {"name": {"it": "Seguito dallo staff", "en": "Managed"}, "items": ["lab_cert", "importer_search", "forwarder_quotes"]},
}

DEFAULT = "esplora"


def get(plan_id):
    return PLANS.get(plan_id) or PLANS[DEFAULT]


def level_of(item):
    for lv, v in LEVELS.items():
        if item in v["items"]:
            return lv
    return None


def can_add_project(plan_id, current_projects):
    cap = get(plan_id)["max_projects"]
    return cap is None or current_projects < cap


def public():
    return {"plans": PLANS, "levels": LEVELS, "default": DEFAULT}
