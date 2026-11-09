"""Request to a control body for an operator extract or verification (Valoritalia and Kiwa Cermet).

Staff or the TEM prepare the request from the company record; they send it themselves (the app sends no email) and then
record that it was sent and, later, that a reply arrived (uploaded in Documents). Nothing here decides or changes the
certification status: that stays "claimed" until staff or CORE have seen the reply.

Whether either body answers a request that is not made by the producer is not established, so a request is only
prepared once the producer's consent is recorded, and the text is written as the producer's own request.
"""
import uuid

from . import db, docs, masaf

STATES = ("prepared", "sent", "reply_received")

# Only what a public page showed (research of 9 Nov 2026). The form addresses are the pages that carry the forms.
BODIES = {
    "kiwa": {"form": "Richiesta verifica operatori DOP-IGP", "page": "https://www.kiwa.com/it/it/servizi/certificazione/dop-igp-stg/",
             "asks": "name, email, VAT or CUAA, company, address, products, notes"},
    "valoritalia": {"form": "Richiesta estratto elenco degli operatori DOP/IGP/STG", "page": "https://www.valoritalia.it/",
                    "asks": "see the request menu on the site"},
}

NOTE = {
    "it": "Bozza dai dati dell'azienda. La invia l'azienda o lo staff con il suo consenso. Non è una verifica e non cambia lo stato della certificazione.",
    "en": "Draft from the company record. The company or staff send it with the company's consent. It is not a verification and does not change the certification status.",
}


def _clean(v, n=300):
    return str(v).strip()[:n] if v not in (None, "") else ""


def prefill(case):
    co, pr = case.get("company") or {}, case.get("product") or {}
    vals = {"company": _clean(co.get("legal_name")), "vat": _clean(co.get("vat_number")),
            "address": _clean(co.get("address_region")), "contact": _clean(co.get("contact")),
            "product": _clean(pr.get("name_brand")), "denomination": _clean(pr.get("denomination") or pr.get("appellation"))}
    return vals, [k for k in ("company", "vat", "address", "denomination") if not vals[k]]


def text_it(vals, body_name, wine):
    what = "l'estratto dell'elenco degli operatori" if wine else "la verifica della posizione di operatore"
    return (f"Oggetto: Richiesta di {what} - {vals['denomination'] or '[denominazione]'}\n\n"
            f"Gentili signori,\n\nla società {vals['company'] or '[ragione sociale]'} (partita IVA {vals['vat'] or '[partita IVA]'}, "
            f"sede: {vals['address'] or '[indirizzo]'}) produce {vals['product'] or '[prodotto]'} a denominazione {vals['denomination'] or '[denominazione]'}. "
            f"Con il consenso della società chiediamo a {body_name} {what}, e di indicare le modalità, i tempi e gli eventuali costi del rilascio "
            f"di un attestato ufficiale che la società possa mostrare ai propri acquirenti esteri.\n\n"
            f"Contatto: {vals['contact'] or '[contatto]'}\n\nCordiali saluti")


def _row(r):
    return {k: r[k] for k in r.keys()}


def listing(con, case_id):
    return [_row(r) for r in con.execute("SELECT * FROM cert_requests WHERE case_id=? ORDER BY created_at DESC", (case_id,))]


def info(con, case_row, lang="it"):
    case = db.case_read(con, case_row["id"])
    vals, missing = prefill(case)
    bodies, seen = [], set()
    for r in (masaf.describe(vals["denomination"])["found"] if vals["denomination"] else []):
        if r["body_id"] in seen:
            continue
        seen.add(r["body_id"])
        b = BODIES.get(r["body_id"])
        bodies.append({"body_id": r["body_id"], "name": r["control_body"], "supported": bool(b), "email": r["email"], "web": r["web"],
                       "form": b["form"] if b else None, "page": b["page"] if b else None, "list_date": r["list_date"],
                       "text": text_it(vals, r["control_body"], r["sector"] == "wine") if b else None})
    return {"denomination": vals["denomination"], "fields": vals, "missing": missing, "bodies": bodies,
            "requests": listing(con, case_row["id"]), "note": NOTE["en" if lang == "en" else "it"],
            "source": "MASAF registers of authorised control bodies"}


def prepare(con, case_row, who_sub, body_id, consent):
    if body_id not in BODIES:
        return {"error": "this body is not supported yet"}
    if not consent:
        return {"error": "the producer's consent is required before a request is prepared"}
    case = db.case_read(con, case_row["id"])
    vals, missing = prefill(case)
    if missing:
        return {"error": "missing in the company record: " + ", ".join(missing)}
    ok = [r for r in masaf.describe(vals["denomination"])["found"] if r["body_id"] == body_id]
    if not ok:
        return {"error": "MASAF does not list this body for that name"}
    t, rid = db.now(), str(uuid.uuid4())
    con.execute("INSERT INTO cert_requests(id, case_id, company_id, body_id, body_name, denomination, state, consent, prepared_by, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rid, case_row["id"], case_row["company_id"], body_id, ok[0]["control_body"], vals["denomination"], "prepared", 1,
                 who_sub, t, t))
    con.commit()
    db.log_event(con, case_row["id"], who_sub, "cert_request", {"id": rid, "state": "prepared", "body": body_id, "denomination": vals["denomination"]})
    return {"ok": True, "request_id": rid}


def set_state(con, who, case_row, request_id, state, doc_id=None):
    """prepared -> sent -> reply_received, in that order. The reply may name an uploaded document."""
    r = con.execute("SELECT * FROM cert_requests WHERE id=? AND case_id=?", (request_id, case_row["id"])).fetchone()
    if r is None:
        return {"error": "request not found"}
    order = {s: i for i, s in enumerate(STATES)}
    if state not in order or order[state] != order[r["state"]] + 1:
        return {"error": f"a request goes from {r['state']} to {STATES[min(order[r['state']] + 1, 2)]} only"}
    t, sub = db.now(), who["user"]
    if state == "sent":
        con.execute("UPDATE cert_requests SET state=?, sent_by=?, sent_at=?, updated_at=? WHERE id=?", (state, sub, t, t, request_id))
    else:
        if doc_id and docs.get_doc(con, doc_id, who) is None:
            return {"error": "document not found"}
        con.execute("UPDATE cert_requests SET state=?, reply_by=?, reply_at=?, doc_id=?, updated_at=? WHERE id=?",
                    (state, sub, t, doc_id or None, t, request_id))
    con.commit()
    db.log_event(con, case_row["id"], sub, "cert_request", {"id": request_id, "state": state, "doc_id": doc_id})
    return {"ok": True}
