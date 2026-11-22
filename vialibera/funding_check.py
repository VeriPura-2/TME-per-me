"""Eligibility check for funding schemes (F1, 22 Nov 2026).

Six questions per company (size, region, activity, single company or consortium, co-funding, destination from the project).
Each scheme gets: likely (likely eligible), check (check with the funder) or no (not eligible), with the reason.
A rule only fires on a fact in data/funding.json that has an official source and a check date. A fact we do not hold,
or an answer of "not sure", always gives "check", never a guess. The funder decides: the page says so.
"""
from . import db, funding

SIZES = ("micro", "small", "medium", "large", "not_sure")          # under 10, 10 to 49, 50 to 249, 250 or more (EU SME bands)
ACTIVITIES = ("farming", "processing", "trading", "not_sure")
APPLICANTS = ("company", "consortium", "not_sure")
COFUND = ("yes", "small", "no", "not_sure")
REGIONS = ("Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna", "Friuli-Venezia Giulia", "Lazio", "Liguria",
           "Lombardy", "Marche", "Molise", "Piedmont", "Apulia", "Sardinia", "Sicily", "Tuscany", "Trentino-Alto Adige",
           "Umbria", "Aosta Valley", "Veneto")
IT_NAMES = {"Lombardy": "Lombardia", "Piedmont": "Piemonte", "Tuscany": "Toscana", "Apulia": "Puglia", "Sardinia": "Sardegna",
            "Sicily": "Sicilia", "Aosta Valley": "Valle d'Aosta", "Verona province": "provincia di Verona",
            "Modena province": "provincia di Modena", "Reggio Calabria chamber area": "area della Camera di Reggio Calabria"}
AREA_REGION = {"Verona province": "Veneto", "Modena province": "Emilia-Romagna", "Reggio Calabria chamber area": "Calabria"}

R = {  # reasons, EN and IT
    "size_no": ("not for companies of your size", "non è per imprese della sua dimensione"),
    "region_no": ("only for companies in {where}", "solo per imprese in {where}"),
    "area_check": ("only for companies in {where}: check that yours is there", "solo per imprese in {where}: verifichi che la sua lo sia"),
    "farming_no": ("{funder} excludes companies mainly in primary agricultural production", "{funder} esclude le imprese di produzione agricola primaria"),
    "applicant_check": ("check who may apply: a single company or a consortium", "verifichi chi può presentare domanda: singola impresa o consorzio"),
    "cofund_check": ("this scheme pays {share} of the cost: the rest is yours", "questo bando copre il {share} del costo: il resto è a suo carico"),
    "missing": ("we do not hold the terms needed to check: {what}", "non abbiamo le condizioni necessarie per verificare: {what}"),
    "unsure": ("you answered not sure: {what}", "ha risposto non so: {what}"),
}
WHAT = {"size": ("size", "dimensione"), "region": ("region", "regione"), "activity": ("activity", "attività"),
        "applicant": ("who applies", "chi presenta domanda")}


def _r(key, **kw):
    en, it = R[key]
    return {"en": en.format(**{k: (v[0] if isinstance(v, tuple) else v) for k, v in kw.items()}),
            "it": it.format(**{k: (v[1] if isinstance(v, tuple) else v) for k, v in kw.items()})}


def evaluate(scheme, a):
    """(result, [reasons]) for one scheme and one set of answers."""
    facts = {k: v["value"] for k, v in scheme.get("facts", {}).items()}
    no, check = [], []
    if scheme.get("always_check"):
        check.append(dict(scheme["always_check"]))
    # size
    if "sizes" in facts:
        if a.get("size") in (None, "", "not_sure"):
            check.append(_r("unsure", what=WHAT["size"]))
        elif a["size"] not in facts["sizes"]:
            no.append(_r("size_no"))
    else:
        check.append(_r("missing", what=WHAT["size"]))
    # region
    regs = facts.get("regions")
    if regs and regs != "all":
        where = (", ".join(regs), ", ".join(IT_NAMES.get(x, x) for x in regs))
        need = {AREA_REGION.get(x, x) for x in regs}
        if not a.get("region"):
            check.append(_r("unsure", what=WHAT["region"]))
        elif a["region"] not in need:
            no.append(_r("region_no", where=where))
        elif any(x in AREA_REGION for x in regs):
            check.append(_r("area_check", where=where))
    elif not regs:
        check.append(_r("missing", what=WHAT["region"]))
    # activity
    if "excluded_ateco" in facts:
        if a.get("activity") == "farming" and "A" in facts["excluded_ateco"]:
            no.append(_r("farming_no", funder=scheme["funder"]))
        elif a.get("activity") in (None, "", "not_sure"):
            check.append(_r("unsure", what=WHAT["activity"]))
    # applicant
    app = facts.get("applicant")
    if a.get("applicant") in (None, "", "not_sure") or (app and a["applicant"] == "consortium" and "aggregation" not in app and "consortium" not in app):
        check.append(_r("applicant_check"))
    # co-funding: a grant that pays a share leaves the rest to the company
    share = facts.get("grant_share")
    if scheme.get("instrument") == "grant" and share and a.get("cofund") in ("small", "no", "not_sure"):
        check.append(_r("cofund_check", share=share))
    if no:
        return "no", no
    if check:
        return "check", check
    return "likely", []


def get_profile(con, key):
    r = con.execute("SELECT * FROM funding_profiles WHERE owner_key=?", (key,)).fetchone()
    return {k: r[k] for k in ("size", "region", "activity", "applicant", "cofund")} if r else None


def save_profile(con, key, who, body):
    a = {"size": body.get("size") if body.get("size") in SIZES else None,
         "region": body.get("region") if body.get("region") in REGIONS else None,
         "activity": body.get("activity") if body.get("activity") in ACTIVITIES else None,
         "applicant": body.get("applicant") if body.get("applicant") in APPLICANTS else None,
         "cofund": body.get("cofund") if body.get("cofund") in COFUND else None}
    con.execute("DELETE FROM funding_profiles WHERE owner_key=?", (key,))
    con.execute("INSERT INTO funding_profiles(owner_key, size, region, activity, applicant, cofund, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (key, a["size"], a["region"], a["activity"], a["applicant"], a["cofund"], who["user"], db.now()))
    con.commit()
    return a


def results(profile):
    """One line per scheme: open schemes first, then no fixed window, then check, then closed."""
    order = {"open": 0, "no_window": 1, "check": 2, "closed": 3}
    out = []
    for s in funding.schemes():
        res, why = evaluate(s, profile or {})
        out.append({"id": s["id"], "label": s["label"], "status": s["status"]["value"], "url": s["url"],
                    "checked": s["status"]["checked"], "result": res, "reasons": why})
    return sorted(out, key=lambda x: (order.get(x["status"], 9), {"likely": 0, "check": 1, "no": 2}[x["result"]]))


def may_fit(profile):
    """How many schemes that are open or have no fixed window may fit: the number on the line under Duties."""
    return sum(1 for x in results(profile) if x["status"] in ("open", "no_window") and x["result"] in ("likely", "check"))
