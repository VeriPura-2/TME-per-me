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
    if co.get("address_region"):
        out["address"] = co["address_region"]
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
            "links": LINKS, "note": NOTE[lang]}


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
