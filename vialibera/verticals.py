"""Verticals: the industry a project belongs to (food today, fashion later).

The vertical is stored per project (cases.vertical). An empty or unknown value means food, so every project
created before this column existed behaves exactly as before. Fashion is registered but switched off: no start
form, chat or API path creates a Fashion project until it is enabled in a later step.
"""
from . import lane_requests, requirements

DEFAULT = "food"

VERTICALS = {
    # The food entry points at the lists the app already uses, it does not copy them.
    "food": {"enabled": True, "label": {"it": "Alimentare", "en": "Food"},
             "products": requirements.PRODUCTS, "destinations": requirements.DESTINATIONS,
             "covered_products": lane_requests.COVERED_PRODUCTS, "covered_countries": lane_requests.COVERED_COUNTRIES},
    "fashion": {"enabled": False, "label": {"it": "Moda", "en": "Fashion"}},
}


def vertical_of(case):
    """The vertical key of a case (a dict from db.case_read or a row). Anything empty or unknown reads as food."""
    try:
        v = (case or {}).get("vertical") if isinstance(case, dict) else case["vertical"]
    except (KeyError, IndexError, TypeError):
        v = None
    v = str(v or "").strip().lower()
    return v if v in VERTICALS else DEFAULT


def enabled(vertical):
    """True when projects of this vertical may be created."""
    return bool(VERTICALS.get(vertical, {}).get("enabled"))
