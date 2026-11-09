"""Parse the MASAF registers of control bodies into one lookup table.

Input: the public PDFs MASAF publishes (see SOURCES). Output: a list of rows
    denomination, category, kind (food/wine/stg), control_body, body_type, region
plus a contacts table for the bodies, and a refresh date.

This module only reads PDFs the person has downloaded. It makes no network calls
and no AI calls. pdfplumber is needed to REFRESH the data; the app itself only
reads the JSON file the refresh writes (vialibera/data/masaf_control_bodies.json).

A row here says who is authorised to control a name. It is not proof that any
producer is certified.
"""
import json
import re

CAT_RE = re.compile(r"^[DI]\.?[OG]\.?P\.?$", re.I)
INT_RE = re.compile(r"^\d{1,3}$")


def _lines(words, tol=3):
    """Group words into lines by their top coordinate."""
    out = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if out and abs(out[-1][0] - w["top"]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in out]


def _text(ws):
    return " ".join(w["text"] for w in sorted(ws, key=lambda w: (round(w["top"] / 4), w["x0"])))


def _norm(s):
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


def _blocks(words, gap=13.5):
    """Cluster left-column words into name blocks by vertical gap."""
    ws = sorted(words, key=lambda w: w["top"])
    blocks = []
    for w in ws:
        if blocks and w["top"] - blocks[-1][-1]["top"] <= gap:
            blocks[-1].append(w)
        else:
            blocks.append([w])
    return blocks


def parse_food(pdf):
    """Food register: body, n, denomination, category. Returns list of dicts."""
    rows, groups = [], []
    prev_body, kind = None, "public"
    for page in pdf.pages:
        words = page.extract_words(use_text_flow=True)
        cats = [w for w in words if CAT_RE.match(w["text"])]
        anchors = []
        for c in cats:
            same = [w for w in words if INT_RE.match(w["text"]) and abs(w["top"] - c["top"]) < 6 and w["x0"] < c["x0"]]
            if same:
                anchors.append((min(same, key=lambda w: w["x0"]), c))
        if not anchors:
            continue
        anchors.sort(key=lambda a: a[0]["top"])
        nx = min(a[0]["x0"] for a in anchors)
        cx0 = min(a[1]["x0"] for a in anchors)
        # denominations: words between the n column and the category column
        mids = [(anchors[i][0]["top"] + anchors[i + 1][0]["top"]) / 2 for i in range(len(anchors) - 1)]
        page_rows = []
        stars = [w["top"] for w in words if w["text"] == "*" and w["x0"] < nx - 20]
        ft = min(stars) - 1 if stars else 10_000  # footnote starts here
        cand = [w for w in words if w["top"] < ft and w["x1"] < cx0 + 1 and not CAT_RE.match(w["text"])
                and all(w is not n for n, _ in anchors)]
        owner = {}
        for w in cand:
            if w["x0"] <= nx + 6:
                continue
            k = min(range(len(anchors)), key=lambda j: abs(w["top"] - anchors[j][0]["top"]))
            if abs(w["top"] - anchors[k][0]["top"]) <= 16:
                owner.setdefault(k, []).append(w)
        for i, (n, c) in enumerate(anchors):
            den = owner.get(i, [])
            page_rows.append({"n": int(n["text"]), "top": n["top"], "den": _norm(_text(den)),
                              "cat": ".".join(re.sub(r"[^A-Z]", "", c["text"].upper())) + ".", "page": page.page_number})
        # groups of consecutive rows (n resets to 1 = new body)
        pgroups = []
        for r in page_rows:
            if r["n"] == 1 or not pgroups and not groups:
                pgroups.append([r])
            elif not pgroups:
                pgroups.append([r])
                pgroups[-1][0]["cont"] = True
            else:
                pgroups[-1].append(r)
        # name blocks: left column, not headings or footnotes
        left = [w for w in words if w["x1"] < nx - 4]
        heads, head_tops = [], set()
        last_top = anchors[-1][0]["top"]
        for t, ws in _lines(words):
            tx = _text(ws)
            if re.search(r"ORGANISMO DI CONTROLLO\s+n|AUTORITA' PUBBLICA\s+n|AUTORITA' PUBBLICHE|PRIVATI AUTORIZZATI|ELENCO delle|DENOMINAZIONE CONTROLLATA|^\*|transitoria\)", tx, re.I):
                head_tops.add(round(t))
                heads.append((t, tx))
            elif t > last_top + 30:
                head_tops.add(round(t))  # footnote below the last row
        tops = {id(w): round(t) for t, ws in _lines(left) for w in ws}
        namew = [w for w in left if tops.get(id(w)) not in head_tops]
        blocks = _blocks(namew)
        spans = [(g[0]["top"], g[-1]["top"] + 8) for g in pgroups]
        names = [[] for _ in pgroups]
        for b in blocks:
            cy = sum(w["top"] for w in b) / len(b) + 4
            def dist(s):
                return 0 if s[0] <= cy <= s[1] else min(abs(cy - s[0]), abs(cy - s[1]))
            k = min(range(len(spans)), key=lambda j: dist(spans[j]))
            names[k].append(_norm(_text(b)))
        # section markers (public vs private) by y order
        for gi, g in enumerate(pgroups):
            body = " ".join(names[gi]) if names[gi] else None
            if g[0].get("cont") and not body:
                body = prev_body
            for t, tx in heads:
                if t < g[0]["top"] and t > (pgroups[gi - 1][-1]["top"] if gi else -1):
                    if re.search(r"AUTORITA' PUBBLICHE", tx, re.I):
                        kind = "public"
                    elif re.search(r"PRIVATI AUTORIZZATI", tx, re.I):
                        kind = "private"
            for r in g:
                r["body"] = body
                r["body_type"] = kind
            prev_body = body
            groups.append(g)
        rows.extend(r for g in pgroups for r in g)
    return rows


WINE_CAT_RE = re.compile(r"^(DOC|DOCG|IGT|DOP|IGP)$")


def parse_wine(pdf):
    """Wine register (art. 64, L. 238/2016): body, n, denomination, region(s).

    Regions are merged cells in the PDF, so a region is attached to a row only
    when its group has exactly one region text; otherwise `region` is None and
    the group's texts are kept in `regions` (never guessed).
    """
    rows, prev_body = [], None
    for page in pdf.pages:
        words = [w for w in page.extract_words(use_text_flow=True, x_tolerance=1.5) if w["top"] >= 0]
        anchors = []
        for c in words:
            if WINE_CAT_RE.match(c["text"]) and 155 < c["x0"] < 175:
                same = [w for w in words if INT_RE.match(w["text"]) and abs(w["top"] - c["top"]) < 4 and w["x0"] < c["x0"]]
                if same:
                    anchors.append(max(same, key=lambda w: w["x0"]))
        hdr = [w["top"] for w in words if w["text"] == "CONTROLLATA"]
        y0 = max(hdr) + 5 if hdr else 0  # first pages carry a column header
        anchors.sort(key=lambda w: w["top"])
        owner = {}
        for w in words:
            if w["x0"] < 158 or w["x0"] > 365 or w["top"] < y0 or w in anchors:
                continue
            k = min(range(len(anchors)), key=lambda j: abs(w["top"] - anchors[j]["top"]))
            if abs(w["top"] - anchors[k]["top"]) <= 8:
                owner.setdefault(k, []).append(w)
        page_rows = [{"n": int(a["text"]), "top": a["top"], "den": _norm(_text(owner.get(i, []))),
                      "page": page.page_number} for i, a in enumerate(anchors)]
        groups = []
        for r in page_rows:
            if r["n"] == 1 or not groups:
                groups.append([r])
                if r["n"] != 1:
                    r["cont"] = True
            else:
                groups[-1].append(r)
        spans = [(g[0]["top"], g[-1]["top"] + 8) for g in groups]

        def assign(ws):
            out = [[] for _ in groups]
            for b in _blocks(ws, gap=11.5):
                cy = sum(w["top"] for w in b) / len(b) + 4
                k = min(range(len(spans)), key=lambda j: 0 if spans[j][0] <= cy <= spans[j][1]
                        else min(abs(cy - spans[j][0]), abs(cy - spans[j][1])))
                out[k].append(_norm(_text(b)))
            return out
        names = assign([w for w in words if w["x1"] < 140 and y0 < w["top"] < anchors[-1]["top"] + 14])
        regs = assign([w for w in words if w["x0"] > 366 and y0 < w["top"] < anchors[-1]["top"] + 14])
        for gi, g in enumerate(groups):
            body = " ".join(names[gi]) if names[gi] else (prev_body if g[0].get("cont") else None)
            for r in g:
                r["body"] = body
                r["regions"] = regs[gi]
                r["region"] = regs[gi][0] if len(regs[gi]) == 1 else None
            prev_body = body
        rows.extend(r for g in groups for r in g)
    return rows


WINE_BODY_KEYS = [
    ("valoritalia", "Valoritalia Srl"),
    ("rinaagrifood", "RINA Agrifood S.p.A. (ex Agroqualità)"),
    ("istitutoregionaledelvino", "IRVO - Istituto Regionale del Vino e dell'Olio"),
    ("ceviq", "CEVIQ - Certificazione Vini e Prodotti Italiani di Qualità Srl"),
    ("siquria", "Siquria Srl"),
    ("triveneta", "Triveneta Certificazioni Srl"),
    ("ccpb", "CCPB Srl"),
    ("tcasrl", "TCA Srl - Toscana Certificazione Agroalimentare"),
    ("3a-pta", "3A-PTA - Parco tecnologico agroalimentare dell'Umbria"),
    ("3apta", "3A-PTA - Parco tecnologico agroalimentare dell'Umbria"),
    ("ce.r.s.a.a", "Ce.R.S.A.A. - Area Made In Quality"),
    ("cersaa", "Ce.R.S.A.A. - Area Made In Quality"),
    ("ccia", None),  # chamber of commerce, resolved below
]


def canonical_wine_body(text):
    """Map the (letter-spaced, sometimes repeated) body text to one clean name."""
    if not text:
        return None
    flat = re.sub(r"\s+", "", text).lower()
    for key, name in WINE_BODY_KEYS:
        if key in flat:
            if name:
                return name
            if "bolzano" in flat:
                return "CCIAA di Bolzano (CCIATA)"
            if "trento" in flat:
                return "CCIAA di Trento (CCIATA)"
    return None


def parse_stg(pdf):
    """STG list: denomination -> one or more control bodies."""
    rows = []
    for page in pdf.pages:
        words = [w for w in page.extract_words(use_text_flow=True, x_tolerance=1.5) if w["top"] > 60]
        ints = [w for w in words if INT_RE.match(w["text"])]
        if not ints:
            continue
        nx = sorted(w["x0"] for w in ints)[len(ints) // 2]
        anchors = sorted((w for w in ints if abs(w["x0"] - nx) < 15), key=lambda w: w["top"])
        groups = []
        for a in anchors:
            if int(a["text"]) == 1 or not groups:
                groups.append([a])
            else:
                groups[-1].append(a)
        # body text: right of the n column, nearest anchor
        body = {}
        for w in words:
            if w["x0"] > nx + 10:
                k = min(range(len(anchors)), key=lambda j: abs(w["top"] - anchors[j]["top"]))
                if abs(w["top"] - anchors[k]["top"]) <= 12:
                    body.setdefault(id(anchors[k]), []).append(w)
        spans = [(g[0]["top"], g[-1]["top"] + 8) for g in groups]
        names = [[] for _ in groups]
        for b in _blocks([w for w in words if w["x1"] < nx - 4], gap=13.5):
            cy = sum(w["top"] for w in b) / len(b) + 4
            k = min(range(len(spans)), key=lambda j: 0 if spans[j][0] <= cy <= spans[j][1]
                    else min(abs(cy - spans[j][0]), abs(cy - spans[j][1])))
            names[k].append(_norm(_text(b)))
        for gi, g in enumerate(groups):
            den = " ".join(names[gi])
            for a in g:
                den = den.replace("DENOMINAZIONE CONTROLLATA", "").strip()
                rows.append({"denomination": den, "n": int(a["text"]),
                             "body": _norm(_text(body.get(id(a), [])))})
    return rows


def parse_contacts(pdf):
    """Contact tables (private control bodies, public authorities).

    One dict per body: name, email, pec, web. Only these columns are read:
    address and phone cells wrap and overlap in the PDF, so they are left out
    rather than risk wrong values. Placeholder dashes become None.
    """
    out, cols = [], None
    for page in pdf.pages:
        words = page.extract_words(x_tolerance=1.5)
        head = {w["text"].lower(): w for w in words if w["top"] < 90}
        mails = sorted((w for w in words if w["top"] < 90 and w["text"].lower().startswith("e-mail")), key=lambda w: w["x0"])
        addr = head.get("indirizzo") or head.get("address")
        if addr and len(mails) >= 2:
            cols = {"addr_x": addr["x0"], "pec_x": (mails[0]["x0"] + mails[1]["x0"]) / 2}
        if not cols:
            continue
        ymin = addr["top"] + 8 if addr else 0  # header only on the first page
        anchors = sorted((w for w in words if INT_RE.match(w["text"]) and w["x0"] < 60 and w["top"] > ymin), key=lambda w: w["top"])
        recs = {id(a): {"name": [], "email": [], "pec": [], "web": []} for a in anchors}
        for w in words:
            if w["top"] <= ymin or w in anchors or not anchors:
                continue
            k = min(range(len(anchors)), key=lambda j: abs(w["top"] - anchors[j]["top"]))
            if abs(w["top"] - anchors[k]["top"]) > 30:
                continue
            t = w["text"].strip(";,")
            if "@" in t:
                recs[id(anchors[k])]["pec" if w["x0"] >= cols["pec_x"] else "email"].append(t)
            elif t.lower().startswith(("http", "www")):
                recs[id(anchors[k])]["web"].append(t)
            elif w["x1"] < cols["addr_x"] - 5:
                recs[id(anchors[k])]["name"].append(w)
        for a in anchors:
            r = recs[id(a)]
            addrs = r["email"] + r["pec"]  # the PDF's two mail columns are told apart by the address itself
            pec = [x for x in addrs if re.search(r"pec|legalmail", x.split("@")[-1], re.I)]
            mail = [x for x in addrs if x not in pec]
            out.append({"n": int(a["text"]), "name": _clean_name(_norm(_text(r["name"]))) or None,
                        "email": "; ".join(mail) or None, "pec": "; ".join(pec) or None,
                        "web": " ".join(r["web"]) or None})
    return out


_STREET = {"via", "viale", "strada", "piazza", "sede", "reg.", "frazione", "corso", "c.so", "dei"}


def _clean_name(t):
    """Drop header text and street-type words that spill from the address column."""
    t = re.sub(r"^n\.\s*(Name|Nome)\s*", "", t)
    return " ".join(w for w in t.split() if w.lower() not in _STREET).strip()


# Short ids for the bodies. Matching is on the lower-case text with spaces removed.
BODY_IDS = [
    ("valoritalia", "valoritalia"), ("rinaagrifood", "rina"), ("agroqualit", "rina"), ("ccpb", "ccpb"),
    ("csqa", "csqa"), ("kiwa", "kiwa"), ("cermet", "kiwa"), ("ifcq", "ifcq"), ("ocq", "ocqpr"),
    ("organismocontrolloqualit", "ocqpr"), ("dqa", "dqa"), ("dipartimentoqualit", "dqa"),
    ("ecepa", "ecepa"), ("e.ce.p.a", "ecepa"), ("icea", "icea"), ("istitutoperlacertificazioneetica", "icea"),
    ("inoq", "inoq"), ("istitutonordovestqualit", "inoq"), ("toscanacertificazione", "tca"), ("tca", "tca"),
    ("certiprodop", "certiprodop"), ("bioagricert", "bioagricert"), ("bureauveritas", "bureauveritas"),
    ("sqk", "sqk"), ("controlloqualit\u00e0altoadige", "sqk"), ("controlloqualita'altoadige", "sqk"),
    ("sudtiroler", "sqk"), ("omnia", "omnia"), ("suoloesalute", "suolo"), ("ceviq", "ceviq"),
    ("siquria", "siquria"), ("triveneta", "triveneta"), ("sidel", "sidel"), ("abcert", "abcert"),
    ("agrovet", "agrovet"), ("3a", "3a-pta"), ("ce.r.s.a.a", "cersaa"), ("cersaa", "cersaa"),
    ("corfilcarni", "corfilcarni"), ("corfilac", "corfilac"), ("filierala", "corfilac"),
    ("istitutoregionaledelvino", "irvo"), ("i.r.v.o", "irvo"), ("zooprofilattico", "izs-sicilia"),
    ("i.z.s", "izs-sicilia"), ("enterisi", "enterisi"),
    ("bolzano", "cciaa-bolzano"), ("trento", "cciaa-trento"), ("bari", "cciaa-bari"), ("chieti", "cciaa-chieti-pescara"),
    ("genova", "cciaa-genova"), ("gransasso", "cciaa-gran-sasso"), ("lecce", "cciaa-lecce"), ("trapani", "cciaa-trapani"),
]


def body_id(text):
    """Return the short id for a body name as printed in a MASAF list, or None."""
    if not text:
        return None
    flat = re.sub(r"\s+", "", text).lower().replace("\u2019", "'")
    for key, ident in BODY_IDS:
        if key in flat:
            return ident
    return None


# The PDFs carry a list date in the title, but not a date per denomination.
SOURCE_KINDS = [
    ("vitivinicolo", "wine", "15 Jan 2026"),
    ("Elenco_STG", "stg", "7 Oct 2026"),
    ("privati", "contacts_private", "1 Jul 2026"),
    ("Autorit", "contacts_public", "16 Sep 2026"),
    ("Strutture_Controllo_DOP_IGP", "food", "no list date printed"),
]


def build(pdf_dir, refreshed):
    """Read the MASAF PDFs in pdf_dir and return the lookup table as a dict."""
    import os
    import pdfplumber
    found = {}
    for fn in sorted(os.listdir(pdf_dir)):
        for key, kind, _ in SOURCE_KINDS:
            if key.lower() in fn.lower() and fn.lower().endswith(".pdf") and kind not in found:
                found[kind] = fn
    missing = [k for _, k, _ in SOURCE_KINDS if k not in found]
    if missing:
        raise SystemExit("Missing MASAF PDFs for: " + ", ".join(missing))
    open_ = lambda k: pdfplumber.open(os.path.join(pdf_dir, found[k]))
    dates = {k: d for _, k, d in SOURCE_KINDS}
    rows = []
    for r in parse_food(open_("food")):
        rows.append({"denomination": r["den"], "category": r["cat"], "sector": "food",
                     "body_id": body_id(r["body"]), "body_name": r["body"], "body_type": r["body_type"],
                     "region": None, "list_date": dates["food"]})
    for r in parse_wine(open_("wine")):
        rows.append({"denomination": r["den"], "category": r["den"].split()[0], "sector": "wine",
                     "body_id": body_id(r["body"]), "body_name": canonical_wine_body(r["body"]),
                     "body_type": "private" if body_id(r["body"]) not in PUBLIC_IDS else "public",
                     "region": r["region"], "regions": r["regions"], "list_date": dates["wine"]})
    for r in parse_stg(open_("stg")):
        rows.append({"denomination": r["denomination"], "category": "STG", "sector": "food",
                     "body_id": body_id(r["body"]), "body_name": r["body"], "body_type": None,
                     "region": None, "list_date": dates["stg"]})
    register_names = {}
    for r in rows:
        if r["body_id"] and r["body_name"] and r["sector"] == "food" and r["category"] != "STG":
            register_names.setdefault(r["body_id"], r["body_name"])
    bodies = {}
    for kind, typ in (("contacts_private", "private"), ("contacts_public", "public")):
        for c in parse_contacts(open_(kind)):
            bid = body_id(c["name"])
            if bid:
                bodies[bid] = {"id": bid, "name": register_names.get(bid) or c["name"], "type": typ, "email": c["email"], "pec": c["pec"],
                               "web": c["web"], "list_date": dates[kind]}
    return {"refreshed": refreshed, "sources": {k: {"file": f, "list_date": dates[k]} for k, f in found.items()},
            "note": "A row says who is authorised to control a name. It is not proof that any producer is certified. "
                    "The lists give no per-denomination authorisation date; list_date is the date of the whole list.",
            "bodies": bodies, "rows": rows}


PUBLIC_IDS = {"3a-pta", "cersaa", "corfilac", "corfilcarni", "irvo", "izs-sicilia", "cciaa-bari", "cciaa-chieti-pescara",
              "cciaa-genova", "cciaa-gran-sasso", "cciaa-lecce", "cciaa-trapani", "cciaa-trento", "cciaa-bolzano"}

DATA_FILE = None


def _data_path():
    import os
    return os.path.join(os.path.dirname(__file__), "data", "masaf_control_bodies.json")


def load(path=None):
    with open(path or _data_path(), encoding="utf-8") as f:
        return json.load(f)


def _fold(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if not unicodedata.combining(c)))


def lookup(name, data=None):
    """Who is authorised to control this denomination? Returns a list of rows (may be empty).

    Matches the whole name, ignoring case and accents, then falls back to a
    row whose name contains the query. Not proof of certification.
    """
    data = data or load()
    q = _fold(name).strip()
    exact = [r for r in data["rows"] if _fold(r["denomination"]).replace("dop", "").replace("igp", "").strip() == q]
    if exact:
        return exact
    return [r for r in data["rows"] if q and q in _fold(r["denomination"])]


def describe(name, data=None, limit=3):
    """Lookup result for the AI tool and the helper: who MASAF lists as control body for a name, with contact, list date and
    the disclaimer. Empty 'found' when MASAF has no match (the caller then says so and flags staff)."""
    data = data or load()
    found = []
    for r in lookup(name, data)[:limit]:
        b = (data.get("bodies") or {}).get(r.get("body_id")) or {}
        found.append({"denomination": r["denomination"], "category": r["category"], "sector": r["sector"],
                      "control_body": r.get("body_name"), "body_id": r.get("body_id"), "email": b.get("email"),
                      "pec": b.get("pec"), "web": b.get("web"), "list_date": r.get("list_date")})
    return {"query": name, "found": found, "refreshed": data.get("refreshed"), "note": data.get("note"),
            "source": "MASAF registers of authorised control bodies"}


if __name__ == "__main__":
    import argparse
    import datetime
    ap = argparse.ArgumentParser(description="Rebuild the MASAF control-body table from the downloaded PDFs.")
    ap.add_argument("pdf_dir")
    ap.add_argument("--out", default=_data_path())
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    d = build(a.pdf_dir, a.date)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(len(d["rows"]), "rows,", len(d["bodies"]), "bodies ->", a.out)
