"""VAT number checks for client companies: Italian only, check digit, and the EU VIES service.

VIES (European Commission, free) confirms a number and returns the registered name and address.
In Italy a VAT number is in VIES only when the business has opted in for intra-EU trade, so
"not in VIES" never means the number is fake: the company is accepted, flagged for staff, and
told how to enrol (free, through the Agenzia delle Entrate). When VIES does not answer, the
company is accepted and the daily job tries again.
"""
import json
import urllib.error
import urllib.request

from . import accounts, db

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/IT/vat/{num}"
ITALY_ONLY = {"it": "MioTEM è per le aziende italiane: serve una partita IVA italiana.",
              "en": "MioTEM is for Italian companies: an Italian VAT number (partita IVA) is needed."}

ENROL = {
    "it": ["La tua partita IVA non risulta nell'archivio VIES. Serve per vendere ad aziende di altri paesi UE (per esempio la Germania) senza IVA italiana.",
           "L'iscrizione è gratuita e immediata. Accedi all'area riservata dell'Agenzia delle Entrate (Fisconline, SPID o CIE), "
           "poi Servizi, Comunicazioni, \"Comunicare istanza di inclusione nell'archivio VIES\", e indica la tua partita IVA. "
           "Puoi farlo anche tramite il tuo commercialista.",
           "MioTEM ricontrolla il VIES ogni giorno e aggiorna lo stato da solo."],
    "en": ["Your VAT number is not in the VIES archive. You need it to sell to businesses in other EU countries (for example Germany) without Italian VAT.",
           "Enrolment is free and immediate. Sign in to the Agenzia delle Entrate reserved area (Fisconline, SPID or CIE), "
           "then Services, Communications, \"Comunicare istanza di inclusione nell'archivio VIES\", and enter your VAT number. "
           "Your commercialista can also do it for you.",
           "MioTEM re-checks VIES every day and updates the status by itself."],
}
ENROL_LINK = "https://www.agenziaentrate.gov.it/portale/web/guest/area-riservata"


def italian(raw):
    """(vat, error) for a client company: check digit as before, and Italian only."""
    vat, err = accounts.normalise_vat(raw)
    if err:
        return None, err
    if not vat.startswith("IT"):
        return None, ITALY_ONLY["en"]
    return vat, None


def _http(url, timeout=8):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with db.outside_call(), urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def _http_now():
    return _http  # looked up at call time, so tests can switch the network off


def vies(vat, http=None):
    """{"state": valid | not_in_vies | unavailable, "name", "address", "checked_at"}. Never raises."""
    out = {"state": "unavailable", "name": None, "address": None, "checked_at": db.now()}
    try:
        d = json.loads((http or _http_now())(VIES_URL.format(num=vat[2:])))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return out
    if d.get("isValid") is True:
        clean = lambda v: None if not v or v.strip() in ("---", "") else " ".join(v.split())
        out.update(state="valid", name=clean(d.get("name")), address=clean(d.get("address")))
    elif d.get("isValid") is False and d.get("userError") in ("VALID", "INVALID", None):
        out["state"] = "not_in_vies"
    return out  # any other userError (member state down, rate limit) stays "unavailable"


def apply(con, company_id, res, actor="system"):
    """Store the VIES answer. A valid answer marks the company VAT-verified."""
    con.execute("UPDATE companies SET vies_state=?, vies_name=?, vies_address=?, vies_checked_at=? WHERE id=?",
                (res["state"], res["name"], res["address"], res["checked_at"], company_id))
    if res["state"] == "valid":
        con.execute("UPDATE companies SET status='verified' WHERE id=? AND status='unverified'", (company_id,))
    con.commit()
    db.log_event(con, None, actor, "vies_check", {"company": company_id, "state": res["state"]})
    return res


def check_company(con, company_id, http=None):
    row = con.execute("SELECT vat FROM companies WHERE id=?", (company_id,)).fetchone()
    if row is None or not str(row["vat"]).startswith("IT"):
        return None
    return apply(con, company_id, vies(row["vat"], http))


def lookup(raw, http=None):
    """For pre-filling a form: validate, then ask VIES. Returns (status, body)."""
    vat, err = italian(raw)
    if err:
        return 400, {"error": "invalid_vat", "detail": err}
    return 200, {"vat": vat, **vies(vat, http)}


def apply_to_checklist(con, company_id, req):
    """The VIES checklist item is on file when VIES confirms the company."""
    if not req or not company_id:
        return req
    r = con.execute("SELECT vies_state FROM companies WHERE id=?", (company_id,)).fetchone()
    for i in req["data"]["items"]:
        if i["id"] == "vies" and r and r["vies_state"] == "valid":
            i["on_file"], i["verified"] = True, True
    return req
