"""VeriPura price menu. PLACEHOLDERS: real codes and prices come from VeriPura.
price_cents None means the price is to be set by VeriPura and the item cannot be paid."""

MENU = {
    "tariff_lookup": {"price_cents": None},
    "label_review": {"price_cents": None, "compliance": True},
    "core_document_check": {"price_cents": None, "compliance": True},
}

# Invite credits. None means VeriPura has not set the amount, so no credit is granted.
INVITE = {"credit_cents": None, "expiry_days": 90}
