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


# F2: deadline list and email alerts ---------------------------------------------------------

import re
from datetime import date as _date

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def _share_pct(scheme):
    m = re.search(r"(\d+)\s*%", str(scheme.get("facts", {}).get("grant_share", {}).get("value") or ""))
    return int(m.group(1)) if m else None


def deadlines(profile, today=None):
    """Schemes that may fit and can be applied for: open with a sourced deadline (by date), then no fixed window.
    For companies under 10 people, the share the scheme pays comes first (less to cover themselves); a grant without a
    sourced share carries the label 'co-funding share not confirmed' and comes after."""
    today = today or _date.today()
    by = {s["id"]: s for s in funding.schemes()}
    out = []
    for x in results(profile):
        if x["result"] == "no" or x["status"] not in ("open", "no_window"):
            continue
        s = by[x["id"]]
        dl = s.get("facts", {}).get("deadline", {}).get("value")
        if x["status"] == "open" and (not dl or _date.fromisoformat(dl) < today):
            continue
        pct = _share_pct(s)
        out.append({"id": x["id"], "label": x["label"], "status": x["status"], "deadline": dl if x["status"] == "open" else None,
                    "checked": x["checked"], "url": x["url"], "result": x["result"],
                    "share_unconfirmed": s.get("instrument") == "grant" and pct is None, "share": pct})
    micro = (profile or {}).get("size") == "micro"
    key = (lambda d: (d["share_unconfirmed"], -(d["share"] or 0), d["deadline"] or "9999")) if micro else \
          (lambda d: (d["status"] != "open", d["deadline"] or "9999"))
    return sorted(out, key=key)


def get_alerts(con, key):
    r = con.execute("SELECT email, lang FROM funding_alerts WHERE owner_key=?", (key,)).fetchone()
    return {"on": bool(r)}


def set_alerts(con, key, who, on, email, lang):
    con.execute("DELETE FROM funding_alerts WHERE owner_key=?", (key,))
    if on:
        if not EMAIL.match(str(email or "")):
            con.commit()
            return 400, {"error": "email needed"}
        con.execute("INSERT INTO funding_alerts(owner_key, email, lang, set_by, set_at) VALUES (?,?,?,?,?)",
                    (key, str(email)[:254], "en" if lang == "en" else "it", who["user"], db.now()))
    con.commit()
    db.log_event(con, None, who["user"], "funding_alerts", {"on": bool(on)})
    return 200, {"ok": True, "on": bool(on)}


RESULT = {"likely": ("likely eligible", "probabilmente ammissibile"), "check": ("check with the funder", "da verificare con l'ente")}
MAIL = {
    "open": {"en": ("{scheme} is open", "Hello, {scheme} is now open, according to the official page we checked on {checked}: {link}\n"
                    "Your eligibility check shows: {result}. The funder decides.\n\nYou can stop these emails in MioTEM, under Financing in your project: {app}"),
             "it": ("{scheme} è aperto", "Buongiorno, {scheme} è ora aperto, secondo la pagina ufficiale verificata il {checked}: {link}\n"
                    "La sua verifica dei requisiti indica: {result}. Decide l'ente che finanzia.\n\nPuò interrompere queste email in MioTEM, alla voce Finanziamenti del suo progetto: {app}")},
    "deadline": {"en": ("{scheme} closes on {deadline}", "Hello, {scheme} closes on {deadline}, according to the official page we checked on {checked}: {link}\n"
                        "Your eligibility check shows: {result}. The funder decides.\n\nYou can stop these emails in MioTEM, under Financing in your project: {app}"),
                 "it": ("{scheme} chiude il {deadline}", "Buongiorno, {scheme} chiude il {deadline}, secondo la pagina ufficiale verificata il {checked}: {link}\n"
                        "La sua verifica dei requisiti indica: {result}. Decide l'ente che finanzia.\n\nPuò interrompere queste email in MioTEM, alla voce Finanziamenti del suo progetto: {app}")},
}


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fday(iso, lang):
    """18 Dec 2026 in English, 18/12/2026 in Italian."""
    try:
        d = _date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.day:02d}/{d.month:02d}/{d.year}" if lang == "it" else f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def send_alerts(con, base_url, send=None, today=None):
    """Daily job. Emails a subscribed company when a scheme that may fit turns open (staff changed the status after a
    check), and 14 and 3 days before a sourced deadline. Each email at most once (funding_alerts_sent)."""
    from . import notify
    send = send or notify.send_to
    today = today or _date.today()
    schemes = funding.schemes()
    seen = {r["scheme_id"]: r["status"] for r in con.execute("SELECT scheme_id, status FROM funding_seen").fetchall()}
    opened = {s["id"] for s in schemes if s["status"]["value"] == "open" and s["id"] in seen and seen[s["id"]] != "open"}
    sent = 0
    for sub in con.execute("SELECT * FROM funding_alerts").fetchall():
        prof = get_profile(con, sub["owner_key"])
        if not prof:
            continue
        lang = sub["lang"]
        fits = {x["id"]: x["result"] for x in results(prof) if x["result"] in ("likely", "check")}
        for s in schemes:
            if s["id"] not in fits or s["status"]["value"] != "open":
                continue
            dl = s.get("facts", {}).get("deadline", {}).get("value")
            todo = []
            if s["id"] in opened:
                todo.append(("open", s["status"]["checked"]))
            if dl:
                days = (_date.fromisoformat(dl) - today).days
                if 3 < days <= 14:
                    todo.append(("d14", dl))
                elif 0 <= days <= 3:
                    todo.append(("d3", dl))
            for kind, ref in todo:
                if con.execute("SELECT 1 FROM funding_alerts_sent WHERE owner_key=? AND scheme_id=? AND kind=? AND ref=?",
                               (sub["owner_key"], s["id"], kind, ref)).fetchone():
                    continue
                subj, body = MAIL["open" if kind == "open" else "deadline"][lang]
                v = {"scheme": s["label"][lang], "checked": fday(s["status"]["checked"], lang), "link": s["url"], "deadline": fday(dl, lang),
                     "result": RESULT[fits[s["id"]]][0 if lang == "en" else 1], "app": base_url.rstrip("/") + "/"}
                if send(sub["email"], subj.format(**v), body.format(**v)):
                    con.execute("INSERT INTO funding_alerts_sent(owner_key, scheme_id, kind, ref, sent_at) VALUES (?,?,?,?,?)",
                                (sub["owner_key"], s["id"], kind, ref, db.now()))
                    sent += 1
    for s in schemes:
        con.execute("DELETE FROM funding_seen WHERE scheme_id=?", (s["id"],))
        con.execute("INSERT INTO funding_seen(scheme_id, status, seen_at) VALUES (?,?,?)", (s["id"], s["status"]["value"], db.now()))
    con.commit()
    return {"funding_emails": sent}
