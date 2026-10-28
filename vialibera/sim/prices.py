"""SIMULATED example prices. Not VeriPura prices. Delete this file when
VeriPura supplies the real menu (menu.py) and set "price_menu" to live."""
from . import tag

# monthly fee in euro cents, and per-item price by level in cents
EXAMPLE = {
    "esplora": {"monthly": 0,    "levels": {1: 0,    2: 4900, 3: 14900}},
    "parti":   {"monthly": 2900, "levels": {1: 0,    2: 3900, 3: 11900}},
    "cresci":  {"monthly": 7900, "levels": {1: 0,    2: 2900, 3: 8900}},
}


def prices():
    return tag("price_menu", EXAMPLE)

# SIMULATED invite credit. Not a VeriPura offer. Replace with menu.INVITE.
INVITE_EXAMPLE = {"credit_cents": 2000, "expiry_days": 90}
