"""Tools shown on each project: links to partner services, previews of tools in development, coming soon.

Each card states the current and the expected state of one tool:
  today    what works now (a VeriPura check, or an outside service opened in a new tab)
  coming   the expected state: "In development" (preview with example data only) or "Coming soon",
           with a "Tell me when it's ready" button

Previews describe the task and the result, never how the work is done (Thomas, 6 Nov 2026).
No rival versions of VeriPura products: label checks and document checks stay VeriPura's.
Interest clicks are recorded per case and tool, so staff see which tools users want.

Who sees what (Thomas, 6 Nov 2026):
  independent exporter (no TEM)  every card
  TEM                            every card, with a "Visible to client" switch per card and project
  client of a TEM                the cards switched on; defaults below. Off by default: what the TEM may do
                                 or arrange themselves (shipping partners, label check, finding buyers).
"""
import re
import uuid

from . import db

CHILLED = ("cheese",)  # products that may need chilled transport

L = lambda en, it: {"en": en, "it": it}

# Each card is one tool: "today" is what works now, "coming" is the expected state.
# coming.status: preview ("In development", example data only) or soon ("Coming soon").

PARCEL_LINKS = {
    "sendcloud": {"label": L("Sendcloud (parcels)", "Sendcloud (pacchi)"), "url": "https://www.sendcloud.com/"},
    "shippypro": {"label": L("ShippyPro (parcels, also chilled)", "ShippyPro (pacchi, anche refrigerati)"), "url": "https://www.shippypro.com/"},
}
CHILLED_NOTE = L("Chilled parcels suit samples and small orders only. Larger chilled volumes travel by refrigerated pallet or container.",
                 "I pacchi refrigerati vanno bene solo per campioni e piccoli ordini. Volumi refrigerati più grandi viaggiano su pallet o container refrigerati.")

CORE = [  # MioTEM's own tools: always shown (no switch for the TEM); "go" is where the button takes the user
    {"id": "ai_manager", "go": "chat", "name": L("Your agentic export assistant", "Il tuo assistente export agentico"),
     "today": {"text": L("Guides you one question at a time and builds your project: product, market, company.",
                         "Ti guida una domanda alla volta e costruisce il tuo progetto: prodotto, mercato, azienda.")}},
    {"id": "checklist", "go": "req", "name": L("Required documents", "Documenti richiesti"),
     "today": {"text": L("For your product and market, the documents you need, who prepares each one, and the official source where we have one.",
                         "Per il tuo prodotto e mercato, i documenti necessari, chi prepara ciascuno e la fonte ufficiale, quando disponibile.")}},
    {"id": "duties", "go": "duties", "name": L("Duties and taxes", "Dazi e imposte"),
     "today": {"text": L("Customs duties for your product in your destination, checked against the official tariffs.",
                         "I dazi doganali per il tuo prodotto nel paese di destinazione, verificati rispetto alle tariffe ufficiali.")}},
    {"id": "library", "go": "docs", "name": L("Document library", "Archivio documenti"),
     "today": {"text": L("All your company documents in one place, filed by project, private to your company.",
                         "Tutti i documenti dell'azienda in un unico posto, archiviati per progetto, riservati alla tua azienda.")}},
    {"id": "eori", "go": "eori", "name": L("EORI registration form", "Modulo di registrazione EORI"),
     "today": {"text": L("A prefilled draft of the official customs form: you check, sign and file it.",
                         "Una bozza precompilata del modulo ufficiale delle dogane: la controlli, la firmi e la presenti tu.")}},
    {"id": "consultants", "name": L("Export consultants (TEM)", "Consulenti export (TEM)"),
     "today": {"text": L("Work with your temporary export manager on MioTEM: they see your projects only after you engage them.",
                         "Lavora con il tuo temporary export manager su MioTEM: vede i tuoi progetti solo dopo che lo hai incaricato.")},
     "coming": {"status": "soon", "text": L("Find a TEM on MioTEM. TEMs can offer their services to exporters on MioTEM.",
                                           "Trova un TEM su MioTEM. I TEM possono offrire i propri servizi agli esportatori su MioTEM.")}},
]
for _c in CORE:
    _c["by"], _c["always"] = {"kind": "miotem"}, True

CARDS = [
    {"id": "shipping", "by": {"kind": "partner", "name": "Sendcloud, ShippyPro"},
     "name": L("Shipping", "Spedizioni"),
     "today": {"text": L("Parcels for samples and small orders, booked with these services.",
                         "Pacchi per campioni e piccoli ordini, da prenotare con questi servizi.")},
     "coming": {"status": "soon",
                "text": L("Pallets and containers: quotes, booking and container tracking for larger shipments, and shipment tracking through the freight forwarder you or your TEM engage.",
                          "Pallet e container: preventivi, prenotazione e tracciamento container per spedizioni più grandi, e tracciamento delle spedizioni tramite lo spedizioniere che incarichi tu o il tuo TEM.")}},
    {"id": "doc_checks", "by": {"kind": "partner", "name": "VeriPura"},
     "name": L("VeriPura Document Checker", "VeriPura Document Checker"),
     "coming": {"status": "preview",
                "text": L("Upload your documents in the project. For now our staff run the check: it compares the invoice, packing list and transport document with each other, "
                          "and screens ingredients against additives banned in the European Union. Also planned: the export declaration, the e-AD for wine and the US wine certificates.",
                          "Carica i documenti nel progetto. Per ora il controllo lo avvia il nostro staff: confronta fattura, packing list e documento di trasporto tra loro, "
                          "e controlla gli ingredienti rispetto agli additivi vietati nell'Unione europea. In programma anche la dichiarazione di esportazione, l'e-AD per il vino e i certificati per il vino negli USA."),
                "example": [L("Export declaration (MRN): matches invoice and packing list", "Dichiarazione di esportazione (MRN): coerente con fattura e packing list"),
                            L("e-AD: quantities match the invoice", "e-AD: quantità coerenti con la fattura")]}},
    {"id": "label_check", "by": {"kind": "partner", "name": "VeriPura"},
     "name": L("Label check, VeriPura label validator", "Verifica etichetta, validatore etichette VeriPura"),
     "today": {"text": L("Check your label artwork in the VeriPura label validator (separate VeriPura account, opens in a new tab).",
                         "Verifica la grafica dell'etichetta nel validatore etichette VeriPura (account VeriPura separato, si apre in una nuova scheda)."),
               "links": [{"label": L("VeriPura label validator", "Validatore etichette VeriPura"), "url": "https://label.veripura.com/"}]},
     "coming": {"status": "preview",
                "text": L("The result inside your project, in Italian, without a separate account.",
                          "Il risultato dentro il progetto, in italiano, senza un account separato."),
                "example": [L("Allergens: highlighted correctly", "Allergeni: evidenziati correttamente"),
                            L("Label language: matches the destination", "Lingua dell'etichetta: conforme alla destinazione"),
                            L("Missing: net quantity in the same field of vision as the name", "Manca: quantità netta nello stesso campo visivo della denominazione")]}},
    {"id": "ttb_agent", "by": {"kind": "miotem"}, "only": {"products": ("wine",), "countries": ("usa", "us", "united states")},
     "name": L("US wine certificate assistant", "Assistente certificato vino USA"),
     "coming": {"status": "preview",
                "text": L("Planned: an AI assistant will guide you through the US certificate for your wine, step by step, with you confirming each one.",
                          "In programma: un assistente AI ti guiderà nel certificato USA per il tuo vino, passo dopo passo, e tu confermerai ogni passaggio."),
                "steps": [
                    {"t": L("Is it needed?", "Serve?"),
                     "ex": L("Likely needed: your label shows a vintage year. Confirm?", "Probabilmente sì: l'etichetta riporta l'annata. Confermi?")},
                    {"t": L("How to get it", "Come ottenerlo"),
                     "ex": L("What to prepare and who issues it, filled in from your project.", "Cosa preparare e chi lo rilascia, già compilato con i dati del progetto.")},
                    {"t": L("Check the certificate", "Verifica del certificato"),
                     "ex": L("Matches your label and invoice. Confirm?", "Coerente con etichetta e fattura. Confermi?")},
                    {"t": L("Done", "Fatto"),
                     "ex": L("Confirmed by you, recorded in the project history.", "Confermato da te, registrato nella cronologia del progetto.")}]}},
    {"id": "cert_evidence", "by": {"kind": "miotem"},
     "name": L("Certification evidence", "Prove delle certificazioni"),
     "today": {"text": L("Tell us which protected name your product carries (DOP, IGP, DOCG) and which control body certifies you. "
                         "We show the body the Ministry of Agriculture (MASAF) lists for that name, with the list date. "
                         "Upload your certificate in Documents: until our staff or VeriPura CORE have seen it, the status stays claimed. "
                         "For Parmigiano Reggiano, an exporter can also check its own VAT number against the public list of OCQ PR.",
                         "Indica quale denominazione protetta ha il tuo prodotto (DOP, IGP, DOCG) e quale organismo di controllo ti certifica. "
                         "Ti mostriamo l'organismo che il Ministero dell'agricoltura (MASAF) indica per quel nome, con la data dell'elenco. "
                         "Carica il certificato in Documenti: finché il nostro staff o VeriPura CORE non lo hanno visto, lo stato resta «dichiarato». "
                         "Per il Parmigiano Reggiano l'esportatore può anche controllare la propria partita IVA nell'elenco pubblico di OCQ PR.")},
     "coming": {"status": "preview",
                "text": L("Request to the control body: with your consent, your TEM or VeriPura staff prepare a request for an extract or a verification (Valoritalia, Kiwa Cermet), send it, and file the reply in Documents.",
                          "Richiesta all'organismo di controllo: con il tuo consenso, il tuo TEM o lo staff VeriPura preparano una richiesta di estratto o di verifica (Valoritalia, Kiwa Cermet), la inviano e archiviano la risposta in Documenti.")}},
    {"id": "label_design", "by": {"kind": "partner", "name": "Food Label Maker, GoVisually"},
     "name": L("Label design", "Progettazione etichette"),
     "today": {"text": L("Create nutrition panels and labels with these partner tools. GoVisually is free, and Food Label Maker has a free trial label. Then upload the label here.",
                         "Crea tabelle nutrizionali ed etichette con questi strumenti dei partner. GoVisually è gratuito e Food Label Maker offre un'etichetta di prova gratuita. Poi carica qui l'etichetta."),
               "links": [{"label": L("Food Label Maker", "Food Label Maker"), "url": "https://foodlabelmaker.com/"},
                         {"label": L("GoVisually nutrition label generator", "Generatore di etichette nutrizionali GoVisually"),
                          "url": "https://govisually.com/free-tools/nutrition-label"}]}},
    {"id": "funding", "by": {"kind": "miotem"},
     "name": L("Funding for exporting", "Finanziamenti per l'export"),
     "today": {"text": L("Official programmes that fund export projects and temporary export managers: SIMEST loans with a grant share, "
                         "and regional and chamber of commerce calls. Calls open and close during the year, so each one is marked open, closed or check the page. "
                         "Closed calls stay listed so you can see what comes up and when.",
                         "Programmi ufficiali che finanziano progetti export e temporary export manager: finanziamenti SIMEST con quota a fondo perduto "
                         "e bandi di regioni e camere di commercio. I bandi aprono e chiudono durante l'anno, quindi ognuno è indicato come aperto, chiuso o da verificare. "
                         "I bandi chiusi restano in elenco per vedere cosa esce e quando."),
               "checked": "2026-11-08",
               "notify": "funding_calls",
               "links": [
                   {"label": L("SIMEST: Temporary Manager loan (Fondo 394)", "SIMEST: finanziamento Temporary Manager (Fondo 394)"), "status": "check",
                    "note": L("Check the circular for the current terms", "Verifica la circolare per le condizioni attuali"),
                    "url": "https://www.simest.it/app/uploads/2025/11/Circolare-8-394-2023-TM-3.11.2025.pdf"},
                   {"label": L("Emilia-Romagna: internationalisation call 2026-2027 (TEM costs eligible)", "Emilia-Romagna: bando internazionalizzazione 2026-2027 (costi TEM ammessi)"), "status": "closed",
                    "note": L("Closed 13 Mar 2026, or earlier at 300 applications. The Region may reopen it.", "Chiuso il 13 mar 2026, o prima a 300 domande. La Regione può riaprirlo."),
                    "url": "https://fesr.regione.emilia-romagna.it/opportunita/opportunita-di-finanziamento/2025/sostegno-a-progetti-di-internazionalizzazione-delle-p-m-i-e-aggregazioni-di-p-m-i-2026-2027/bando-e-modulistica/bando.pdf/@@download/file/Bando.pdf"},
                   {"label": L("Emilia-Romagna: Digital Export call (Unioncamere)", "Emilia-Romagna: bando Digital Export (Unioncamere)"), "status": "check",
                    "url": "https://www.ucer.camcom.it/internazionalizzazione-delle-imprese/news/notizie-2026/bando-digital-export-anno-2026-2027/documenti/bando-digital-export-2026-2027.pdf/@@download/file"},
                   {"label": L("Verona chamber: internationalisation call 2026", "Camera di commercio di Verona: bando internazionalizzazione 2026"), "status": "closed",
                    "note": L("Applications ran 7 to 21 Sep 2026. 40% up to 6,000 euro with a TEM. Verona province only.", "Domande dal 7 al 21 set 2026. 40% fino a 6.000 euro con un TEM. Solo provincia di Verona."),
                    "url": "https://www.vr.camcom.it/la-camera/modulistica-online/incentivi-internazionalizzazione/normativa/bando-internazionalizzazione-2026.pdf/@@display-file/file_principale"},
                   {"label": L("Modena chamber: internationalisation voucher", "Camera di commercio di Modena: voucher internazionalizzazione"), "status": "closed",
                    "note": L("Reported closed on 9 Oct 2026", "Risulta chiuso il 9 ott 2026"),
                    "url": "https://www.mo.camcom.it/amministrazione-trasparente/sovvenzioni-contributi-sussidi-vantaggi-economici/bandi/bando-voucher-internazionalizzazione-anno-2026/view"},
                   {"label": L("Lombardy: Export su misura 2026", "Lombardia: Export su misura 2026"), "status": "closed",
                    "note": L("Both 2026 windows closed. No new window announced.", "Entrambe le finestre 2026 chiuse. Nessuna nuova finestra annunciata."),
                    "url": "https://www.assolombarda.it/servizi/internazionalizzazione/informazioni/bando-export-su-misura"},
                   {"label": L("Reggio Calabria chamber: internationalisation call 2026", "Camera di commercio di Reggio Calabria: bando internazionalizzazione 2026"), "status": "closed",
                    "note": L("Closed 30 Oct 2026", "Chiuso il 30 ott 2026"),
                    "url": "https://www.rc.camcom.gov.it/bandi-e-avvisi/bando-internazionalizzazione-2026"},
                   {"label": L("Tuscany: regional open calls (look for internationalisation)", "Toscana: bandi regionali aperti (cerca internazionalizzazione)"), "status": "check",
                    "url": "https://www.regione.toscana.it/bandi-aperti"},
                   {"label": L("Alessandria-Asti chamber: export support measures (incl. OCM Vino)", "Camera di commercio di Alessandria-Asti: misure per l'export (incl. OCM Vino)"), "status": "check",
                    "url": "https://www.aa.camcom.it/sites/default/files/contenuto_redazione/editor/Internazionalizzazione_attrazione_investimenti_transizione_digitale_ed_ecologica/Brochure%20misure%20internazionalizzazione/Brochure%20misure%20internazionalizzazione%202026.pdf"}]},
     "coming": {"status": "soon",
                "text": L("Funding finder: MioTEM matches your company and project to the open calls and prepares the application from the data you already gave.",
                          "Ricerca finanziamenti: MioTEM abbina azienda e progetto ai bandi aperti e prepara la domanda con i dati che hai già fornito.")}},
    {"id": "buyer_verification", "by": {"kind": "miotem"},
     "name": L("Buyer verification page", "Pagina di verifica per l'acquirente"),
     "coming": {"status": "preview",
                "text": L("Planned: once your documents are checked, share a page and QR code that shows your buyer the documents for the shipment were checked.",
                          "In programma: una volta verificati i documenti, condividi una pagina e un codice QR che mostra all'acquirente che i documenti della spedizione sono stati verificati."),
                "example": [L("Example, not a real shipment: pasta, Italy to United Kingdom, documents checked", "Esempio, non una spedizione reale: pasta, Italia verso Regno Unito, documenti verificati")]}},
    {"id": "importers", "by": {"kind": "partner", "name": "VeriPura Connect"},
     "name": L("Researched importers", "Importatori ricercati"),
     "today": {"text": L("Browse researched importers of Italian food and wine for your destination. This list is updated regularly.",
                         "Consulta gli importatori ricercati di prodotti alimentari e vino italiani per la tua destinazione. L'elenco è aggiornato regolarmente.")},
     "no_tell": True,
     "coming": {"status": "soon",
                "text": L("Contact importers through VeriPura Connect.",
                          "Contatta gli importatori tramite VeriPura Connect.")}},
    {"id": "alerts", "by": {"kind": "miotem"},
     "name": L("Rule changes ahead", "Novità normative in arrivo"),
     "coming": {"status": "soon",
                "text": L("Notices of new food-safety rules for your product and destination, from official WTO notifications and from changes to official sources.",
                          "Avvisi sulle nuove norme di sicurezza alimentare per il tuo prodotto e la tua destinazione, dalle notifiche ufficiali WTO e dalle modifiche alle fonti ufficiali.")}},
    {"id": "mode2", "by": {"kind": "miotem"},
     "name": L("Help with a project", "Aiuto per un progetto"),
     "coming": {"status": "soon",
                "text": L("Need help with one project, not a long-term arrangement? Soon you will be able to find temporary export managers who offer their services on MioTEM and hire one for a defined project. Prices and payment: to be decided.",
                          "Hai bisogno di aiuto per un solo progetto, non per un rapporto continuativo? Presto potrai trovare temporary export manager che offrono i loro servizi su MioTEM, incaricarne uno per un progetto definito. Prezzi e pagamento: da definire.")}},
]
TOOL_IDS = {c["id"] for c in CORE + CARDS} | {"refcheck"}
STEP = {"label_check": 2, "label_design": 2, "ttb_agent": 3, "shipping": 4}  # the checklist step where the tool helps (1 Company, 2 Product, 3 Destination, 4 Shipment)
INTEREST_ONLY = {"funding_calls"}  # interest buttons that are not a card of their own (new funding calls)
CLIENT_OFF = {"shipping", "label_check", "importers"}  # hidden from a TEM's client unless the TEM switches them on


def _norm(s):
    return (s or "").strip().lower()


def for_case(product_category, country):
    """The tool cards for one project, in display order (deep copies, safe to annotate)."""
    import copy
    p, k = _norm(product_category), _norm(country)
    out = []
    for c in CORE + CARDS:
        only = c.get("only")
        if only and not (p in only["products"] and k in only["countries"]):
            continue
        card = copy.deepcopy({kk: v for kk, v in c.items() if kk != "only"})
        if c["id"] in STEP:
            card["step"] = STEP[c["id"]]
        if card["id"] == "shipping":
            order = ["shippypro", "sendcloud"] if p in CHILLED else ["sendcloud", "shippypro"]
            card["today"]["links"] = [PARCEL_LINKS[x] for x in order]
            if p in CHILLED:
                card["today"]["note"] = CHILLED_NOTE
        out.append(card)
    return sorted(out, key=lambda c: c["by"]["kind"] != "miotem")  # MioTEM first, then partners; stable within each


PUBLIC_TEXT = {  # shorter wording for the public page (no link details, no partner names beyond the approved label validator)
    "shipping": L("Parcels for samples and small orders, booked with partner services. Next: pallets and containers.",
                  "Pacchi per campioni e piccoli ordini, prenotabili con servizi partner. Poi: pallet e container."),
    "label_check": L("Check your label artwork in the VeriPura label validator. Next: the result inside your project, in Italian.",
                     "Verifica la grafica dell'etichetta nel validatore etichette VeriPura. Poi: il risultato dentro il progetto, in italiano."),
    "label_design": L("Create nutrition panels and labels with partner tools, then upload the label in your project.",
                      "Crea tabelle nutrizionali ed etichette con strumenti dei partner, poi carica l'etichetta nel progetto."),
    "importers": L("Researched importers of Italian food and wine, by destination. The list is updated regularly.",
                   "Importatori ricercati di prodotti alimentari e vino italiani, per destinazione. L'elenco è aggiornato regolarmente."),
}


def public_catalog():
    """The tool list for the public landing page: every tool, live or planned, with no partner names and no user data."""
    out = []
    for c in CORE + CARDS:
        today, coming = c.get("today"), c.get("coming")
        status = "live" if today else ("preview" if coming and coming["status"] == "preview" else "soon")
        text = {}
        for lg in ("en", "it"):
            parts = [today["text"][lg]] if today else []
            if coming and (not today or coming["status"] != "soon" or c["id"] in ("shipping", "consultants", "label_check")):
                parts.append(("Poi: " if lg == "it" else "Next: ") + coming["text"][lg] if today else coming["text"][lg])
            text[lg] = " ".join(parts)
        out.append({"id": c["id"], "name": c["name"], "by": c["by"]["kind"], "status": status, "text": PUBLIC_TEXT.get(c["id"], text)})
    order = {"live": 0, "preview": 1, "soon": 2}
    return sorted(out, key=lambda x: order[x["status"]])  # stable: MioTEM tools stay ahead of partner tools within a status


def ai_guide():
    """The tool list for the AI's fixed prompt (cached): what each tool does today, what is next, and where it is."""
    lines = ["MioTEM TOOLS. When the client asks what MioTEM can do, about a tool, or how to use one, answer briefly from this list "
             "(say which are MioTEM's own and which come from partners, and say plainly what is not ready yet). "
             "To offer a button that takes the client to a tool, end your message with one last line "
             "'GOTO: <key>' where key is one of chat, req, duties, docs, eori, tools. "
             "Never describe how a tool works inside, only what it does for the client."]
    for c in CORE + CARDS:
        by = "MioTEM" if c["by"]["kind"] == "miotem" else ("partner " + c["by"]["name"]).strip()
        where = {"chat": "this chat", "req": "Services, required documents (GOTO: req)", "duties": "Services, duties (GOTO: duties)",
                 "docs": "the Documents button (GOTO: docs)", "eori": "Services, EORI form (GOTO: eori)"}.get(c.get("go"), "Services, tools for this project (GOTO: tools)")
        only = " Only for wine to the United States." if c.get("only") else ""
        today = (" Today: " + c["today"]["text"]["en"]) if c.get("today") else " Not available yet."
        nxt = (" Next (" + ("in development" if c["coming"]["status"] == "preview" else "coming soon") + "): " + c["coming"]["text"]["en"]) if c.get("coming") else ""
        lines.append("- " + c["name"]["en"] + " [" + by + "]." + today + nxt + only + " Where: " + where + ".")
    lines.append("- Check an export reference [MioTEM]. Today: checks the format of an MRN or an ARC. Where: Services, tools for this project (GOTO: tools).")
    return "\n".join(lines)


# ---- who sees what

def has_tem(con, company_id):
    return bool(company_id) and con.execute(
        "SELECT 1 FROM tem_clients WHERE company_id=? AND status='active'", (company_id,)).fetchone() is not None


def _visibility(con, case_id):
    v = {t: t not in CLIENT_OFF for t in TOOL_IDS}
    for r in con.execute("SELECT tool, visible FROM tool_visibility WHERE case_id=?", (case_id,)).fetchall():
        v[r["tool"]] = bool(r["visible"])
    return v


def for_viewer(con, case_row, category, country, viewer):
    """viewer: exporter, tem or client. Returns {"cards": [...], "refcheck": bool}, with client_visible flags for the TEM."""
    cards = for_case(category, country)
    if viewer == "exporter":
        return {"cards": cards, "refcheck": True}
    vis = _visibility(con, case_row["id"])
    if viewer == "tem":
        for c in cards:
            c["client_visible"] = True if c.get("always") else vis[c["id"]]
        shown = sum(1 for c in cards if c["client_visible"]) + (1 if vis["refcheck"] else 0)
        return {"cards": cards, "refcheck": True, "refcheck_client_visible": vis["refcheck"],
                "client_count": {"shown": shown, "total": len(cards) + 1}}
    return {"cards": [c for c in cards if c.get("always") or vis[c["id"]]], "refcheck": vis["refcheck"]}


def set_visibility(con, who, case_id, tool, visible):
    from . import tems
    row = tems._case_tem(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    if tool not in TOOL_IDS or tool in {c["id"] for c in CORE}:
        return 400, {"error": "unknown tool"}
    con.execute("DELETE FROM tool_visibility WHERE case_id=? AND tool=?", (case_id, tool))
    con.execute("INSERT INTO tool_visibility(case_id, tool, visible, set_by, set_at) VALUES (?,?,?,?,?)",
                (case_id, tool, 1 if visible else 0, who["user"], db.now()))
    con.commit()
    tems.log_access(con, who, row, ("show_tool:" if visible else "hide_tool:") + tool)
    return 200, {"ok": True}


# ---- interest ("Tell me when it's ready")

def user_type(con, company_id, user_sub):
    from . import tems
    if tems.firm_of(con, user_sub):
        return "tem"
    return "client" if has_tem(con, company_id) else "exporter"


def record_interest(con, case_id, user_sub, tool):
    if tool not in TOOL_IDS and tool not in INTEREST_ONLY:
        return 400, {"error": "unknown tool"}
    company = None
    if case_id:
        r = con.execute("SELECT company_id FROM cases WHERE id=?", (case_id,)).fetchone()
        company = r["company_id"] if r else None
    utype = user_type(con, company, user_sub)
    have = con.execute("SELECT id FROM tool_interest WHERE tool=? AND user_sub=? AND COALESCE(case_id,'')=?",
                       (tool, user_sub, case_id or "")).fetchone()
    if not have:
        con.execute("INSERT INTO tool_interest(id, case_id, company_id, user_sub, tool, user_type, created_at) VALUES (?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), case_id, company, user_sub, tool, utype, db.now()))
        con.commit()
        db.log_event(con, case_id, user_sub, "tool_interest", {"tool": tool, "user_type": utype})
    return 200, {"ok": True}


def interest_listing(con):
    rows = [dict(r) for r in con.execute(
        "SELECT t.tool, t.user_type, t.created_at, co.legal_name AS company FROM tool_interest t LEFT JOIN companies co ON co.id=t.company_id "
        "ORDER BY t.created_at DESC LIMIT 300").fetchall()]
    counts, types = {}, {}
    for r in rows:
        counts[r["tool"]] = counts.get(r["tool"], 0) + 1
        types[r["user_type"] or "?"] = types.get(r["user_type"] or "?", 0) + 1
    return {"total": len(rows), "by_tool": [{"tool": k, "n": n} for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))],
            "by_user_type": [{"type": k, "n": n} for k, n in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))],
            "latest": rows[:50]}


# ---- export references: format only. Whether the declaration or movement exists is confirmed in the official systems.

MRN_RE = re.compile(r"^\d{2}[A-Z]{2}[A-Z0-9]{13}[0-9A-Z]$")      # 18 characters: year, country, identifier, check character
ARC_RE = re.compile(r"^\d{2}[A-Z]{2}[A-Z0-9]{16}\d$")             # 21 characters: year, country, identifier, check digit
MRN_LOOKUP = "https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/mrn-follow_en"


def check_reference(kind, value):
    v = re.sub(r"\s+", "", str(value or "")).upper()
    if kind == "mrn":
        ok = bool(MRN_RE.match(v))
        return {"kind": "mrn", "value": v, "format_ok": ok, "lookup": MRN_LOOKUP,
                "message": L("Format correct (18 characters). Confirm the declaration in the EU MRN follow-up service." if ok else
                             "This does not look like an MRN: it has 18 characters, starting with the year and the country code (e.g. 26IT...).",
                             "Formato corretto (18 caratteri). Conferma la dichiarazione nel servizio UE di verifica MRN." if ok else
                             "Non sembra un MRN: ha 18 caratteri e inizia con l'anno e il codice paese (es. 26IT...).")}
    if kind == "arc":
        ok = bool(ARC_RE.match(v))
        return {"kind": "arc", "value": v, "format_ok": ok, "lookup": None,
                "message": L("Format correct (21 characters). The movement's status is shown in your EMCS account or by your customs agent." if ok else
                             "This does not look like an ARC: it has 21 characters, starting with the year and the country code (e.g. 26IT...).",
                             "Formato corretto (21 caratteri). Lo stato del movimento è visibile nel tuo account EMCS o tramite il tuo spedizioniere doganale." if ok else
                             "Non sembra un ARC: ha 21 caratteri e inizia con l'anno e il codice paese (es. 26IT...).")}
    return {"error": "unknown kind"}
