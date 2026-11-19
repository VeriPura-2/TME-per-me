"""Reading a Core answer: what was read from the document, and what a control body confirmed.

Core's answer has no separate field for this yet. The two facts are only in the alert text, for example
"Read from the uploaded certificate and confirmed by the control body: ..." or
"Read from the uploaded certificate; NOT confirmed by the control body (...)". Until Core adds a field
(asked of VeriPura), this module reads the wording. If an alert carries a "basis" field it wins over the
wording: "read", "confirmed" or "not_confirmed".

Rules that never bend: "confirmed" appears only when an alert says so in words or by basis. Nothing is
inferred from a green status. A document with no such alert shows "no control body check reported".
Every original alert is still shown next to these lines.
"""
import re

NOT_CONF = re.compile(r"\bnot\s+confirmed\b|\bnon\s+confermat", re.I)
CONF = re.compile(r"\bconfirmed\s+by\b|\bconfermat[oa]\s+da\b", re.I)
READ = re.compile(r"\bread\s+from\b|\bletto\s+da\b", re.I)
NOSPEC = re.compile(r"no specialist check ran", re.I)

# plain-language flags, found by keyword in the alert text. The original alert is always shown too.
FLAGS = (
    ("no_specialist", NOSPEC,
     {"it": "Nessun controllo specialistico eseguito: il risultato non è un esito positivo. Indicare il tipo di documento.",
      "en": "No specialist check ran: this result is not a pass. Set the document type."}),
    ("plant_not_active", re.compile(r"\b(sospes[oa]|terminat[oa]|chius[oa]|auto-?sospes[oa]|suspended|closed|terminated)\b", re.I),
     {"it": "Almeno uno stabilimento o una scheda risulta sospeso o chiuso: verificare quale prima di spedire.",
      "en": "At least one plant or record is suspended or closed: check which one before shipping."}),
    ("expired", re.compile(r"\bexpired\b|\bscadut[oa]\b|\bwithdrawn\b|\bnot active\b", re.I),
     {"it": "Un certificato risulta scaduto o ritirato.", "en": "A certificate is expired or withdrawn."}),
    ("voluntary_scheme", re.compile(r"voluntary|volontari|fit to become|atto a divenire|not (a )?(dop|igp)\b", re.I),
     {"it": "Certificato di uno schema volontario: non prova lo stato DOP o IGP.",
      "en": "Voluntary scheme certificate: it does not prove DOP or IGP status."}),
    ("not_lot", re.compile(r"specific (wine )?lot|singolo lotto|tasting", re.I),
     {"it": "L'iscrizione all'elenco non prova che un singolo lotto abbia superato l'analisi.",
      "en": "Being on the list does not show that a given lot passed analysis."}),
)

LABEL = {
    "read_yes": {"it": "Letto dal documento", "en": "Read from the document"},
    "conf_yes": {"it": "Confermato dall'organismo di controllo", "en": "Confirmed by the control body"},
    "conf_no": {"it": "Non confermato dall'organismo di controllo", "en": "Not confirmed by the control body"},
    "conf_none": {"it": "Nessun controllo presso un organismo di controllo segnalato",
                  "en": "No control body check reported"},
}


def _texts(alerts):
    return [str(a.get("message") or "") for a in alerts or []]


def basis(alerts):
    """-> {"read": bool, "confirmed": "yes"|"no"|"none", "label": {...}, "flags": [...]} from the alert list."""
    read, conf = False, "none"
    for a in alerts or []:
        b = a.get("basis")
        m = str(a.get("message") or "")
        if b == "confirmed":
            conf = "yes" if conf != "no" else "no"
            read = True
        elif b == "not_confirmed":
            conf = "no"
        elif b == "read":
            read = True
        else:
            if NOT_CONF.search(m):
                conf = "no"
            elif CONF.search(m) and conf != "no":
                conf = "yes"
            if READ.search(m):
                read = True
    # one alert saying "not confirmed" beats another saying "confirmed": show the cautious fact
    flags = []
    seen = set()
    for kind, rx, label in FLAGS:
        if kind not in seen and any(rx.search(t) for t in _texts(alerts)):
            seen.add(kind)
            flags.append({"kind": kind, "label": label})
    return {"read": read, "confirmed": conf,
            "read_label": LABEL["read_yes"] if read else None,
            "confirmed_label": LABEL["conf_" + conf], "flags": flags}
