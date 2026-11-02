"""Required documents checklist, Wave 1 (prepared by MioTEM, verified by staff).

Origin Italy. Products: dried pasta, wine, olive oil, cheese. Destinations: UK, USA, Canada, Germany, France, Spain, Netherlands, Belgium, Austria
(France and the last four added 2 Nov 2026), Switzerland (2 Nov 2026).
Source review: MioTEM_Wave1_Required_Documents_DRAFT.md (1 Nov 2026), approved for coding.

Confidence: A = confirmed in an official source. B = secondary source, official link to attach.
C = known rule, source to be checked by staff. Only A rows count as verified; B and C rows are
shown as "staff to verify" until a staff member confirms them.

When VeriPura Core exposes a requirements endpoint, replace required() with a Core call that
returns the same shape, and keep this file as the cross-check.
"""

CHECKED = "2026-11-01"

PRODUCTS = {"pasta": "pasta", "wine": "wine", "olive oil": "oil", "cheese and dairy": "cheese", "cheese": "cheese"}
DESTINATIONS = {"uk": "UK", "united kingdom": "UK", "gb": "UK", "great britain": "UK",
                "usa": "US", "us": "US", "united states": "US", "stati uniti": "US",
                "canada": "CA", "germany": "DE", "germania": "DE", "deutschland": "DE", "regno unito": "UK",
                "france": "FR", "francia": "FR",
                "spain": "ES", "spagna": "ES", "españa": "ES", "espana": "ES",
                "netherlands": "NL", "the netherlands": "NL", "paesi bassi": "NL", "olanda": "NL", "holland": "NL",
                "nederland": "NL",
                "belgium": "BE", "belgio": "BE", "belgique": "BE", "belgië": "BE", "belgie": "BE",
                "austria": "AT", "österreich": "AT", "osterreich": "AT", "oesterreich": "AT",
                "switzerland": "CH", "svizzera": "CH", "schweiz": "CH", "suisse": "CH"}

ALL_P = {"pasta", "wine", "oil", "cheese"}
NON_EU = {"UK", "US", "CA", "CH"}
EU_D = {"DE", "FR", "ES", "NL", "BE", "AT"}  # other EU countries: no customs, intra-EU VAT and excise rules
ALL_D = NON_EU | EU_D

LAYERS = {1: {"it": "Azienda", "en": "Company"}, 2: {"it": "Prodotto", "en": "Product"},
          3: {"it": "Mercato", "en": "Destination"}, 4: {"it": "Spedizione", "en": "Shipment"}}

WHO = {
    "exporter": {"it": "Esportatore", "en": "Exporter"},
    "importer": {"it": "Importatore", "en": "Importer"},
    "agent": {"it": "Spedizioniere o doganalista", "en": "Customs agent or forwarder"},
    "carrier": {"it": "Vettore", "en": "Carrier"},
    "customs": {"it": "Agenzia delle Dogane", "en": "Italian customs"},
    "asl": {"it": "ASL", "en": "ASL (local health authority)"},
    "vet": {"it": "Veterinario ufficiale ASL", "en": "ASL official vet"},
    "warehouse": {"it": "Deposito fiscale", "en": "Tax warehouse"},
    "buyer_de": {"it": "Di solito l'acquirente tedesco", "en": "Usually the German buyer"},
    "buyer_fr": {"it": "Di solito l'acquirente francese", "en": "Usually the French buyer"},
    "buyer_eu": {"it": "Di solito l'acquirente nel paese di destinazione", "en": "Usually the buyer in the destination country"},
    "staff": {"it": "Verifica dello staff", "en": "Staff check"},
}
IMPORTER_SIDE = {"importer", "buyer_de", "buyer_fr", "buyer_eu"}

SRC = {
    "uk_label": "https://www.food.gov.uk/business-guidance/packaging-and-labelling",
    "uk_composite": "https://www.gov.uk/guidance/import-or-move-composite-products-from-the-eu-and-northern-ireland-to-great-britain",
    "uk_btom": "https://www.gov.uk/guidance/import-or-move-food-and-drink-from-the-eu-and-northern-ireland-to-great-britain",
    "uk_wine": "https://www.food.gov.uk/business-guidance/importing-and-exporting-wine",
    "uk_wine_label": "https://www.gov.uk/guidance/importing-selling-and-labelling-wine",
    "ttb": "https://www.ttb.gov/node/762",
    "fda_ffr": "https://www.fda.gov/food/hfp-constituent-updates/fda-reminds-food-facilities-biennial-renewal-requirements",
    "us_pasta_ad": "https://www.trade.gov/final-results-antidumping-duty-administrative-review-certain-pasta-italy",
    "usda_dairy": "https://www.fas.usda.gov/programs/dairy-import-licensing-program",
    "cfia_sfc": "https://inspection.canada.ca/en/food-licences/importing-food",
    "gac_cheese": "https://www.international.gc.ca/controls-controles/prod/agri/dairy-laitiers/notices-avis/909.aspx?lang=eng",
    "ca_rawcheese": "https://cscb.ca/en/article/new-requirements-aged-unpasteurized-cheese-italy",
    "lucid": "https://www.verpackungsregister.org/en/faq-detail-category/questions-about-registration",
    # France (added 2 Nov 2026)
    "fr_lang": "https://www.legifrance.gouv.fr/loda/id/LEGITEXT000005616341",
    "fr_infotri": "https://www.adelphe.fr/sites/default/files/Documents/2025-10/adelphe_guide_info-tri_fr.pdf",
    "fr_excise": "https://www.douane.gouv.fr/fiche/droits-des-alcools-et-boissons-alcooliques",
    # Spain, Netherlands, Belgium, Austria (added 2 Nov 2026)
    "es_lang": "https://www.aesan.gob.es/en/AECOSAN/web/seguridad_alimentaria/subdetalle/norma_general_etiquetado.htm",
    "es_pack": "https://www.miteco.gob.es/es/calidad-y-evaluacion-ambiental/temas/prevencion-y-gestion-residuos/registro-productores-producto/registro-productores-producto-seccion-envases.html",
    "es_wine_tax": "https://www.boe.es/buscar/act.php?id=BOE-A-1992-28741",
    "nl_lang": "https://zoek.officielebekendmakingen.nl/stb-2013-146.pdf",
    "nl_pack": "https://ondernemersplein.overheid.nl/wetten-en-regels/afvalbeheersbijdrage-verpakkingen-betalen/",
    "nl_excise": "https://download.belastingdienst.nl/douane/docs/tarievenlijst-accijns-acc0552z95fd.pdf",
    "be_pack": "https://www.ucm.be/emballages",
    "at_pack": "https://www.wko.at/noe/up/verpackungsverordnung-auslaendische-haendler-lieferanten",
    # Switzerland (added 2 Nov 2026)
    "ch_origin": "https://trade.ec.europa.eu/access-to-markets/en/roo-explain-term/origin/CH/destination/IT/term/statementOrigin",
    "ch_label": "https://www.kmu.admin.ch/kmu/en/home/savoir-pratique/gestion-pme/etiquetage/etiqueter-les-denrees-alimentaires.html",
    "ch_geb": "https://importlicensing.wto.org/content/agricultural-products-general-import-permit-gip",
    "ch_vet": "https://www.blv.admin.ch/blv/en/home/import-und-export/import/importe-aus-der-eu.html",
    "ch_tariff": "https://xtares.admin.ch/tares/login/loginFormFiller.do?l=en",
    "ch_wine_tax": "https://www.bazg.admin.ch/de/besteuerung-alkoholische-getraenke-schweiz",
    "at_wine_tax": "https://www.usp.gv.at/themen/steuern-finanzen/weitere-steuern-und-abgaben/verbrauchsteuern_und_energieabgaben/wein_schaumwein_verbrauchsteuerrechtliche_bestimmungen.html",
    # REX threshold, official EU sources (replaced a courier page on 2 Nov 2026)
    "rex_uk": "https://taxation-customs.ec.europa.eu/system/files/2021-03/compendium_on_rules_of_origin_q_a.pdf",
    "rex_ca": "https://trade.ec.europa.eu/access-to-markets/en/roo-explain-term/origin/CA/destination/FR/term/statementOrigin",
}


# Pages people read are not always readable by the daily job: some official sites refuse requests from
# cloud servers (checked from Google Cloud on 2 Nov 2026). For those, the job watches an official source
# for the same rule instead. Clients still see the page in SRC.
WATCH = {
    # USDA FAS page answers 403 to cloud servers: watch the regulation's amendment list (eCFR official API).
    "usda_dairy": "https://www.ecfr.gov/api/versioner/v1/versions/title-7.json?part=6",
    # CFIA page answers 404 to cloud servers: watch the Safe Food for Canadians Regulations.
    "cfia_sfc": "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2018-108/",
}


def watch_url(source):
    """The URL the daily job checks for a given client-facing source."""
    for k, url in SRC.items():
        if url == source and k in WATCH:
            return WATCH[k]
    return source


def _r(rid, layer, it, en, who, conf, products=ALL_P, dests=ALL_D, src=None, doc=None, only_it=None, only_en=None,
       note_it=None, note_en=None):
    return {"id": rid, "layer": layer, "it": it, "en": en, "who": who, "conf": conf, "products": products,
            "dests": dests, "source": SRC.get(src) if src else None, "doc_type": doc,
            "only_if": {"it": only_it, "en": only_en} if only_en else None,
            "note": {"it": note_it, "en": note_en} if note_en else None}


ROWS = [
    # 1. Company
    _r("eori", 1, "Numero EORI italiano", "Italian EORI number", "customs", "A", dests=NON_EU, doc="tax_ids"),
    _r("food_reg", 1, "Registrazione impresa alimentare (SCIA all'ASL)", "Food business registration (SCIA to ASL)",
       "asl", "C", doc="facility_approval"),
    _r("rex", 1, "Registrazione REX (esportatore registrato)", "REX registration (registered exporter)", "customs", "A",
       dests={"UK"}, src="rex_uk", only_it="spedizioni oltre 6.000 euro, per il dazio zero",
       only_en="consignments over EUR 6,000, for 0% duty"),
    _r("rex", 1, "Registrazione REX (esportatore registrato)", "REX registration (registered exporter)", "customs", "A",
       dests={"CA"}, src="rex_ca", only_it="spedizioni oltre 6.000 euro, per il dazio zero",
       only_en="consignments over EUR 6,000, for 0% duty"),
    _r("approved_exporter", 1, "Esportatore autorizzato (dichiarazione di origine oltre 6.000 euro)",
       "Approved exporter status (origin declaration over EUR 6,000)", "customs", "B", dests={"CH"}, src="ch_origin",
       only_it="spedizioni oltre 6.000 euro, per il dazio preferenziale", only_en="consignments over EUR 6,000, for preferential duty",
       note_it="In alternativa: certificato EUR.1 dalla dogana", note_en="Alternative: EUR.1 certificate from customs"),
    _r("est_number", 1, "Numero di riconoscimento CE dello stabilimento (bollo sanitario)",
       "EU-approved establishment number (oval health mark)", "asl", "C", products={"cheese"}, doc="facility_approval"),
    _r("vies", 1, "Iscrizione al VIES (operazioni intracomunitarie)", "VIES enrolment (intra-EU trade)", "exporter", "B",
       dests=EU_D, note_it="Gratuita, tramite l'Agenzia delle Entrate. MioTEM la controlla in automatico",
       note_en="Free, through the Agenzia delle Entrate. MioTEM checks it automatically"),
    _r("excise_auth", 1, "Deposito fiscale o rappresentante fiscale accise", "Excise tax warehouse or excise representative",
       "customs", "C", products={"wine"}),

    # 2. Product labels
    _r("label_uk", 2, "Etichetta UK in inglese con nome e indirizzo dell'importatore UK",
       "UK label in English with the UK importer's name and address", "exporter", "A", dests={"UK"}, src="uk_label",
       doc="label"),
    _r("label_uk_wine", 2, "Etichetta vino con indirizzo dell'importatore o imbottigliatore UK",
       "Wine label with UK importer or bottler address", "exporter", "B", products={"wine"}, dests={"UK"},
       src="uk_wine_label"),
    _r("label_uk_oil", 2, "Denominazione della categoria dell'olio in etichetta", "Olive oil category name on the label",
       "exporter", "C", products={"oil"}, dests={"UK"}),
    _r("label_us", 2, "Etichetta conforme FDA (inglese, Nutrition Facts, allergeni)",
       "FDA-compliant label (English, Nutrition Facts, allergens)", "exporter", "C", products={"pasta", "oil", "cheese"},
       dests={"US"}, doc="label"),
    _r("cola", 2, "COLA: approvazione TTB di ogni etichetta", "COLA: TTB approval for each label", "importer", "A",
       products={"wine"}, dests={"US"}, src="ttb", note_it="Stampare le etichette solo dopo l'approvazione",
       note_en="Print export labels only after approval"),
    _r("label_ca", 2, "Etichetta bilingue (inglese e francese) con tabella nutrizionale canadese e importatore",
       "Bilingual label (English and French) with Canadian Nutrition Facts and importer", "exporter", "C",
       dests={"CA"}, doc="label", note_it="Verificare il simbolo nutrizionale sul fronte",
       note_en="Check the front-of-package nutrition symbol rules"),
    _r("label_de", 2, "Etichetta con le informazioni obbligatorie in tedesco (Reg. UE 1169/2011)",
       "Label with mandatory information in German (EU Reg. 1169/2011)", "exporter", "C", dests={"DE", "AT"}, doc="label"),
    _r("label_fr", 2, "Etichetta con le informazioni obbligatorie in francese (legge Toubon, Reg. UE 1169/2011)",
       "Label with mandatory information in French (Toubon law, EU Reg. 1169/2011)", "exporter", "B", dests={"FR"},
       src="fr_lang", doc="label", note_it="Altre lingue ammesse in aggiunta al francese",
       note_en="Other languages allowed in addition to French"),
    _r("label_ch", 2, "Etichetta in almeno una lingua ufficiale svizzera (italiano ammesso) con paese di produzione",
       "Label in at least one Swiss official language (Italian allowed) with country of production", "exporter", "B",
       dests={"CH"}, src="ch_label", doc="label",
       note_it="La Svizzera chiede il paese di produzione e l'origine degli ingredienti più spesso dell'UE",
       note_en="Switzerland asks for country of production and ingredient origin more often than the EU"),
    _r("label_es", 2, "Etichetta con le informazioni obbligatorie almeno in spagnolo (RD 1334/1999, art. 18)",
       "Label with mandatory information at least in Spanish (RD 1334/1999, art. 18)", "exporter", "A", dests={"ES"},
       src="es_lang", doc="label", note_it="Ammessi adesivi in spagnolo", note_en="Spanish stickers are allowed"),
    _r("label_nl", 2, "Etichetta con le informazioni obbligatorie almeno in olandese",
       "Label with mandatory information at least in Dutch", "exporter", "B", dests={"NL"}, src="nl_lang", doc="label",
       note_it="Nel 2025 il Parlamento ha chiesto di abolire l'obbligo: verificare che sia ancora in vigore",
       note_en="Parliament asked in 2025 to drop this rule: check it still applies"),
    _r("label_be", 2, "Etichetta nella lingua della regione linguistica di vendita (olandese, francese, tedesco)",
       "Label in the language of the linguistic region where sold (Dutch, French, German)", "exporter", "C",
       dests={"BE"}, doc="label", note_it="Vendita in tutto il Belgio: olandese, francese e tedesco",
       note_en="Sold across Belgium: Dutch, French and German"),
    _r("triman", 2, "Logo Triman e Info-tri sull'imballaggio", "Triman logo and Info-tri sorting label on the packaging",
       "exporter", "B", products={"pasta", "oil", "cheese"}, dests={"FR"}, src="fr_infotri",
       note_it="Obbligatori dal 2022 sugli imballaggi venduti ai consumatori in Francia",
       note_en="Mandatory since 2022 on consumer packaging sold in France"),
    _r("triman", 2, "Logo Triman e Info-tri sull'imballaggio", "Triman logo and Info-tri sorting label on the packaging",
       "exporter", "B", products={"wine"}, dests={"FR"}, src="fr_infotri",
       only_it="vino non in bottiglia di vetro (es. bag-in-box)", only_en="wine not in glass bottles (for example bag-in-box)",
       note_it="Le bottiglie di vetro per bevande sono escluse", note_en="Glass beverage bottles are excluded"),
    _r("label_de_wine", 2, "Etichetta vino UE: ingredienti e valori nutrizionali (anche via QR)",
       "EU wine label: ingredients and nutrition (QR code allowed)", "exporter", "C", products={"wine"}, dests=EU_D),
    _r("label_de_oil", 2, "Etichetta secondo le norme UE di commercializzazione dell'olio (categoria, origine)",
       "Label to EU olive oil marketing standards (category, origin)", "exporter", "C", products={"oil"}, dests=EU_D),
    _r("raw_milk_label", 2, "Dicitura \"prodotto con latte crudo\"", "\"Made with raw milk\" statement", "exporter", "C",
       products={"cheese"}, dests=EU_D, only_it="formaggio a latte crudo", only_en="raw milk cheese"),
    _r("raw_milk_age_us", 2, "Formaggio a latte crudo stagionato almeno 60 giorni", "Raw milk cheese aged at least 60 days",
       "exporter", "C", products={"cheese"}, dests={"US"}, only_it="formaggio a latte crudo", only_en="raw milk cheese"),
    _r("raw_milk_age_ca", 2, "Formaggio a latte crudo: stagionatura minima canadese",
       "Raw milk cheese: Canadian minimum ageing rule", "exporter", "B", products={"cheese"}, dests={"CA"},
       only_it="formaggio a latte crudo", only_en="raw milk cheese"),

    # 3. Destination
    _r("fda_ffr", 3, "Registrazione FDA dello stabilimento, con US agent", "FDA food facility registration, with US agent",
       "exporter", "A", dests={"US"}, src="fda_ffr",
       note_it="Rinnovo 2026 entro il 31 dicembre 2026, altrimenti scade",
       note_en="2026 renewal due by 31 December 2026, or it expires"),
    _r("fsvp", 3, "Informazioni FSVP per l'importatore", "FSVP supplier information for the importer", "importer", "C",
       products={"pasta", "oil", "cheese"}, dests={"US"}),
    _r("ttb_permit", 3, "Permesso TTB (Federal Basic Importer's Permit) dell'importatore",
       "Importer holds a TTB Federal Basic Importer's Permit", "importer", "A", products={"wine"}, dests={"US"}, src="ttb"),
    _r("ttb_cert", 3, "Certificato di eta o di origine, se richiesto da TTB per il tipo di vino",
       "Certificate of age or origin, where TTB requires it for the wine type", "exporter", "A", products={"wine"},
       dests={"US"}, src="ttb", doc="certificate"),
    _r("us_state", 3, "Regole di distribuzione dello stato USA", "US state distribution rules", "importer", "B",
       products={"wine"}, dests={"US"}),
    _r("usda_dairy", 3, "Licenza USDA di importazione lattiero-casearia (dazio in quota)",
       "USDA dairy import licence (lower in-quota duty)", "importer", "A", products={"cheese"}, dests={"US"},
       src="usda_dairy", note_it="Senza licenza si applica il dazio fuori quota",
       note_en="Without it the higher over-quota duty applies"),
    _r("aphis", 3, "Verifica sanitaria animale USA (APHIS)", "US animal health check (APHIS)", "staff", "C",
       products={"cheese"}, dests={"US"}),
    _r("us_pasta_ad", 3, "Dazi antidumping e compensativi sulla pasta italiana (aliquota per azienda)",
       "Antidumping and countervailing duties on pasta from Italy (company-specific rate)", "staff", "A",
       products={"pasta"}, dests={"US"}, src="us_pasta_ad",
       note_it="Incide sul costo di sbarco, non sui documenti", note_en="Affects landed cost, not documents"),
    _r("sfc", 3, "Licenza SFC (Safe Food for Canadians) dell'importatore", "Importer's SFC (Safe Food for Canadians) licence",
       "importer", "A", products={"pasta", "oil", "cheese"}, dests={"CA"}, src="cfia_sfc"),
    _r("gac_permit", 3, "Permesso di importazione di Global Affairs Canada (titolare quota CETA formaggi)",
       "Global Affairs Canada import permit (CETA cheese quota holder)", "importer", "A", products={"cheese"},
       dests={"CA"}, src="gac_cheese"),
    _r("ca_zoo", 3, "Certificato zoosanitario per formaggio a latte crudo bovino o bufalino",
       "Zoosanitary certificate for raw milk cattle or buffalo cheese", "vet", "A", products={"cheese"}, dests={"CA"},
       src="ca_rawcheese", doc="certificate", only_it="latte crudo bovino o bufalino",
       only_en="raw cattle or buffalo milk",
       note_it="Dal 6 gennaio 2026. Prodotto prima del 23 maggio 2025: basta la prova della data",
       note_en="Since 6 January 2026. Made before 23 May 2025: proof of production date is enough"),
    _r("ca_liquor", 3, "Registrazione presso l'ente provinciale degli alcolici (es. analisi di laboratorio)",
       "Provincial liquor board listing and documents (for example lab analysis)", "exporter", "C",
       products={"wine"}, dests={"CA"}, doc="lab_analysis", note_it="Varia per provincia", note_en="Varies by province"),
    _r("ipaffs", 3, "Prenotifica IPAFFS", "IPAFFS pre-notification", "importer", "B", products={"cheese"}, dests={"UK"},
       src="uk_btom"),
    _r("uk_ehc", 3, "Certificato sanitario di esportazione firmato dal veterinario ufficiale",
       "Export health certificate signed by an official vet", "vet", "B", products={"cheese"}, dests={"UK"},
       src="uk_btom", doc="certificate", only_it="formaggio a latte crudo (es. Parmigiano Reggiano)",
       only_en="raw milk cheese (for example Parmigiano Reggiano)"),
    _r("uk_cheese_commercial", 3, "Documento commerciale", "Commercial document", "exporter", "B", products={"cheese"},
       dests={"UK"}, src="uk_btom", only_it="formaggio pastorizzato", only_en="pasteurised cheese"),
    _r("uk_composite", 3, "Documento commerciale per prodotto composito esente", "Commercial document for exempt composite product",
       "exporter", "A", products={"pasta"}, dests={"UK"}, src="uk_composite", only_it="pasta all'uovo",
       only_en="egg pasta"),
    _r("uk_duty", 3, "Accisa UK sugli alcolici", "UK alcohol duty", "importer", "C", products={"wine"}, dests={"UK"}),
    _r("lucid", 3, "Registrazione imballaggi (LUCID)", "Packaging registration (LUCID)", "buyer_de", "B", dests={"DE"},
       src="lucid", note_it="L'esportatore si registra solo se vende direttamente a utenti finali in Germania",
       note_en="The exporter registers only when selling directly to end users in Germany"),

    _r("fr_epr", 3, "Adesione a un eco-organismo francese per gli imballaggi (Citeo, Adelphe o Léko)",
       "Membership of a French packaging scheme (Citeo, Adelphe or Léko)", "buyer_fr", "B", dests={"FR"},
       src="fr_infotri", note_it="L'esportatore aderisce solo se vende direttamente a utenti finali in Francia",
       note_en="The exporter joins only when selling directly to end users in France"),
    _r("fr_excise", 3, "Accisa francese sul vino (destinatario: deposito autorizzato o destinatario registrato)",
       "French wine excise (consignee: authorised warehousekeeper or registered consignee)", "buyer_fr", "B",
       products={"wine"}, dests={"FR"}, src="fr_excise"),

    _r("ch_wine_reg", 3, "Iscrizione al Controllo svizzero del commercio dei vini e permesso generale d'importazione (PGI) dell'importatore",
       "Importer registered with Swiss Wine Trade Control and holding a general import permit (GIP)", "importer", "B",
       products={"wine"}, dests={"CH"}, src="ch_geb",
       note_it="Senza PGI il vino entra fuori contingente, con dazio molto più alto",
       note_en="Without a GIP the wine enters outside the tariff quota, at a much higher duty"),
    _r("ch_duty", 3, "Dazio svizzero all'importazione: verifica aliquota su Tares",
       "Swiss import duty: check the rate in Tares", "staff", "C", products={"pasta", "oil"}, dests={"CH"},
       src="ch_tariff", note_it="Pasta: prodotto agricolo trasformato, possibile componente agricola del dazio",
       note_en="Pasta: processed agricultural product, the duty may have an agricultural component"),
    _r("es_pack", 3, "Registro dei produttori di prodotto (imballaggi) e adesione a un sistema EPR spagnolo",
       "Spanish Producer Register (packaging) and membership of a Spanish packaging scheme", "buyer_eu", "B",
       dests={"ES"}, src="es_pack",
       note_it="Chi immette per primo il prodotto sul mercato spagnolo. Dal 12 agosto 2026 vale la definizione UE di produttore: verificare",
       note_en="Whoever first places the product on the Spanish market. EU producer definition applies from 12 August 2026: check"),
    _r("nl_pack", 3, "Contributo imballaggi a Verpact (ex Afvalfonds Verpakkingen)",
       "Packaging fee to Verpact (formerly Afvalfonds Verpakkingen)", "buyer_eu", "A", dests={"NL"}, src="nl_pack",
       only_it="oltre 50.000 kg di imballaggi l'anno", only_en="over 50,000 kg of packaging a year",
       note_it="L'esportatore paga solo se vende direttamente a consumatori nei Paesi Bassi",
       note_en="The exporter pays only when selling directly to consumers in the Netherlands"),
    _r("nl_excise", 3, "Accisa olandese sul vino", "Dutch wine excise", "buyer_eu", "A", products={"wine"},
       dests={"NL"}, src="nl_excise"),
    _r("be_pack", 3, "Adesione a Fost Plus (imballaggi domestici) o Valipac (imballaggi commerciali)",
       "Membership of Fost Plus (household packaging) or Valipac (commercial packaging)", "buyer_eu", "B",
       dests={"BE"}, src="be_pack", note_it="Responsabile: l'importatore dei prodotti imballati",
       note_en="Responsible: the importer of the packaged products"),
    _r("be_excise", 3, "Accisa belga sul vino (accisa e accisa speciale)", "Belgian wine excise (excise and special excise)",
       "buyer_eu", "C", products={"wine"}, dests={"BE"}),
    _r("at_pack", 3, "Licenza imballaggi presso un sistema austriaco di raccolta e riciclo",
       "Packaging licence with an Austrian collection and recovery system", "buyer_eu", "B", dests={"AT"},
       src="at_pack", note_it="Vendendo ad aziende austriache l'obbligo è dell'importatore. Vendendo a consumatori serve un rappresentante autorizzato in Austria",
       note_en="When selling to Austrian businesses the importer is responsible. Selling to consumers needs an authorised representative in Austria"),

    # 4. Shipment
    _r("invoice", 4, "Fattura commerciale", "Commercial invoice", "exporter", "A", dests=NON_EU, doc="invoice"),
    _r("invoice_de", 4, "Fattura con partite IVA di venditore e acquirente (verifica VIES)",
       "Invoice with both VAT numbers (buyer checked in VIES)", "exporter", "C", dests=EU_D, doc="invoice"),
    _r("origin_stmt", 4, "Dichiarazione di origine in fattura", "Origin statement on the invoice", "exporter", "A",
       dests={"UK"}, src="rex_uk", note_it="Accordo UE-UK: dazio zero", note_en="EU-UK TCA: 0% duty"),
    _r("origin_stmt", 4, "Dichiarazione di origine in fattura (regole PEM)", "Origin declaration on the invoice (PEM rules)",
       "exporter", "B", dests={"CH"}, src="ch_origin", note_it="Accordo UE-Svizzera", note_en="EU-Switzerland agreement"),
    _r("origin_stmt", 4, "Dichiarazione di origine in fattura", "Origin statement on the invoice", "exporter", "A",
       dests={"CA"}, src="rex_ca", note_it="CETA: dazio zero", note_en="CETA: 0% duty"),
    _r("packing", 4, "Packing list", "Packing list", "exporter", "A", dests=NON_EU, doc="packing_list"),
    _r("transport", 4, "Documento di trasporto (CMR, lettera di vettura aerea, polizza di carico)",
       "Transport document (CMR, air waybill, bill of lading)", "carrier", "A", doc="transport"),
    _r("export_decl", 4, "Dichiarazione doganale di esportazione (MRN)", "EU export declaration (MRN)", "agent", "C",
       dests=NON_EU, doc="customs"),
    _r("import_decl", 4, "Dichiarazione di importazione a destino", "Import declaration at destination", "importer", "C",
       dests=NON_EU),
    _r("prior_notice", 4, "Prior notice FDA per ogni spedizione", "FDA prior notice, every shipment", "importer", "B",
       dests={"US"}),
    _r("ead", 4, "e-AD (EMCS) dal deposito fiscale al punto di uscita UE", "e-AD (EMCS) from the tax warehouse to the EU exit",
       "warehouse", "C", products={"wine"}, dests=NON_EU),
    _r("ead_de", 4, "e-AD o documento di accompagnamento semplificato (accise)",
       "e-AD or simplified accompanying document (excise)", "warehouse", "C", products={"wine"}, dests=EU_D),
    _r("intrastat", 4, "Intrastat, se sopra la soglia", "Intrastat return, if over the threshold", "exporter", "C",
       dests=EU_D),
]

NOT_NEEDED = [
    {"products": {"wine"}, "dests": {"UK"}, "it": "Certificato VI-1: non serve (abolito dal 1 gennaio 2022)",
     "en": "VI-1 certificate: not needed (removed from 1 January 2022)", "source": SRC["uk_wine"]},
    {"products": {"wine"}, "dests": {"ES"}, "it": "Accisa spagnola sul vino: aliquota zero (restano le regole di circolazione, e-AD)",
     "en": "Spanish wine excise: zero rate (movement rules still apply, e-AD)", "source": SRC["es_wine_tax"]},
    {"products": {"cheese"}, "dests": {"CH"}, "it": "Certificato sanitario veterinario: di norma non serve (area veterinaria comune UE-Svizzera, nessun controllo alla frontiera)",
     "en": "Veterinary health certificate: normally not needed (EU-Swiss common veterinary area, no border checks)", "source": SRC["ch_vet"]},
    {"products": {"wine"}, "dests": {"CH"}, "it": "Accisa svizzera sul vino: nessuna (il vino fino a 18% vol non è tassato)",
     "en": "Swiss wine excise: none (wine up to 18% vol is not taxed)", "source": SRC["ch_wine_tax"]},
    {"products": {"wine"}, "dests": {"AT"}, "it": "Accisa austriaca sul vino: nessuna (restano le regole di circolazione, e-AD)",
     "en": "Austrian wine excise: none (movement rules still apply, e-AD)", "source": SRC["at_wine_tax"]},
]

CAVEAT = {"it": "Preparato da MioTEM, verificato dallo staff. Le voci segnate vanno ancora verificate.",
          "en": "Prepared by MioTEM, verified by staff. Marked items are still to be verified."}


def lane(category, country):
    """(product key, destination key) when the lane is in Wave 1, else None."""
    p = PRODUCTS.get((category or "").strip().lower())
    d = DESTINATIONS.get((country or "").strip().lower())
    return (p, d) if p and d else None


def covers(category, country):
    return lane(category, country) is not None


def required(category, country, on_file_types):
    """Checklist for one lane. on_file_types: set of docs.TYPES ids the client already has."""
    ln = lane(category, country)
    if not ln:
        return None
    p, d = ln
    items = []
    for r in ROWS:
        if p not in r["products"] or d not in r["dests"]:
            continue
        items.append({"id": r["id"], "layer": r["layer"], "it": r["it"], "en": r["en"], "who": WHO[r["who"]],
                      "importer_side": r["who"] in IMPORTER_SIDE, "verified": r["conf"] == "A",
                      "confidence": r["conf"], "source": r["source"], "only_if": r["only_if"], "note": r["note"],
                      "on_file": bool(r["doc_type"] and r["doc_type"] in on_file_types)})
    not_needed = [{"it": n["it"], "en": n["en"], "source": n["source"]} for n in NOT_NEEDED
                  if p in n["products"] and d in n["dests"]]
    return {"simulated": False, "source": "miotem_checklist", "checked": CHECKED,
            "data": {"lane": {"product": p, "destination": d}, "layers": LAYERS, "items": items,
                     "not_needed": not_needed, "caveat": CAVEAT}}
