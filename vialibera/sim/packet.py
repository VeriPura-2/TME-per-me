"""SIMULATED options packet. Items, dependency rules and prices are examples.
Delete when real adapters and the VeriPura menu exist; set "options_packet" to live."""
from . import tag, prices
from .. import plans

NEEDS = {  # interview "needs" answer keyword -> item
    "tariff": "tariff_lookup", "duty": "tariff_lookup", "dazi": "tariff_lookup",
    "label": "label_check", "etichett": "label_check",
    "export documents": "export_documents", "documenti": "export_documents",
    "importer": "importer_search", "importatore": "importer_search",
    "logistic": "forwarder_quotes",
    "certif": "lab_cert",
}
REQUIRES = {"landed_cost": ["tariff_lookup"], "export_documents": ["tariff_lookup"],
            "document_check": ["export_documents"], "forwarder_quotes": ["landed_cost"]}
NAMES = {
    "required_docs": ("Elenco documenti richiesti", "Required documents list"),
    "tariff_lookup": ("Dazi, IVA e quote", "Duty, VAT and quota lookup"),
    "landed_cost": ("Costo di sbarco", "Landed cost"),
    "export_documents": ("Documenti di esportazione", "Export documents"),
    "document_check": ("Controllo documenti", "Document check"),
    "label_check": ("Controllo etichetta", "Label check"),
    "importer_search": ("Ricerca importatori", "Importer search"),
    "forwarder_quotes": ("Preventivi spedizionieri", "Forwarder quotes"),
    "lab_cert": ("Analisi e certificazioni", "Lab and certification"),
}


def wanted_items(needs_text):
    low = (needs_text or "").lower()
    out = []
    for k, item in NEEDS.items():
        if k in low and item not in out:
            out.append(item)
    return out or ["tariff_lookup"]


def expand(selected):
    """Add required items. Returns (all items in order, {added item: [because of]})."""
    allitems, why = list(selected), {}
    changed = True
    while changed:
        changed = False
        for it in list(allitems):
            for req in REQUIRES.get(it, []):
                if req not in allitems:
                    allitems.insert(allitems.index(it), req); why[req] = [it]; changed = True
                elif req in why and it not in why[req]:
                    why[req].append(it)
    return allitems, why


def build(selected, plan_id):
    items, why = expand(selected)
    price_tbl = prices.EXAMPLE[plan_id]["levels"]
    rows = []
    for it in items:
        lv = plans.level_of(it)
        rows.append({"id": it, "name": {"it": NAMES[it][0], "en": NAMES[it][1]}, "level": lv,
                     "price_cents": price_tbl[lv], "added_because": why.get(it, [])})
    total = sum(r["price_cents"] for r in rows)
    return tag("options_packet", {"plan": plan_id, "items": rows, "total_cents": total,
                                  "monthly_cents": prices.EXAMPLE[plan_id]["monthly"], "currency": "EUR",
                                  "label": {"it": "Prezzi di esempio, da definire da VeriPura", "en": "Example prices, to be set by VeriPura"}})
