"""Duties for every Wave 1 lane, shown to the client.

Decided 2 Nov 2026: clients see the duties for every product on every lane. Values come from the
weekly tariff check (tariff_watch), which reads the official sources and stores each line in
duty_snapshots; staff see any change in Data changes. EU destinations have no customs duty.
Every answer carries its source, the date it was read, and its limits.
"""
import json

from . import requirements, tariff_watch

SOURCES = {
    "UK": "https://www.trade-tariff.service.gov.uk/",
    "US": "https://hts.usitc.gov/",
    "CA": "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/menu-eng.html",
    "CH": "https://xtares.admin.ch/tares/login/loginFormFiller.do?l=en",
}

LIMIT = {
    "UK": {"it": "Il dazio preferenziale richiede la dichiarazione di origine UE in fattura.",
           "en": "The preferential duty needs the EU origin statement on the invoice."},
    "US": {"it": "Solo dazio generale USA (colonna 1). Non include i dazi aggiuntivi USA del capitolo 99 dell'HTS "
                 "(per esempio sui prodotti UE) né eventuali dazi antidumping: verifica dello staff.",
           "en": "US general duty (column 1) only. It does not include additional US duties under HTS chapter 99 "
                 "(for example on EU goods) or any antidumping duties: staff to check."},
    "CA": {"it": "Il dazio CETA richiede la dichiarazione di origine in fattura. \"Entro il contingente\": solo per le "
                 "quantità coperte da un permesso di quota del destinatario; oltre, si applica l'aliquota più alta.",
           "en": "The CETA duty needs the origin statement on the invoice. \"Within access commitment\": only for "
                 "quantities covered by the consignee's quota permit; beyond it, the higher rate applies."},
    "CH": {"it": "L'aliquota UE richiede la prova dell'origine UE. Vino: l'aliquota entro il contingente richiede il "
                 "permesso generale d'importazione del destinatario.",
           "en": "The EU rate needs proof of EU origin. Wine: the within-quota rate needs the consignee's general "
                 "import permit."},
}

LABELS = {
    "eu_rate": {"it": "Con origine UE", "en": "With EU origin"},
    "normal_rate": {"it": "Senza prova di origine UE", "en": "Without proof of EU origin"},
    "vat": {"it": "IVA all'importazione", "en": "Import VAT"},
    "general_rate": {"it": "Dazio generale USA", "en": "US general duty"},
    "ceta_rate": {"it": "Con origine UE (CETA)", "en": "With EU origin (CETA)"},
    "mfn_rate": {"it": "Senza prova di origine UE (MFN)", "en": "Without proof of EU origin (MFN)"},
}
ORDER = ["eu_rate", "ceta_rate", "general_rate", "normal_rate", "mfn_rate", "vat"]

NO_EU_DUTY = {"it": "Nessun dazio doganale: il commercio tra paesi UE è esente da dazi.",
              "en": "No customs duty: trade between EU countries is duty-free."}


def for_case(con, case, **_):
    """Duties block for the Journey and the TEM workspace. None when the lane is not in Wave 1."""
    ln = requirements.lane(case["product"].get("category"), case["market"].get("country"))
    if not ln:
        return None
    p, d = ln
    if d in requirements.EU_D:
        return {"destination": d, "eu": True, "note": NO_EU_DUTY}
    lines = [l for l in tariff_watch.LINES if l[1] == d and l[2] == p]
    stored = {r["ref"]: r for r in con.execute(
        "SELECT ref, value, checked_at FROM duty_snapshots WHERE ref IN (%s)" % ",".join("?" * len(lines)),
        [l[0] for l in lines]).fetchall()} if lines else {}
    groups, read = [], []
    for ref, _, _, code, _, desc in lines:
        if ref not in stored:
            continue
        v = json.loads(stored[ref]["value"])
        read.append(stored[ref]["checked_at"])
        groups.append({"code": code, "description": {"it": tariff_watch.DESC_IT.get(ref, desc), "en": desc},
                       "lines": [{"label": LABELS[k], "value": v[k]} for k in ORDER if k in v]})
    if not groups:
        return {"destination": d, "pending": True}
    return {"destination": d, "groups": groups, "limit": LIMIT[d], "source": SOURCES[d], "retrieved_at": min(read)}
