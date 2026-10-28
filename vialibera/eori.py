"""EORI application: prefill the official ADM form from what we hold, the person checks and confirms.

DRAFT. The form is ADM's "Richiesta di attribuzione del codice EORI". It is filed, signed, with the
customs office the person chooses (the form header reads "All'Ufficio delle Dogane di ..."). We never
file, tick the consent boxes, date or sign. Remove/replace once VeriPura confirms the route with ADM.
"""
import io
import os
import re

FORM = os.path.join(os.path.dirname(__file__), "static", "forms", "eori_it.pdf")
LINKS = {
    "form_page": "https://www.adm.gov.it/portale/dogane/operatore/ecustoms-aida/progetti-aida/eos",
    "check": "https://ec.europa.eu/taxation_customs/dds2/eos/eori_validation.jsp",
}
NOTE = {
    "it": "Bozza. Controlla ogni dato, scarica il modulo, firmalo e consegnalo all'Ufficio delle Dogane che scegli. Via Libera non lo presenta e non lo firma.",
    "en": "Draft. Check every field, download the form, sign it and file it with the customs office you choose. Via Libera does not file or sign it.",
}
# key, label it, label en, page, baseline y (top-down), required
FIELDS = [
    ("office", "Ufficio delle Dogane di (città)", "Customs office (city)", 1, 72, True),
    ("country", "Paese della sede legale (codice e nome)", "Country of registered office (code and name)", 1, 220, True),
    ("piva", "Partita IVA", "VAT number (partita IVA)", 1, 247, True),
    ("cf", "Codice fiscale", "Tax code (codice fiscale)", 1, 279, True),
    ("name", "Ragione sociale", "Company name", 1, 475, True),
    ("founded", "Data di costituzione (GG/MM/AAAA)", "Date of incorporation (DD/MM/YYYY)", 1, 663, True),
    ("city", "Città della sede legale", "City of registered office", 1, 697, True),
    ("province", "Provincia (sigla)", "Province (2 letters)", 1, 724, True),
    ("address", "Indirizzo della sede legale", "Registered address", 1, 753, True),
    ("cap", "CAP", "Postcode", 2, 43, True),
    ("legal_form", "Qualità del richiedente", "Applicant type", 2, None, True),
    ("nace", "Attività economica (codice NACE e descrizione)", "Economic activity (NACE code and description)", 2, 184, True),
    ("c_surname", "Contatto: cognome", "Contact: surname", 2, 483, True),
    ("c_name", "Contatto: nome", "Contact: first name", 2, 514, True),
    ("c_country", "Contatto: paese", "Contact: country", 2, 541, False),
    ("c_city", "Contatto: città", "Contact: city", 2, 577, False),
    ("c_address", "Contatto: indirizzo", "Contact: address", 2, 608, False),
    ("c_cap", "Contatto: CAP", "Contact: postcode", 2, 639, False),
    ("c_phone", "Contatto: telefono", "Contact: phone", 2, 670, False),
    ("c_email", "Contatto: email", "Contact: email", 2, 733, True),
    ("doc_type", "Documento: tipo", "Document: type", 3, 104, True),
    ("doc_ref", "Documento: estremi (numero REA o data)", "Document: details (REA number or date)", 3, 150, True),
    ("doc_country", "Documento: paese di rilascio", "Document: issuing country", 3, 181, True),
]
LEGAL_FORMS = {"person": (424, 77), "company": (424, 115), "association": (424, 149)}
X = 275


def _digits(v):
    return re.sub(r"\D", "", v or "")


def split_address(text):
    """Best-effort split of an Italian address like 'Via Roma 1, 12051 Alba (CN)' into street, cap, city, province.
    Anything we cannot place stays in street so nothing is lost; the person checks the result."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    out = {}
    m = re.search(r"\b(\d{5})\b", t)
    prov = re.search(r"[(\[,\s-]\s*([A-Za-z]{2})\s*[)\]]?\s*$", t)
    if prov and prov.group(1).isupper():
        out["province"] = prov.group(1)
        t = t[:prov.start()].rstrip(" ,-([")
    if m:
        out["cap"] = m.group(1)
        before, after = t[:m.start()].strip(" ,-"), t[m.end():].strip(" ,-")
        if after:
            out["city"] = after
        out["address"] = before
        if not before and after:
            out.pop("address")
    else:
        parts = [x.strip() for x in t.split(",") if x.strip()]
        if len(parts) >= 2:
            out["city"], out["address"] = parts[-1], ", ".join(parts[:-1])
        else:
            out["address"] = t
    return {k: v for k, v in out.items() if v}


def prefill(case, saved=None):
    """Values we can offer from the case, then anything the person already confirmed."""
    co = case.get("company", {}) if case else {}
    out = {"country": "IT Italia", "c_country": "IT Italia", "doc_country": "IT Italia",
           "doc_type": "Certificato camerale (visura)"}
    if co.get("legal_name"):
        out["name"] = co["legal_name"]
    d = _digits(co.get("vat_number"))
    if len(d) == 11:
        out["piva"] = d
    out.update(split_address(co.get("address_region")))
    if out.get("city"):
        out["c_city"] = out["city"]
    if out.get("address"):
        out["c_address"] = out["address"]
    if out.get("cap"):
        out["c_cap"] = out["cap"]
    contact = co.get("contact") or ""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", contact)
    if m:
        out["c_email"] = m.group(0)
    m = re.search(r"\+?\d[\d ./-]{6,}\d", contact)
    if m:
        out["c_phone"] = m.group(0).strip()
    nm = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+|\+?\d[\d ./-]{6,}\d", "", contact).strip(" ,;")
    parts = nm.split()
    if len(parts) >= 2:
        out["c_name"], out["c_surname"] = parts[0], " ".join(parts[1:])
    for k, v in (saved or {}).items():
        if v:
            out[k] = v
    return out


def saved_values(case):
    co = case.get("company", {}) if case else {}
    return {k[len("eori_"):]: v for k, v in co.items() if k.startswith("eori_")}


def describe(case, lang):
    vals = prefill(case, saved_values(case))
    fields = [{"key": k, "label": it if lang == "it" else en, "value": vals.get(k, ""), "required": req}
              for k, it, en, _p, _y, req in FIELDS]
    return {"fields": fields, "legal_form": vals.get("legal_form", ""),
            "legal_forms": [{"id": "company", "label": "Persona giuridica" if lang == "it" else "Legal entity (company)"},
                            {"id": "person", "label": "Persona fisica" if lang == "it" else "Natural person (sole trader)"},
                            {"id": "association", "label": "Associazione di persone" if lang == "it" else "Association of persons"}],
            "missing": [f["key"] for f in fields if f["required"] and not f["value"]] + ([] if vals.get("legal_form") else ["legal_form"]),
            "links": LINKS, "note": NOTE[lang], "vat_note": VAT_NOTE[lang], "excise": excise((case or {}).get("product", {}).get("category"), lang)}


def _latin(s):
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def fill(values):
    """Return PDF bytes of the ADM form with values written in. Nothing is ticked except the applicant type."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    rd = PdfReader(FORM)
    pages = {1: [], 2: [], 3: []}
    for k, _it, _en, pg, y, _r in FIELDS:
        v = _latin(str(values.get(k) or "").strip())
        if v and y:
            pages[pg].append((X if k != "office" else 380, y, v[:70]))
    wr = PdfWriter()
    for i, page in enumerate(rd.pages, 1):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(float(page.mediabox.width), float(page.mediabox.height)))
        H = float(page.mediabox.height)
        c.setFont("Helvetica", 9)
        for x, y, v in pages.get(i, []):
            c.drawString(x, H - y, v)
        if i == 2 and values.get("legal_form") in LEGAL_FORMS:
            bx, by = LEGAL_FORMS[values["legal_form"]]
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(bx, H - by - 4, "X")
        if i == 1:
            c.setFont("Helvetica", 6.5)
            c.setFillGray(0.45)
            c.drawString(45, 24, "Precompilato da Via Libera (bozza). Verificare i dati prima di firmare. Consenso, data e firma a cura del richiedente.")
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])
        wr.add_page(page)
    out = io.BytesIO()
    wr.write(out)
    return out.getvalue()


VAT_NOTE = {
    "it": "IVA sulle esportazioni (tutti i prodotti): se il trasporto fuori UE è a carico del cliente estero (per esempio EXW, FCA), la merce deve uscire dalla UE entro 90 giorni dalla consegna, altrimenti si deve applicare l'IVA e scatta una sanzione del 50 per cento dell'imposta. Si può regolarizzare entro i 30 giorni successivi (art. 8 DPR 633/1972, art. 7 D.Lgs. 471/1997). Fonte: guida della Camera di commercio di Torino, da verificare con il tuo commercialista.",
    "en": "VAT on exports (all products): if the foreign buyer arranges transport outside the EU (for example EXW, FCA), the goods must leave the EU within 90 days of delivery, otherwise Italian VAT applies and a penalty of 50 percent of the tax follows. It can be regularised in the following 30 days (art. 8 DPR 633/1972, art. 7 D.Lgs. 471/1997). Source: Turin Chamber of Commerce guide, to be confirmed with your accountant.",
}

# ---- excise guidance (DRAFT). Main source: Camera di commercio di Torino guide "Vendere vino e bevande alcoliche
# in Italia e all'estero" (updated June 2025, quotes D.Lgs. 504/1995). Also EU pages on excise and EMCS.
# ADM's own pages could not be opened by us, so each point is to be confirmed with the customs office.
EXCISE_SOURCES = [
    {"label": "Camera di commercio di Torino: guida fiscale e doganale per vino e alcolici (giugno 2025)", "url": "https://www.to.camcom.it/book/export/html/17204"},
    {"label": "Your Europe: paying excise duties", "url": "https://europa.eu/youreurope/business/taxation/excise-duties-eu/paying-excise-duties/"},
    {"label": "Commissione UE: EMCS e e-AD", "url": "https://taxation-customs.ec.europa.eu/taxation/excise-duties/emcs_en"},
    {"label": "Access2Markets: excise duties and My Trade Assistant", "url": "https://trade.ec.europa.eu/access-to-markets/en/my-trade-assistant"},
    {"label": "ADM: FAQ accise", "url": "https://www.adm.gov.it/portale/en/-/faq-le-risposte-alle-domande-piu-frequenti-in-materia-di-accise"},
]
_HOW = {"it": "Licenza (deposito fiscale): denuncia all'Ufficio delle Dogane competente, verifica dell'impianto, poi istanza in bollo e diritto annuale (103,29 euro per un deposito di vino, 258,23 euro per altre bevande alcoliche). Non abbiamo trovato un modulo scaricabile ADM.",
        "en": "Licence (tax warehouse): a denuncia to the competent customs office, an inspection of the premises, then an application on stamped paper and an annual fee (EUR 103.29 for a wine warehouse, EUR 258.23 for other alcoholic drinks). We found no downloadable ADM form."}
EXCISE = {
    "wine": {
        "it": ["Il vino ha accisa a aliquota zero in Italia ma resta un prodotto soggetto ad accisa.",
               "Piccolo produttore (media annua sotto i 1.000 hl nelle ultime tre campagne viticole consecutive): niente deposito fiscale, codice d'accisa e cauzione finché l'aliquota è zero (art. 37 D.Lgs. 504/1995). Servono comunque registro di cantina telematico, documento di accompagnamento e controlli.",
               "Il piccolo produttore non può fare vini liquorosi o aromatizzati (vermouth, mistelle): sono prodotti intermedi e richiedono un deposito fiscale.",
               "Sopra i 1.000 hl, o con prodotti intermedi, serve un deposito fiscale con licenza e codice d'accisa.",
               "Export fuori UE, uscita da una dogana italiana: dichiarazione di esportazione (di solito tramite spedizioniere doganale), fattura senza IVA con la dicitura dell'art. 8 DPR 633/1972 e prova di uscita (MRN, cassetto doganale). Documenti di trasporto interni (DDT).",
               "Export fuori UE, uscita da una dogana di un altro Paese UE: il piccolo produttore emette l'MVV-E, il deposito fiscale l'e-AD, entrambi sulla dogana di esportazione.",
               _HOW["it"]],
        "en": ["Wine has a zero excise rate in Italy but is still an excise product.",
               "Small producer (average output under 1,000 hl over the last three consecutive wine campaigns): no tax warehouse, excise code or guarantee while the rate is zero (art. 37 D.Lgs. 504/1995). You still need the electronic cellar register, an accompanying document and to accept controls.",
               "A small producer cannot make fortified or aromatised wines (vermouth, mistelle): they are intermediate products and need a tax warehouse.",
               "Above 1,000 hl, or with intermediate products, you need a tax warehouse with a licence and excise code.",
               "Export outside the EU, leaving through an Italian customs office: export declaration (usually through a customs broker), invoice without VAT with the art. 8 DPR 633/1972 wording, and proof of exit (MRN, customs drawer). Ordinary domestic transport documents (DDT).",
               "Export outside the EU, leaving through another EU country's customs office: the small producer issues an MVV-E, a tax warehouse issues an e-AD, both addressed to the export customs office.",
               _HOW["en"]],
    },
    "spirits": {
        "it": ["Per produrre o detenere alcol e bevande spiritose in sospensione d'accisa serve un deposito fiscale con licenza e codice d'accisa. Il regime del piccolo produttore vale solo per il vino.",
               "Export fuori UE: la vendita in sospensione d'accisa comporta l'e-AD, emesso sulla dogana di esportazione se la merce esce da un altro Paese UE; con uscita da una dogana italiana valgono i documenti di circolazione interna.",
               "Dichiarazione di esportazione e prova di uscita come per il vino; l'uscita conferma la fine della sospensione e libera la cauzione.",
               _HOW["it"]],
        "en": ["To produce or hold alcohol and spirits under excise suspension you need a tax warehouse with a licence and an excise code. The small-producer regime applies only to wine.",
               "Export outside the EU: a sale under excise suspension requires an e-AD, addressed to the export customs office if the goods leave through another EU country; leaving through an Italian customs office, ordinary domestic documents apply.",
               "Export declaration and proof of exit work as for wine; exit ends the suspension and releases the guarantee.",
               _HOW["en"]],
    },
}


def excise(category, lang):
    c = EXCISE.get((category or "").strip().lower())
    if not c:
        return None
    return {"points": c[lang], "sources": EXCISE_SOURCES}
