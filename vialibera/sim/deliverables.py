"""SIMULATED sample deliverables. Generic samples, never results about the client's product.
Delete when real deliverables are produced; set "deliverables" to live."""
from . import tag

SAMPLES = {
    "tariff_lookup": ({"it": "Esempio: scheda dazi per un prodotto e un paese, con aliquota, IVA, eventuali quote e fonte ufficiale.",
                       "en": "Example: a duty sheet for one product and country, with rate, VAT, any quota and the official source."}),
    "document_check": ({"it": "Esempio: esito del controllo di un documento con campi letti, citazione della pagina e segnalazioni.",
                        "en": "Example: result of a document check with fields read, page citation and alerts."}),
    "label_check": ({"it": "Esempio: elenco di punti dell'etichetta da correggere per il mercato.",
                     "en": "Example: list of label points to fix for the market."}),
    "export_documents": ({"it": "Esempio: bozza di fattura e packing list dalla scheda pratica.",
                          "en": "Example: draft invoice and packing list from the case file."}),
}
DEFAULT = {"it": "Esempio di consegna: un fascicolo con i risultati e le fonti.", "en": "Example deliverable: a file with results and sources."}


def sample(items):
    return tag("deliverables", [{"item": i, "sample": SAMPLES.get(i, DEFAULT)} for i in items])
