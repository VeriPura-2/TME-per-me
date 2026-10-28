"""SIMULATED required-documents checklist. Draft content from the VeriPura master
checklist, not verified against official sources and not specific to a destination.
Delete this file when CORE offers a required-documents call per product and market,
and set "required_docs" to live. The match against uploaded documents is real."""
from . import tag

# (id, it, en, layer, matching doc type in docs.TYPES or None)
BASE = [
    ("registration", "Visura camerale / registrazione", "Company registration", 1, "company_registration"),
    ("tax_ids", "Partita IVA ed EORI", "VAT and EORI", 1, "tax_ids"),
    ("facility", "Registrazione o autorizzazione dello stabilimento", "Food business registration or approval", 1, "facility_approval"),
    ("haccp", "Piano HACCP", "HACCP food safety plan", 1, "facility_approval"),
    ("insurance", "Assicurazione", "Insurance", 1, "insurance"),
    ("spec", "Scheda tecnica del prodotto", "Product specification", 2, "spec_sheet"),
    ("label", "Etichetta (grafica approvata)", "Label artwork", 2, "label"),
    ("lab", "Analisi di laboratorio", "Lab analysis", 2, "lab_analysis"),
    ("certs", "Certificazioni (se dichiarate)", "Certificates (if claimed)", 2, "certificate"),
    ("origin_proof", "Prova di origine, se richiesta", "Origin proof, if requested", 3, "origin"),
    ("importer_contract", "Accordo con l'importatore", "Importer agreement", 3, "contract"),
    ("invoice", "Fattura commerciale", "Commercial invoice", 4, "invoice"),
    ("packing", "Packing list", "Packing list", 4, "packing_list"),
    ("transport", "Documento di trasporto", "Transport document", 4, "transport"),
    ("customs", "Dichiarazione doganale di esportazione", "Export customs declaration", 4, "customs"),
]
EXTRA = {
    "wine": [("wine_doc", "Documento di accompagnamento e analisi del vino", "Wine accompanying document and analysis", 3, None),
             ("excise", "Documenti accise", "Excise documents", 3, None)],
    "spirits": [("excise", "Documenti accise", "Excise documents", 3, None)],
    "cured meat": [("vet_cert", "Certificato sanitario ufficiale", "Official health certificate", 3, None),
                   ("est_listing", "Stabilimento abilitato al paese di destinazione", "Establishment eligible for the destination", 3, None)],
    "cheese and dairy": [("vet_cert", "Certificato sanitario ufficiale", "Official health certificate", 3, None)],
    "pasta": [], "olive oil": [("oil_analysis", "Analisi dell'olio (acidità, perossidi)", "Oil analysis (acidity, peroxides)", 2, None)],
    "preserves": [("process", "Convalida del trattamento termico", "Thermal process validation", 2, None)],
    "bakery": [],
}
LAYERS = {1: {"it": "Azienda", "en": "Company"}, 2: {"it": "Prodotto", "en": "Product"},
          3: {"it": "Mercato", "en": "Destination"}, 4: {"it": "Spedizione", "en": "Shipment"}}


def required(category, on_file_types):
    """on_file_types: set of docs.TYPES ids the client already has. Real match, simulated list."""
    rows = []
    for tid, it, en, layer, dtype in BASE + EXTRA.get((category or "").lower(), []):
        rows.append({"id": tid, "it": it, "en": en, "layer": layer,
                     "on_file": bool(dtype and dtype in on_file_types)})
    return tag("required_docs", {"layers": LAYERS, "items": rows,
                                 "caveat": {"it": "Bozza dalla checklist VeriPura. Non verificata sulle fonti ufficiali e non specifica per il paese.",
                                            "en": "Draft from the VeriPura checklist. Not verified against official sources and not specific to the country."}})
