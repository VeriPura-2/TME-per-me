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

from . import db, funding

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
    {"id": "ai_manager", "go": "chat", "name": L("Your agentic export assistant", "Il suo assistente export agentico"),
     "today": {"text": L("Guides you one question at a time and builds your project: product, market, company.",
                         "La guida una domanda alla volta e costruisce il suo progetto: prodotto, mercato, azienda.")}},
    {"id": "checklist", "go": "req", "name": L("Required documents", "Documenti richiesti"),
     "today": {"text": L("For your product and market, the documents you need, who prepares each one, and the official source where we have one.",
                         "Per il suo prodotto e mercato, i documenti necessari, chi prepara ciascuno e la fonte ufficiale, quando disponibile.")}},
    {"id": "duties", "go": "duties", "name": L("Duties and taxes", "Dazi e imposte"),
     "today": {"text": L("Customs duties for your product in your destination, checked against the official tariffs.",
                         "I dazi doganali per il suo prodotto nel paese di destinazione, verificati rispetto alle tariffe ufficiali.")}},
    {"id": "library", "go": "docs", "name": L("Document library", "Archivio documenti"),
     "today": {"text": L("All your company documents in one place, filed by project, private to your company.",
                         "Tutti i documenti dell'azienda in un unico posto, archiviati per progetto, riservati alla sua azienda.")}},
    {"id": "eori", "go": "eori", "name": L("EORI registration form", "Modulo di registrazione EORI"),
     "today": {"text": L("A prefilled draft of the official customs form: you check, sign and file it.",
                         "Una bozza precompilata del modulo ufficiale delle dogane: la controlla, la firma e la presenta Lei.")}},
    {"id": "consultants", "name": L("Export consultants (TEM)", "Consulenti export (TEM)"),
     "today": {"text": L("Work with your temporary export manager on MioTEM: they see your projects only after you engage them.",
                         "Lavora con il suo temporary export manager su MioTEM: vede i suoi progetti solo dopo che Lei lo ha incaricato.")},
     "coming": {"status": "soon", "text": L("Find a TEM on MioTEM, for ongoing work or for a single project. TEMs can offer their services to exporters on MioTEM.",
                                           "Trovi un TEM su MioTEM, per un rapporto continuativo o per un solo progetto. I TEM possono offrire i propri servizi agli esportatori su MioTEM.")}},
]
for _c in CORE:
    _c["by"], _c["always"] = {"kind": "miotem"}, True

CARDS = [
    {"id": "shipping", "by": {"kind": "partner", "name": "Sendcloud, ShippyPro"},
     "name": L("Shipping", "Spedizioni"),
     "today": {"text": L("Parcels for samples and small orders, booked with these services.",
                         "Pacchi per campioni e piccoli ordini, da prenotare con questi servizi.")},
     "coming": {"status": "soon",
                "text": L("Pallets and containers: shipment tracking through the freight forwarder you or your TEM engage.",
                          "Pallet e container: tracciamento delle spedizioni tramite lo spedizioniere che incarica Lei o il suo TEM.")}},
    {"id": "doc_checks", "by": {"kind": "partner", "name": "VeriPura"},
     "name": L("VeriPura Document Checker", "VeriPura Document Checker"),
     "coming": {"status": "preview",
                "text": L("Upload your documents in the project. For now our staff run the check: it compares the invoice, packing list and transport document with each other, "
                          "and screens ingredients against additives banned in the European Union. Also planned: the export declaration, the e-AD for wine and the US wine certificates.",
                          "Carichi i documenti nel progetto. Per ora il controllo lo avvia il nostro staff: confronta fattura, packing list e documento di trasporto tra loro, "
                          "e controlla gli ingredienti rispetto agli additivi vietati nell'Unione europea. In programma anche la dichiarazione di esportazione, l'e-AD per il vino e i certificati per il vino negli USA."),
                "example": [L("Export declaration (MRN): matches invoice and packing list", "Dichiarazione di esportazione (MRN): coerente con fattura e packing list"),
                            L("e-AD: quantities match the invoice", "e-AD: quantità coerenti con la fattura")]}},
    {"id": "label_check", "by": {"kind": "partner", "name": "VeriPura"},
     "name": L("Label check, VeriPura label validator", "Verifica etichetta, validatore etichette VeriPura"),
     "today": {"text": L("Check your label artwork in the VeriPura label validator (opens in a new tab).",
                         "Verifichi la grafica dell'etichetta nel validatore etichette VeriPura (si apre in una nuova scheda)."),
               "links": [{"label": L("VeriPura label validator", "Validatore etichette VeriPura"), "url": "https://label.veripura.com/"}]},
     "coming": {"status": "preview",
                "text": L("The result inside your project, in Italian.",
                          "Il risultato dentro il progetto, in italiano."),
                "example": [L("Allergens: highlighted correctly", "Allergeni: evidenziati correttamente"),
                            L("Label language: matches the destination", "Lingua dell'etichetta: conforme alla destinazione"),
                            L("Missing: net quantity in the same field of vision as the name", "Manca: quantità netta nello stesso campo visivo della denominazione")]}},
    {"id": "ttb_agent", "by": {"kind": "miotem"}, "only": {"products": ("wine",), "countries": ("usa", "us", "united states")},
     "name": L("US wine certificate assistant", "Assistente certificato vino USA"),
     "coming": {"status": "preview",
                "text": L("Planned: an AI assistant will guide you through the US certificate for your wine, step by step, with you confirming each one.",
                          "In programma: un assistente AI La guiderà nel certificato USA per il suo vino, passo dopo passo, e Lei confermerà ogni passaggio."),
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
                         "Indichi quale denominazione protetta ha il suo prodotto (DOP, IGP, DOCG) e quale organismo di controllo La certifica. "
                         "Ti mostriamo l'organismo che il Ministero dell'agricoltura (MASAF) indica per quel nome, con la data dell'elenco. "
                         "Carichi il certificato in Documenti: finché il nostro staff o VeriPura CORE non lo hanno visto, lo stato resta «dichiarato». "
                         "Per il Parmigiano Reggiano l'esportatore può anche controllare la propria partita IVA nell'elenco pubblico di OCQ PR.")},
     "coming": {"status": "preview",
                "text": L("Request to the control body: with your consent, your TEM or MioTEM staff prepare a request for an extract or a verification (Valoritalia, Kiwa Cermet), send it, and file the reply in Documents.",
                          "Richiesta all'organismo di controllo: con il suo consenso, il suo TEM o lo staff MioTEM preparano una richiesta di estratto o di verifica (Valoritalia, Kiwa Cermet), la inviano e archiviano la risposta in Documenti.")}},
    {"id": "certificates", "by": {"kind": "miotem"},
     "name": L("Certificates and approvals", "Certificati e approvazioni"),
     "today": {"text": L("Keep each certificate and approval in one list: what it covers, who issued it and when it expires. "
                         "We remind you 30 days before it expires. Until our staff or VeriPura Core have seen the document, the status stays claimed.",
                         "Tenga ogni certificato e approvazione in un unico elenco: cosa copre, chi lo ha rilasciato e quando scade. "
                         "Le ricordiamo la scadenza 30 giorni prima. Finché il nostro staff o VeriPura Core non hanno visto il documento, lo stato resta «dichiarato».")}},
    {"id": "label_design", "by": {"kind": "partner", "name": "Food Label Maker, GoVisually"},
     "name": L("Label design", "Progettazione etichette"),
     "today": {"text": L("Create nutrition panels and labels with these partner tools. GoVisually is free, and Food Label Maker has a free trial label. Then upload the label here.",
                         "Crei tabelle nutrizionali ed etichette con questi strumenti dei partner. GoVisually è gratuito e Food Label Maker offre un'etichetta di prova gratuita. Poi carichi qui l'etichetta."),
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
               "checked": funding.last_checked(),
               "notify": "funding_calls",
               "links": funding.card_links()}},  # data/funding.json per scheme (F5); no "coming" line: the eligibility check and deadline reminders are live under Duties (F1, F2)
    {"id": "buyer_verification", "by": {"kind": "miotem"},
     "name": L("Buyer verification page", "Pagina di verifica per l'acquirente"),
     "coming": {"status": "preview",
                "text": L("Planned: once your documents are checked, share a page and QR code that shows your buyer the documents for the shipment were checked.",
                          "In programma: una volta verificati i documenti, condividi una pagina e un codice QR che mostra all'acquirente che i documenti della spedizione sono stati verificati."),
                "example": [L("Example, not a real shipment: pasta, Italy to United Kingdom, documents checked", "Esempio, non una spedizione reale: pasta, Italia verso Regno Unito, documenti verificati")]}},
    {"id": "vero_italiano", "by": {"kind": "partner", "name": "Vero Italiano"},
     "name": L("Vero Italiano: validate your product claims", "Vero Italiano: convalida delle dichiarazioni sul prodotto"),
     "coming": {"status": "preview",
                "text": L("Planned, and voluntary: you declare where your product comes from and how it is made, and upload the evidence. "
                          "Independent checks then place it on the Vero Italiano scale from A to G. Lower grades are honest results, not failures.",
                          "In programma, su base volontaria: Lei dichiara da dove viene il prodotto e come è fatto, e carica le prove. "
                          "Controlli indipendenti lo collocano poi sulla scala Vero Italiano da A a G. I gradi più bassi sono risultati onesti, non bocciature."),
                # Scripted example for demos (Thomas, 20 Nov 2026): no AI call, nothing stored. Example company and VAT are invented.
                "walk": [
                    {"t": L("What it is", "Che cos'è"),
                     "lines": [L("Voluntary: you choose what to share, and you can stop at any time.",
                                 "Volontario: Lei sceglie cosa condividere e può fermarsi in qualsiasi momento."),
                               L("The scale: A DOP or single Italian origin, B 100% Italian ingredients, C made in Italy from foreign raw material, "
                                 "D packed abroad from Italian ingredients, E Italian brand made abroad, F Italian sounding only, G false origin claim.",
                                 "La scala: A DOP o origine italiana unica, B ingredienti 100% italiani, C prodotto in Italia da materia prima estera, "
                                 "D confezionato all'estero da ingredienti italiani, E marchio italiano prodotto all'estero, F solo nome che richiama l'Italia, G falsa indicazione d'origine."),
                               L("C, D and E are legitimate when disclosed. The aim is an accurate result that protects honest producers.",
                                 "C, D ed E sono legittimi se dichiarati. Lo scopo è un risultato esatto, che tutela i produttori onesti."),
                               L("This step collects and pre-checks your data. It never gives a grade.",
                                 "Questa fase raccoglie e controlla in via preliminare i dati. Non assegna mai un grado.")]},
                    {"t": L("Already in MioTEM", "Già in MioTEM"),
                     "lines": [L("Company: Caseificio Esempio Srl, VAT IT00000000000", "Azienda: Caseificio Esempio Srl, partita IVA IT00000000000"),
                               L("Product: Parmigiano Reggiano DOP, whole wheels", "Prodotto: Parmigiano Reggiano DOP, forme intere"),
                               L("Destination: United States, tariff line 0406.90.61.00", "Destinazione: Stati Uniti, voce tariffaria 0406.90.61.00"),
                               L("Taken from your project: you are not asked for it again.", "Preso dal progetto: non Le viene chiesto di nuovo.")]},
                    {"t": L("Your claims", "Le sue dichiarazioni"),
                     "lines": [L("Milk: cow's milk from 12 supplying farms in the province of Reggio Emilia", "Latte: latte vaccino da 12 aziende conferenti in provincia di Reggio Emilia"),
                               L("Made and aged: own dairy, Reggio Emilia. Packed: whole wheels, not portioned", "Prodotto e stagionato: caseificio proprio, Reggio Emilia. Confezionato: forme intere, non porzionate"),
                               L("Bought in: no milk, curd or milk powder", "Acquistato da terzi: nessun latte, cagliata o latte in polvere"),
                               L("Grade you believe applies: A", "Grado che ritiene corretto: A"),
                               L("You type only claims and identifiers. Everything else is an upload or a consent.",
                                 "Lei scrive solo dichiarazioni e codici. Tutto il resto è un caricamento o un consenso.")]},
                    {"t": L("Your evidence", "Le sue prove"),
                     "lines": [L("Label photo: read by VeriPura Core, \"Parmigiano Reggiano DOP\" found", "Foto dell'etichetta: letta da VeriPura Core, trovato \"Parmigiano Reggiano DOP\""),
                               L("Control body certificate (OCQ PR): read by VeriPura Core, holder and VAT match the company", "Certificato dell'organismo di controllo (OCQ PR): letto da VeriPura Core, titolare e partita IVA coincidono con l'azienda"),
                               L("Lots: 3 lots, 1,150 wheels. Casein plates issued: 1,200", "Lotti: 3 lotti, 1.150 forme. Placche di caseina rilasciate: 1.200"),
                               L("Coming later, nothing asked yet: e-invoices, bank payments to farms, satellite checks of land, lab sampling.",
                                 "In arrivo, per ora non richiesti: fatture elettroniche, pagamenti bancari alle aziende conferenti, controlli satellitari dei terreni, campionamento in laboratorio.")]},
                    {"t": L("Pre-check", "Controllo preliminare"),
                     "lines": [L("Ready: certificate and protected name, label", "Pronti: certificato e denominazione protetta, etichetta"),
                               L("Missing: the list of supplying farms", "Mancante: l'elenco delle aziende conferenti"),
                               L("To clarify: 1,200 casein plates issued and 1,150 wheels declared. Were 50 plates unused, or is a lot missing?",
                                 "Da chiarire: 1.200 placche di caseina rilasciate e 1.150 forme dichiarate. Sono rimaste 50 placche inutilizzate, o manca un lotto?"),
                               L("Points to clarify are questions, not findings.", "I punti da chiarire sono domande, non contestazioni.")]},
                    {"t": L("Readiness report", "Rapporto di preparazione"),
                     "lines": [L("Received: claims, label, certificate, lots", "Ricevuti: dichiarazioni, etichetta, certificato, lotti"),
                               L("Still missing: the supplying farms list, so milk volumes can be compared with the farms", "Ancora mancante: l'elenco delle aziende conferenti, per confrontare i volumi di latte con le aziende"),
                               L("Next: the independent checks run once you have answered. No grade is given before then.",
                                 "Poi: i controlli indipendenti partono dopo le sue risposte. Prima di allora non viene assegnato alcun grado.")]}]}},
    {"id": "importers", "by": {"kind": "partner", "name": "VeriPura Connect"},
     "name": L("Researched importers", "Importatori ricercati"),
     "today": {"text": L("Browse researched importers of Italian food and wine for your destination. This list is updated regularly.",
                         "Consulti gli importatori ricercati di prodotti alimentari e vino italiani per la sua destinazione. L'elenco è aggiornato regolarmente.")},
     "no_tell": True,
     "coming": {"status": "soon",
                "text": L("Contact importers through VeriPura Connect.",
                          "Contatta gli importatori tramite VeriPura Connect.")}},
    {"id": "outreach", "by": {"kind": "miotem"},
     "name": L("Outreach to importers", "Campagne verso gli importatori"),
     "coming": {"status": "soon",
                "text": L("Market development: plan and send outreach campaigns to importers for your product and market, from MioTEM.",
                          "Sviluppo del mercato: pianifichi e invii campagne di contatto agli importatori per il suo prodotto e mercato, da MioTEM.")}},
    {"id": "alerts", "by": {"kind": "miotem"},
     "name": L("Rule changes ahead", "Novità normative in arrivo"),
     "coming": {"status": "soon",
                "text": L("Notices of new food-safety rules for your product and destination, from official WTO notifications and from changes to official sources.",
                          "Avvisi sulle nuove norme di sicurezza alimentare per il suo prodotto e la sua destinazione, dalle notifiche ufficiali WTO e dalle modifiche alle fonti ufficiali.")}},
]
TOOL_IDS = {c["id"] for c in CORE + CARDS} | {"refcheck"}
STEP = {"label_check": 2, "label_design": 2, "ttb_agent": 3, "shipping": 4}  # the checklist step where the tool helps (1 Company, 2 Product, 3 Destination, 4 Shipment)
INTEREST_ONLY = {"funding_calls", "tem_intro", "bank_financing", "mode2", "tem_single_projects", "tem_funding", "tem_bank_clients", "tem_sace", "tem_setup_call", "plan_parti", "plan_cresci"}  # interest buttons that are not a card of their own; mode2: a TEM offering single-project work (TEM workspace), the exporter card was merged into the TEM card on 20 Nov 2026
CONSENT_NEEDED = {"tem_intro", "bank_financing", "tem_single_projects", "tem_funding", "tem_bank_clients", "tem_sace", "tem_setup_call", "plan_parti", "plan_cresci"}  # tour closing questions: staff contact the person, so consent is required (20 Nov 2026)
CLIENT_OFF = {"shipping", "label_check", "importers", "outreach"}  # hidden from a TEM's client unless the TEM switches them on


# Guided tour of a project for exporters (Thomas, 20 Nov 2026): one stop per part of the page; tool stops ask "Interested?".
# go: where the page goes (a goTo key, or "team"); tool: the card to highlight; ask: the interest recorded on "Yes".
# The closing stop asks two questions that staff follow up, each with its own consent. No AI call anywhere.
TOUR = [
    {"id": "chat", "go": "chat", "t": L("Your export assistant", "Il suo assistente export"),
     "text": L("Start here. The assistant asks one question at a time about your product, your market and your company, and builds your project from your answers.",
               "Si parte da qui. L'assistente fa una domanda alla volta su prodotto, mercato e azienda, e costruisce il progetto con le sue risposte.")},
    {"id": "req", "go": "req", "t": L("Required documents", "Documenti richiesti"),
     "text": L("For your product and destination: each document you need, who prepares it, and the official source where we have one. Rows still to be confirmed by our staff are marked as such.",
               "Per il suo prodotto e la sua destinazione: ogni documento necessario, chi lo prepara e la fonte ufficiale, quando disponibile. Le righe ancora da confermare dal nostro staff sono segnalate.")},
    {"id": "duties", "go": "duties", "t": L("Duties and taxes", "Dazi e imposte"),
     "text": L("Customs duties for your product in your destination, checked against the official tariffs.",
               "I dazi doganali per il suo prodotto nel paese di destinazione, verificati rispetto alle tariffe ufficiali.")},
    {"id": "landed", "go": "duties", "jel": "j-landed", "t": L("Landed cost estimate", "Stima del costo all'arrivo"),
     "text": L("Add your goods value, freight, insurance and other costs. MioTEM adds the duty from the official tariff and shows the cost per unit, so you can quote with the border costs in view.",
               "Inserisca valore della merce, trasporto, assicurazione e altri costi. MioTEM aggiunge il dazio della tariffa ufficiale e mostra il costo per unità, così può fare un'offerta tenendo conto dei costi alla frontiera.")},
    {"id": "eori", "go": "eori", "ask": "eori", "t": L("EORI registration", "Registrazione EORI"),
     "text": L("Your EORI number identifies your company to EU customs. MioTEM prepares the official form with the data you have given: you check it, sign it and file it.",
               "Il numero EORI identifica la sua azienda presso le dogane UE. MioTEM prepara il modulo ufficiale con i dati che ha fornito: Lei lo controlla, lo firma e lo presenta.")},
    {"id": "docs", "go": "docs", "ask": "doc_checks", "t": L("Document library and checks", "Archivio documenti e controlli"),
     "text": L("All your company documents in one place, filed by project. In preview: the VeriPura Document Checker compares your invoice, packing list and transport document with each other.",
               "Tutti i documenti dell'azienda in un unico posto, archiviati per progetto. In anteprima: il VeriPura Document Checker confronta tra loro fattura, packing list e documento di trasporto.")},
    {"id": "cert", "go": "tools", "tool": "cert_evidence", "ask": "cert_evidence", "t": L("Certification evidence", "Prove delle certificazioni"),
     "text": L("Tell us which protected name your product carries and which control body certifies you, then upload the certificate. For Parmigiano Reggiano you can also check your VAT number against the public list of OCQ PR.",
               "Indichi quale denominazione protetta ha il prodotto e quale organismo di controllo La certifica, poi carichi il certificato. Per il Parmigiano Reggiano può anche controllare la partita IVA nell'elenco pubblico di OCQ PR.")},
    {"id": "certs", "go": "tools", "tool": "certificates", "t": L("Certificates and approvals", "Certificati e approvazioni"),
     "text": L("Keep each certificate and approval in one list, with who issued it and when it expires. We remind you 30 days before it expires.",
               "Tenga ogni certificato e approvazione in un unico elenco, con chi lo ha rilasciato e quando scade. Le ricordiamo la scadenza 30 giorni prima.")},
    {"id": "label_design", "go": "tools", "tool": "label_design", "ask": "label_design", "t": L("Label design", "Progettazione etichette"),
     "text": L("Create nutrition panels and labels with partner tools, then upload the label in your project.",
               "Crei tabelle nutrizionali ed etichette con strumenti dei partner, poi carichi l'etichetta nel progetto.")},
    {"id": "label", "go": "tools", "tool": "label_check", "ask": "label_check", "t": L("Your label", "La sua etichetta"),
     "text": L("Check your label artwork with the VeriPura label validator, or create one with partner design tools.",
               "Verifichi la grafica dell'etichetta con il validatore etichette VeriPura, oppure la crei con gli strumenti di progettazione dei partner.")},
    {"id": "shipping", "go": "tools", "tool": "shipping", "ask": "shipping", "t": L("Shipping", "Spedizioni"),
     "text": L("Parcels for samples and small orders, booked with partner services. Pallets and containers are coming.",
               "Pacchi per campioni e piccoli ordini, da prenotare con servizi partner. Pallet e container sono in arrivo.")},
    {"id": "importers", "go": "tools", "tool": "importers", "ask": "importers", "t": L("Researched importers", "Importatori ricercati"),
     "text": L("Importers of Italian food and wine for your destination. For a new market you can also ask for a TEM on MioTEM to find and contact importers for you. Contact through VeriPura Connect is coming.",
               "Importatori di prodotti alimentari e vino italiani per la sua destinazione. Per un mercato nuovo può anche chiedere che un TEM su MioTEM cerchi e contatti gli importatori per Lei. Il contatto tramite VeriPura Connect è in arrivo.")},
    {"id": "funding", "go": "tools", "tool": "funding", "ask": "funding", "t": L("Funding for exporting", "Finanziamenti per l'export"),
     "text": L("Official programmes that fund export projects and temporary export managers, each marked open, closed or check the page.",
               "Programmi ufficiali che finanziano progetti export e temporary export manager, ognuno indicato come aperto, chiuso o da verificare.")},
    {"id": "fin", "go": "duties", "jel": "j-fund", "t": L("Financing that may fit you", "Finanziamenti adatti a Lei"),
     "text": L("Answer six questions and see which schemes may fit your company, with the official source and check date for each, and the deadlines. The funder always decides.",
               "Risponda a sei domande e veda quali bandi possono adattarsi alla sua azienda, con la fonte ufficiale e la data di verifica di ciascuno, e le scadenze. Decide sempre l'ente che finanzia.")},
    {"id": "vero", "go": "tools", "tool": "vero_italiano", "ask": "vero_italiano", "t": L("Vero Italiano", "Vero Italiano"),
     "text": L("In development: voluntary validation of the claims you make about your product. Open the example on the card to see how it will work.",
               "In sviluppo: convalida volontaria delle dichiarazioni sul suo prodotto. Apra l'esempio sulla scheda per vedere come funzionerà.")},
    {"id": "team", "go": "team", "t": L("Your team", "Il suo team"),
     "text": L("Invite colleagues and give each one a role. The plan belongs to the company.",
               "Inviti i colleghi e assegni a ciascuno un ruolo. Il piano appartiene all'azienda.")},
    {"id": "close", "t": L("Two last questions", "Due ultime domande"),
     "text": L("Both are optional. Your answers only tell our staff how to help you.",
               "Entrambe facoltative. Le risposte servono solo al nostro staff per capire come aiutarLa."),
     "questions": [
         {"ask": "tem_intro", "q": L("Would you like an introduction to a TEM (temporary export manager) on MioTEM?",
                                     "Desidera essere presentato a un TEM (temporary export manager) su MioTEM?"),
          "note": L("TEMs on MioTEM see your request and can offer to help. MioTEM staff then arrange the introduction. We cannot promise a match.",
                    "I TEM su MioTEM vedono la sua richiesta e possono offrirsi di aiutarLa. Lo staff MioTEM organizza poi la presentazione. Non possiamo garantire un abbinamento."),
          "consent": L("I agree that MioTEM may show my company name, product and destination to TEMs on MioTEM, and contact me about an introduction.",
                       "Acconsento che MioTEM mostri ragione sociale, prodotto e destinazione ai TEM su MioTEM, e mi contatti per una presentazione.")},
         {"ask": "bank_financing", "q": L("Are you interested in export financing from Crédit Agricole Italia?",
                                          "Le interessa un finanziamento all'export di Crédit Agricole Italia?"),
          "note": L("Our staff note your interest and contact you. Nothing is shared with the bank without asking you first.",
                    "Il nostro staff registra il suo interesse e La contatta. Nulla viene condiviso con la banca senza prima chiederlo a Lei."),
          "consent": L("I agree that MioTEM staff may contact me about export financing.", "Acconsento a essere contattato dallo staff MioTEM per il finanziamento all'export.")}]},
]

# TEM tour (Thomas, 20 Nov 2026): the workspace, then the TEM's first client project, then five questions staff follow up.
# area: ws (workspace) or proj (first client project); el: element id to highlight; tool: card to highlight. No AI call.
TEM_TOUR = [
    {"id": "ws", "area": "ws", "el": "tw-firm", "t": L('Your workspace', 'Il suo studio'),
     "text": L("Your firm's home on MioTEM: your role, seats, and how many client projects your plan allows.",
               'La casa del suo studio su MioTEM: il suo ruolo, i posti e quanti progetti dei clienti consente il suo piano.')},
    {"id": "team", "area": "ws", "el": "tw-team", "t": L('Firm team', 'Squadra dello studio'),
     "text": L('Invite colleagues to your firm. Only the lead can invite or remove people.',
               'Inviti i colleghi nel suo studio. Solo il responsabile può invitare o rimuovere persone.')},
    {"id": "engage", "area": "ws", "el": "tw-engage", "t": L('Engagement link', 'Link di incarico'),
     "text": L('Send this link to a client. When they accept, they engage you on MioTEM and their projects appear here.',
               'Invii questo link a un cliente. Quando accetta, La incarica su MioTEM e i suoi progetti compaiono qui.')},
    {"id": "clients", "area": "ws", "el": "tw-client", "t": L('Clients and requests', 'Clienti e richieste'),
     "text": L('Each client, their projects and document progress. When a client asks you for help with a tool, the request shows here, and you mark it done.',
               "Ogni cliente, i suoi progetti e l'avanzamento dei documenti. Quando un cliente Le chiede aiuto per uno strumento, la richiesta compare qui e Lei la segna come fatta.")},
    {"id": "intros", "area": "ws", "el": "tw-intros", "t": L("Exporters looking for a TEM", "Esportatori che cercano un TEM"),
     "text": L("Exporters who want a TEM appear here. Offer to help, and MioTEM staff arrange the introduction.",
               "Qui compaiono gli esportatori che cercano un TEM. Si offra di aiutarli e lo staff MioTEM organizza la presentazione.")},
    {"id": "newp", "area": "ws", "el": "tw-newp", "t": L('New client project', 'Nuovo progetto per un cliente'),
     "text": L('Create a project for a client by choosing the product and the destination.',
               'Crei un progetto per un cliente scegliendo il prodotto e la destinazione.')},
    {"id": "proj", "area": "proj", "el": "tw-case", "t": L('Project and chat', 'Progetto e chat'),
     "text": L("The project details collected so far and what is still missing. Open the chat to continue on your client's behalf.",
               'I dati del progetto raccolti finora e cosa manca ancora. Apra la chat per proseguire per conto del cliente.')},
    {"id": "req", "area": "proj", "el": "tw-req", "t": L('Required documents', 'Documenti richiesti'),
     "text": L('The documents your client needs. You can confirm rows still to be verified, with a note. Your client sees your name on each confirmation.',
               'I documenti di cui il cliente ha bisogno. Può confermare le righe ancora da verificare, con una nota. Il cliente vede il suo nome su ogni conferma.')},
    {"id": "docreq", "area": "proj", "el": "tw-docreq", "t": L("Document requests", "Richieste di documenti"),
     "text": L("Tick the documents you need from your client and send one request. Your client uploads into it, you accept it or ask for a change, and MioTEM sends the reminders. Less time chasing files.",
               "Selezioni i documenti che Le servono dal cliente e invii una sola richiesta. Il cliente li carica lì, Lei li accetta o chiede una modifica, e MioTEM invia i promemoria. Meno tempo a rincorrere i file.")},
    {"id": "duties", "area": "proj", "el": "tw-duties", "t": L('Duties and taxes', 'Dazi e imposte'),
     "text": L('Customs duties for this product in this destination, checked against the official tariffs.',
               'I dazi doganali per questo prodotto in questa destinazione, verificati rispetto alle tariffe ufficiali.')},
    {"id": "margin", "area": "proj", "el": "tw-margin", "t": L("Hours and margin", "Ore e margine"),
     "text": L("Record the fee you agreed and the hours you spend. You see your effective hourly rate and margin, and a warning when a project falls below your target rate. Only your firm sees this.",
               "Registri il compenso concordato e le ore impiegate. Vede la tariffa oraria effettiva e il margine, e un avviso quando un progetto scende sotto la sua tariffa obiettivo. Lo vede solo il suo studio.")},
    {"id": "fin", "area": "proj", "el": "tw-fin", "t": L("Financing for this client", "Finanziamenti per questo cliente"),
     "text": L("Track your client's application: scheme, status, deadline and the documents still missing. Hours on financing go in your time log, so you can bill them.",
               "Segua la domanda del cliente: bando, stato, scadenza e documenti ancora mancanti. Le ore sui finanziamenti vanno nel registro del tempo, così può fatturarle.")},
    {"id": "icon", "area": "proj", "el": "tw-icon", "t": L("Importers contacted", "Importatori contattati"),
     "text": L("Record every importer you contact for this client and the result. Your client always sees this record, so the work you do is visible.",
               "Registri ogni importatore contattato per questo cliente e l'esito. Il cliente vede sempre questo registro, così il lavoro svolto è visibile.")},
    {"id": "report", "area": "proj", "el": "tw-report", "t": L("Client report", "Report per il cliente"),
     "text": L("A printable report under your firm's name: documents received and outstanding, checks done, importers contacted and your notes for the client.",
               "Un report stampabile a nome del suo studio: documenti ricevuti e mancanti, controlli eseguiti, importatori contattati e le sue note per il cliente.")},
    {"id": "vis", "area": "proj", "el": "tw-tools", "t": L('Tools and what your client sees', 'Strumenti e cosa vede il cliente'),
     "text": L('You decide which tools each client sees, with the visibility switch on each card. Some start switched off, for work you may prefer to do or arrange yourself.',
               "Lei decide quali strumenti vede ogni cliente, con l'interruttore di visibilità su ogni scheda. Alcuni sono spenti in partenza, per il lavoro che preferisce svolgere o organizzare Lei.")},
    {"id": "importers", "area": "proj", "tool": "importers", "ask": "importers", "t": L('Importer discovery', 'Ricerca importatori'),
     "text": L("Researched importers for your client's product category and destination market.",
               'Importatori ricercati per la categoria di prodotto e il mercato di destinazione del cliente.')},
    {"id": "outreach", "area": "proj", "tool": "outreach", "ask": "outreach", "t": L('Outreach to importers', 'Campagne verso gli importatori'),
     "text": L("Coming soon: plan and send outreach campaigns to importers for your client's product and market.",
               'In arrivo: pianificare e inviare campagne di contatto agli importatori per il prodotto e il mercato del cliente.')},
    {"id": "label_design", "area": "proj", "tool": "label_design", "ask": "label_design", "t": L('Label creation', "Creazione dell'etichetta"),
     "text": L('Create nutrition panels and labels with partner tools, then upload the label in the project.',
               "Crei tabelle nutrizionali ed etichette con strumenti dei partner, poi carichi l'etichetta nel progetto.")},
    {"id": "label", "area": "proj", "tool": "label_check", "ask": "label_check", "t": L('Label validation', "Verifica dell'etichetta"),
     "text": L("Check a client's label artwork with the VeriPura label validator. Your client can use it directly, or you use it for them.",
               "Verifichi la grafica dell'etichetta del cliente con il validatore etichette VeriPura. Il cliente può usarlo direttamente, oppure Lei lo usa per lui.")},
    {"id": "shipping", "area": "proj", "tool": "shipping", "ask": "shipping", "t": L('Shipment options', 'Opzioni di spedizione'),
     "text": L('Parcels for samples and small orders, booked with partner services. Pallets and containers are coming.',
               'Pacchi per campioni e piccoli ordini, da prenotare con servizi partner. Pallet e container sono in arrivo.')},
    {"id": "doc_checks", "area": "proj", "tool": "doc_checks", "ask": "doc_checks", "t": L('VeriPura Document Checker', 'VeriPura Document Checker'),
     "text": L("In preview: compares your client's invoice, packing list and transport document with each other.",
               'In anteprima: confronta tra loro fattura, packing list e documento di trasporto del cliente.')},
    {"id": "vero", "area": "proj", "tool": "vero_italiano", "ask": "vero_italiano", "t": L('Vero Italiano', 'Vero Italiano'),
     "text": L('In development: voluntary validation of the claims your client makes about the product. Open the example on the card to see how it will work.',
               "In sviluppo: convalida volontaria delle dichiarazioni del cliente sul prodotto. Apra l'esempio sulla scheda per vedere come funzionerà.")},
    {"id": "docs", "area": "proj", "el": "tw-docs", "t": L('Client documents', 'Documenti del cliente'),
     "text": L('The files your client uploaded for this project.',
               'I file che il cliente ha caricato per questo progetto.')},
    {"id": "close", "t": L("A few last questions", "Alcune ultime domande"),
     "text": L("All optional. Your answers only tell our staff how to help you.",
               "Tutte facoltative. Le risposte servono solo al nostro staff per capire come aiutarLa."),
     "questions": [
         {"ask": "tem_single_projects", "q": L('Interested in offering your services on MioTEM for single projects, so exporters who need short-term help can find you?',
                              'Le interessa offrire i suoi servizi su MioTEM per singoli progetti, così che gli esportatori che cercano un aiuto a breve termine possano trovarLa?'),
          "note": L('Optional.', 'Facoltativo.'),
          "consent": L('I agree that MioTEM staff may contact me about this.', 'Acconsento a essere contattato dallo staff MioTEM su questo tema.')},
         {"ask": "tem_funding", "q": L('Interested in help finding funding calls that cover TEM costs for your clients?',
                              'Le interessa un aiuto per trovare bandi che coprano i costi del TEM per i suoi clienti?'),
          "note": L('Optional.', 'Facoltativo.'),
          "consent": L('I agree that MioTEM staff may contact me about this.', 'Acconsento a essere contattato dallo staff MioTEM su questo tema.')},
         {"ask": "tem_bank_clients", "q": L('Would your clients be interested in export financing from Crédit Agricole Italia?',
                              "I suoi clienti sarebbero interessati a un finanziamento all'export di Crédit Agricole Italia?"),
          "note": L('Our staff note the interest and contact you. Nothing is shared with the bank without asking first.', "Il nostro staff registra l'interesse e La contatta. Nulla viene condiviso con la banca senza chiederlo prima."),
          "consent": L('I agree that MioTEM staff may contact me about this.', 'Acconsento a essere contattato dallo staff MioTEM su questo tema.')},
         {"ask": "tem_sace", "q": L("Interested in export support from SACE, Italy's export credit agency, for your clients?",
                              "Le interessa il supporto all'export di SACE, l'agenzia italiana per il credito all'esportazione, per i suoi clienti?"),
          "note": L('Our staff note the interest and contact you. Nothing is shared with SACE without asking first.', "Il nostro staff registra l'interesse e La contatta. Nulla viene condiviso con SACE senza chiederlo prima."),
          "consent": L('I agree that MioTEM staff may contact me about this.', 'Acconsento a essere contattato dallo staff MioTEM su questo tema.')},
         {"ask": "tem_setup_call", "q": L('Would you like a call with MioTEM staff to set up your firm and first clients?',
                              'Desidera una chiamata con lo staff MioTEM per configurare il suo studio e i primi clienti?'),
          "note": L('Optional.', 'Facoltativo.'),
          "consent": L('I agree that MioTEM staff may contact me to arrange the call.', 'Acconsento a essere contattato dallo staff MioTEM per fissare la chiamata.')},
     ]},
]


def _norm(s):
    return (s or "").strip().lower()


# Display order (22 Nov 2026 research): compliance and its costs first, growth tools after, the lowest rated last
# (outreach). Importers move up, right after the compliance tools, for a first-time exporter or a new market (no importer there yet).
ORDER = ["ai_manager", "checklist", "duties", "library", "eori",
         "doc_checks", "label_check", "ttb_agent", "cert_evidence", "certificates", "alerts",
         "label_design", "shipping", "vero_italiano", "buyer_verification", "funding", "importers",
         "consultants", "outreach"]
FIRST_TIME_UP = ("importers",)


def _rank(first_time):
    order = list(ORDER)
    if first_time:
        for t in reversed(FIRST_TIME_UP):
            order.remove(t)
            order.insert(order.index("alerts") + 1, t)
    return {t: i for i, t in enumerate(order)}


def for_case(product_category, country, first_time=False):
    """The tool cards for one project, in display order (deep copies, safe to annotate).
    first_time: researched importers move up. True for a first-time exporter or a new market for this project
    (no importer in the destination yet), R1 22 Nov 2026."""
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
    rank = _rank(first_time)
    return sorted(out, key=lambda c: rank.get(c["id"], len(rank)))


PUBLIC_TEXT = {
    "certificates": L("Keep each certificate and approval in one list: what it covers, who issued it and when it expires, with a reminder 30 days before.",
                      "Tenga ogni certificato e approvazione in un unico elenco: cosa copre, chi lo ha rilasciato e quando scade, con un promemoria 30 giorni prima."),  # shorter wording for the public page (no link details, no partner names beyond the approved label validator)
    "shipping": L("Parcels for samples and small orders, booked with partner services. Next: pallets and containers.",
                  "Pacchi per campioni e piccoli ordini, prenotabili con servizi partner. Poi: pallet e container."),
    "label_check": L("Check your label artwork in the VeriPura label validator. Next: the result inside your project, in Italian.",
                     "Verifichi la grafica dell'etichetta nel validatore etichette VeriPura. Poi: il risultato dentro il progetto, in italiano."),
    "label_design": L("Create nutrition panels and labels with partner tools, then upload the label in your project.",
                      "Crei tabelle nutrizionali ed etichette con strumenti dei partner, poi carichi l'etichetta nel progetto."),
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


def for_viewer(con, case_row, category, country, viewer, first_time=False):
    """viewer: exporter, tem or client. Returns {"cards": [...], "refcheck": bool}, with client_visible flags for the TEM."""
    cards = for_case(category, country, first_time)
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


def record_interest(con, case_id, user_sub, tool, consent=False, email=None):
    if tool not in TOOL_IDS and tool not in INTEREST_ONLY:
        return 400, {"error": "unknown tool"}
    if tool in CONSENT_NEEDED and consent is not True:
        return 400, {"error": "consent required"}
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
        data = {"tool": tool, "user_type": utype}
        if tool in CONSENT_NEEDED:
            data["consent"] = "agreed that MioTEM staff may contact them about this"
            data["email"] = str(email or "").strip()[:254] or None  # sent by the person's browser from the sign-in, for staff follow-up
        db.log_event(con, case_id, user_sub, "tool_interest", data)
    return 200, {"ok": True}


def contact_requests(con):
    """Tour closing answers that staff must follow up: TEM introduction and Credit Agricole Italia financing interest.
    The email is the one the person's browser sent from the sign-in when they answered, else the company membership label."""
    import json
    out = []
    for r in con.execute("SELECT e.at, e.actor, e.case_id, e.data FROM events e WHERE e.kind='tool_interest' ORDER BY e.at DESC LIMIT 2000").fetchall():
        d = json.loads(r["data"] or "{}")
        if d.get("tool") not in CONSENT_NEEDED or not d.get("consent"):
            continue
        co = con.execute("SELECT co.legal_name AS company, m.label FROM memberships m JOIN companies co ON co.id=m.company_id "
                         "WHERE m.user_sub=? AND m.status='active' LIMIT 1", (r["actor"],)).fetchone()
        out.append({"tool": d["tool"], "created_at": r["at"], "company": co["company"] if co else None,
                    "email": d.get("email") or (co["label"] if co else None)})
        if len(out) >= 200:
            break
    return {"total": len(out), "requests": out}


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
                             "Formato corretto (21 caratteri). Lo stato del movimento è visibile nel suo account EMCS o tramite il suo spedizioniere doganale." if ok else
                             "Non sembra un ARC: ha 21 caratteri e inizia con l'anno e il codice paese (es. 26IT...).")}
    return {"error": "unknown kind"}
