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
    {"id": "ai_manager", "go": "chat", "name": L("Your AI export manager", "Il tuo export manager AI"),
     "today": {"text": L("Guides you one question at a time and builds your project: product, market, company.",
                         "Ti guida una domanda alla volta e costruisce il tuo progetto: prodotto, mercato, azienda.")}},
    {"id": "checklist", "go": "req", "name": L("Required documents", "Documenti richiesti"),
     "today": {"text": L("For your product and market, the documents you need, who prepares each one, and the official source.",
                         "Per il tuo prodotto e mercato, i documenti necessari, chi prepara ciascuno e la fonte ufficiale.")}},
    {"id": "duties", "go": "duties", "name": L("Duties and taxes", "Dazi e imposte"),
     "today": {"text": L("Customs duties for your product in your destination, from the official tariffs, checked every week.",
                         "I dazi doganali per il tuo prodotto nel paese di destinazione, dalle tariffe ufficiali, controllati ogni settimana.")}},
    {"id": "library", "go": "docs", "name": L("Document library", "Archivio documenti"),
     "today": {"text": L("All your company documents in one place, filed by project, private to your company.",
                         "Tutti i documenti dell'azienda in un unico posto, archiviati per progetto, riservati alla tua azienda.")}},
    {"id": "eori", "go": "eori", "name": L("EORI registration form", "Modulo di registrazione EORI"),
     "today": {"text": L("The official customs form, prefilled with your company data, ready to sign.",
                         "Il modulo ufficiale delle dogane, precompilato con i dati della tua azienda, pronto da firmare.")}},
    {"id": "consultants", "name": L("Export consultants (TEM)", "Consulenti export (TEM)"),
     "today": {"text": L("Work with your temporary export manager on MioTEM: they see your projects only after you engage them.",
                         "Lavora con il tuo temporary export manager su MioTEM: vede i tuoi progetti solo dopo che lo hai incaricato.")},
     "coming": {"status": "soon", "text": L("Find a TEM on MioTEM.", "Trova un TEM su MioTEM.")}},
]
for _c in CORE:
    _c["by"], _c["always"] = {"kind": "miotem"}, True

CARDS = [
    {"id": "shipping", "by": {"kind": "partner", "name": "Sendcloud, ShippyPro"},
     "name": L("Shipping", "Spedizioni"),
     "today": {"text": L("Parcels for samples and small orders, booked with these services.",
                         "Pacchi per campioni e piccoli ordini, da prenotare con questi servizi.")},
     "coming": {"status": "soon",
                "text": L("Pallets and containers: quotes, booking and container tracking for larger shipments.",
                          "Pallet e container: preventivi, prenotazione e tracciamento container per spedizioni più grandi.")}},
    {"id": "doc_checks", "by": {"kind": "partner", "name": "VeriPura"},
     "name": L("Document checks, VeriPura Core", "Verifiche documentali, VeriPura Core"),
     "today": {"text": L("Upload your documents in the project. VeriPura Core checks the invoice, packing list and transport document against each other, "
                         "and your product specification sheet (ingredients, additives) and packaging specification against what your destination bans or restricts.",
                         "Carica i documenti nel progetto. VeriPura Core confronta fattura, packing list e documento di trasporto tra loro, "
                         "e verifica la scheda tecnica del prodotto (ingredienti, additivi) e la specifica dell'imballaggio rispetto a ciò che la destinazione vieta o limita.")},
     "coming": {"status": "preview",
                "text": L("Also the export declaration, the e-AD for wine and the US wine certificates.",
                          "Anche la dichiarazione di esportazione, l'e-AD per il vino e i certificati per il vino negli USA."),
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
                "text": L("An AI agent takes care of the US certificate for your wine and asks you to confirm each step.",
                          "Un agente AI si occupa del certificato USA per il tuo vino e ti chiede di confermare ogni passaggio."),
                "steps": [
                    {"t": L("Is it needed?", "Serve?"),
                     "ex": L("Likely needed: your label shows a vintage year. Confirm?", "Probabilmente sì: l'etichetta riporta l'annata. Confermi?")},
                    {"t": L("How to get it", "Come ottenerlo"),
                     "ex": L("What to prepare and who issues it, filled in from your project.", "Cosa preparare e chi lo rilascia, già compilato con i dati del progetto.")},
                    {"t": L("Check the certificate", "Verifica del certificato"),
                     "ex": L("Matches your label and invoice. Confirm?", "Coerente con etichetta e fattura. Confermi?")},
                    {"t": L("Done", "Fatto"),
                     "ex": L("Confirmed by you, recorded in the project history.", "Confermato da te, registrato nella cronologia del progetto.")}]}},
    {"id": "label_design", "by": {"kind": "partner", "name": "Food Label Maker, GoVisually"},
     "name": L("Label design", "Progettazione etichette"),
     "today": {"text": L("Create nutrition panels and labels for your destination market with these free tools, then upload the label here.",
                         "Crea tabelle nutrizionali ed etichette per il mercato di destinazione con questi strumenti gratuiti, poi carica qui l'etichetta."),
               "links": [{"label": L("Food Label Maker", "Food Label Maker"), "url": "https://foodlabelmaker.com/"},
                         {"label": L("GoVisually nutrition label generator", "Generatore di etichette nutrizionali GoVisually"),
                          "url": "https://govisually.com/free-tools/nutrition-label"}]}},
    {"id": "funding", "by": {"kind": "miotem"},
     "name": L("Funding for exporting", "Finanziamenti per l'export"),
     "today": {"text": L("Official programmes that fund export projects and temporary export managers: SIMEST loans with a grant share, "
                         "and chamber of commerce and regional vouchers. Calls open and close during the year: check the dates on each page.",
                         "Programmi ufficiali che finanziano progetti export e temporary export manager: finanziamenti SIMEST con quota a fondo perduto "
                         "e voucher di camere di commercio e regioni. I bandi aprono e chiudono durante l'anno: verifica le date su ogni pagina."),
               "links": [{"label": L("SIMEST: Temporary Manager loan (Fondo 394)", "SIMEST: finanziamento Temporary Manager (Fondo 394)"),
                          "url": "https://www.simest.it/app/uploads/2025/11/Circolare-8-394-2023-TM-3.11.2025.pdf"},
                         {"label": L("Emilia-Romagna: Digital Export call (Unioncamere)", "Emilia-Romagna: bando Digital Export (Unioncamere)"),
                          "url": "https://www.ucer.camcom.it/internazionalizzazione-delle-imprese/news/notizie-2026/bando-digital-export-anno-2026-2027/documenti/bando-digital-export-2026-2027.pdf/@@download/file"},
                         {"label": L("Modena chamber: internationalisation voucher", "Camera di commercio di Modena: voucher internazionalizzazione"),
                          "url": "https://www.mo.camcom.it/amministrazione-trasparente/sovvenzioni-contributi-sussidi-vantaggi-economici/bandi/bando-voucher-internazionalizzazione-anno-2026/view"},
                         {"label": L("Verona chamber: internationalisation call", "Camera di commercio di Verona: bando internazionalizzazione"),
                          "url": "https://www.vr.camcom.it/la-camera/modulistica-online/incentivi-internazionalizzazione/normativa/bando-internazionalizzazione-2026.pdf/@@display-file/file_principale"},
                         {"label": L("Alessandria-Asti chamber: export support measures (incl. OCM Vino)", "Camera di commercio di Alessandria-Asti: misure per l'export (incl. OCM Vino)"),
                          "url": "https://www.aa.camcom.it/sites/default/files/contenuto_redazione/editor/Internazionalizzazione_attrazione_investimenti_transizione_digitale_ed_ecologica/Brochure%20misure%20internazionalizzazione/Brochure%20misure%20internazionalizzazione%202026.pdf"}]},
     "coming": {"status": "soon",
                "text": L("Funding finder: MioTEM matches your company and project to the open calls and prepares the application from the data you already gave.",
                          "Ricerca finanziamenti: MioTEM abbina azienda e progetto ai bandi aperti e prepara la domanda con i dati che hai già fornito.")}},
    {"id": "buyer_verification", "by": {"kind": "miotem"},
     "name": L("Buyer verification page", "Pagina di verifica per l'acquirente"),
     "coming": {"status": "preview",
                "text": L("Once your documents are validated, share a page and QR code that lets your buyer see the shipment has been checked.",
                          "Una volta validati i documenti, condividi una pagina e un codice QR con cui l'acquirente vede che la spedizione è stata verificata."),
                "example": [L("Pasta, Italy to United Kingdom: documents validated", "Pasta, Italia verso Regno Unito: documenti validati")]}},
    {"id": "importers", "by": {"kind": "partner", "name": "VeriPura OUTREACH"},
     "name": L("Find importers and reach them", "Trova importatori e contattali"),
     "coming": {"status": "soon",
                "text": L("A growing list of verified foreign buyers and importers of Italian products, with outreach emails sent from your own address. "
                          "A proprietary, tested approach, powered by orchestrated AI-Agents, prepares your sending address and paces your emails so they reach the inbox. With VeriPura OUTREACH.",
                          "Un elenco crescente di acquirenti e importatori esteri verificati di prodotti italiani, con email inviate dal tuo indirizzo. "
                          "Un metodo proprietario e collaudato, basato su AI-Agents orchestrati, prepara il tuo indirizzo di invio e distribuisce le email perché arrivino in posta in arrivo. Con VeriPura OUTREACH.")}},
    {"id": "alerts", "by": {"kind": "miotem"},
     "name": L("Rule changes ahead", "Novità normative in arrivo"),
     "coming": {"status": "soon",
                "text": L("Advance notice of new rules for your product in your destination, from official sources, before they apply.",
                          "Avviso in anticipo delle nuove regole per il tuo prodotto nel mercato di destinazione, da fonti ufficiali, prima che si applichino.")}},
    {"id": "tracking", "by": {"kind": "miotem"},
     "name": L("Shipment tracking", "Tracciamento spedizioni"),
     "coming": {"status": "soon",
                "text": L("The status of each shipment in one view, from departure to delivery.",
                          "Lo stato di ogni spedizione in un'unica vista, dalla partenza alla consegna.")}},
]
TOOL_IDS = {c["id"] for c in CORE + CARDS} | {"refcheck"}
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
        if card["id"] == "shipping":
            order = ["shippypro", "sendcloud"] if p in CHILLED else ["sendcloud", "shippypro"]
            card["today"]["links"] = [PARCEL_LINKS[x] for x in order]
            if p in CHILLED:
                card["today"]["note"] = CHILLED_NOTE
        out.append(card)
    return sorted(out, key=lambda c: c["by"]["kind"] != "miotem")  # MioTEM first, then partners; stable within each


def ai_guide():
    """The tool list for the AI's fixed prompt (cached): what each tool does today, what is next, and where it is."""
    lines = ["MioTEM TOOLS. When the client asks what MioTEM can do, about a tool, or how to use one, answer briefly from this list "
             "(say which are MioTEM's own and which come from partners, and say plainly what is not ready yet). "
             "To offer a button that takes the client to a tool, end your message with one last line "
             "'GOTO: <key>' where key is one of chat, req, duties, docs, eori, tools. "
             "Never describe how a tool works inside, only what it does for the client."]
    for c in CORE + CARDS:
        by = "MioTEM" if c["by"]["kind"] == "miotem" else "partner " + c["by"]["name"]
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
    if tool not in TOOL_IDS:
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
