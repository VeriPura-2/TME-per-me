"""Weekly tariff check: every Wave 1 lane with a customs duty, from official sources.

Approved 2 Nov 2026. Runs inside the daily job, once every 7 days. For each tariff line below it
reads the official value, stores it, compares it with the previous week, and records any change
in data_changes (Staff, Data changes). Lines that cannot be read are recorded too, so a broken
source never fails silently.

Sources (all official, all tested on 2 Nov 2026):
- UK: UK Trade Tariff API (commodity code, 10 digits).
- US: USITC HTS REST search (HTS number). General (column 1) rate only.
- Switzerland: Swiss customs (BAZG) free Excel "Duty rates, chapters 1-30", found on the BAZG
  free-data page. The file address changes with each edition, so the job looks it up on that page.
- Canada: CBSA Departmental Consolidation of the Customs Tariff, one PDF per chapter (no other
  format is published). Reader tested on the 2026 PDFs for chapters 4, 15, 19 and 22, checked by hand.
  The PDF address carries the year: the job tries this year, then last year.
EU destinations have no customs duty and are not checked.
"""
import io
import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import db
from .adapters.base import AdapterError
from .adapters.tariff import UKTradeTariff, USITCHts, http_get, uk_duties, us_general

WEEK = timedelta(days=7)
UA = "MioTEM data check (contact: aeoconsultsas@pec.it)"

CH_PAGE = "https://www.bazg.admin.ch/en/tares-free-data-delivery-on-customers-request"
CH_FILE = "duty_rates_chapter_01_to_30"
CH_EU_GROUP = "100001"   # BAZG country group number for the European Union
CH_NORMAL_GROUP = "100000"

# (ref, destination, product, code, statistical key or None, description)
LINES = [
    ("UK:1902199090", "UK", "pasta", "1902199090", None, "Dried pasta, no egg"),
    ("UK:1902110090", "UK", "pasta", "1902110090", None, "Dried pasta with egg"),
    ("UK:1509200010", "UK", "oil", "1509200010", None, "Extra virgin olive oil, 5 litres or less"),
    ("UK:2204210600", "UK", "wine", "2204210600", None, "Still wine with PDO, 2 litres or less"),
    ("UK:0406906100", "UK", "cheese", "0406906100", None, "Grana Padano, Parmigiano Reggiano"),
    ("US:1902.19.20", "US", "pasta", "1902.19.20", None, "Dried pasta, no egg"),
    ("US:1902.11.20", "US", "pasta", "1902.11.20", None, "Dried pasta with egg"),
    ("US:1509.20.20", "US", "oil", "1509.20.20", None, "Extra virgin olive oil, under 18 kg"),
    ("US:1509.20.90", "US", "oil", "1509.20.90", None, "Extra virgin olive oil, other"),
    ("US:2204.21.50", "US", "wine", "2204.21.50", None, "Still wine, 2 litres or less, 14% vol or less"),
    ("US:0406.90.61.00", "US", "cheese", "0406.90.61.00", None, "Romano, Reggiano, Parmesan and similar"),
    ("CA:1902.19.21", "CA", "pasta", "1902.19.21", None, "Pasta, flour and water only, within access commitment"),
    ("CA:1902.19.22", "CA", "pasta", "1902.19.22", None, "Pasta, flour and water only, packs up to 2.3 kg, over access commitment"),
    ("CA:1902.11.10", "CA", "pasta", "1902.11.10", None, "Egg pasta, within access commitment"),
    ("CA:1902.11.21", "CA", "pasta", "1902.11.21", None, "Egg pasta, packs up to 2.3 kg, over access commitment"),
    ("CA:1509.20.00", "CA", "oil", "1509.20.00", None, "Extra virgin olive oil"),
    ("CA:2204.21.10", "CA", "wine", "2204.21.10", None, "Wine, 2 litres or less, 13.7% vol or less"),
    ("CA:2204.21.21", "CA", "wine", "2204.21.21", None, "Wine, 2 litres or less, over 13.7% up to 14.9% vol"),
    ("CA:0406.90.93", "CA", "cheese", "0406.90.93", None, "Parmesan and Parmesan types, within access commitment (CETA quota)"),
    ("CA:0406.90.94", "CA", "cheese", "0406.90.94", None, "Parmesan and Parmesan types, over access commitment"),
    ("CH:1902.1910", "CH", "pasta", "1902.1910", None, "Dried durum pasta, no egg"),
    ("CH:1902.1110", "CH", "pasta", "1902.1110", None, "Dried durum pasta with egg"),
    ("CH:1509.2091", "CH", "oil", "1509.2091", None, "Extra virgin olive oil, glass, 2 litres or less"),
    ("CH:2204.2141", "CH", "wine", "2204.2141", None, "Red wine, bottles, within tariff quota"),
    ("CH:2204.2149", "CH", "wine", "2204.2149", None, "Red wine, bottles, outside tariff quota"),
    ("CH:2204.2121", "CH", "wine", "2204.2121", None, "White wine, bottles, within tariff quota"),
    ("CH:2204.2129", "CH", "wine", "2204.2129", None, "White wine, bottles, outside tariff quota"),
    ("CH:0406.9039", "CH", "cheese", "0406.9039", None, "Parmigiano Reggiano, Grana Padano (hard)"),
]


DESC_IT = {
    "UK:1902199090": "Pasta secca, senza uova",
    "UK:1902110090": "Pasta secca all'uovo",
    "UK:1509200010": "Olio extravergine di oliva, fino a 5 litri",
    "UK:2204210600": "Vino fermo DOP, fino a 2 litri",
    "UK:0406906100": "Grana Padano, Parmigiano Reggiano",
    "US:1902.19.20": "Pasta secca, senza uova",
    "US:1902.11.20": "Pasta secca all'uovo",
    "US:1509.20.20": "Olio extravergine di oliva, sotto i 18 kg",
    "US:1509.20.90": "Olio extravergine di oliva, altre confezioni",
    "US:2204.21.50": "Vino fermo, fino a 2 litri, fino a 14% vol",
    "US:0406.90.61.00": "Romano, Reggiano, Parmesan e simili",
    "CA:1902.19.21": "Pasta di sola farina e acqua, entro il contingente",
    "CA:1902.19.22": "Pasta di sola farina e acqua, confezioni fino a 2,3 kg, oltre il contingente",
    "CA:1902.11.10": "Pasta all'uovo, entro il contingente",
    "CA:1902.11.21": "Pasta all'uovo, confezioni fino a 2,3 kg, oltre il contingente",
    "CA:1509.20.00": "Olio extravergine di oliva",
    "CA:2204.21.10": "Vino, fino a 2 litri, fino a 13,7% vol",
    "CA:2204.21.21": "Vino, fino a 2 litri, oltre 13,7% e fino a 14,9% vol",
    "CA:0406.90.93": "Parmesan e tipi Parmesan, entro il contingente (quota CETA)",
    "CA:0406.90.94": "Parmesan e tipi Parmesan, oltre il contingente",
    "CH:1902.1910": "Pasta secca di grano duro, senza uova",
    "CH:1902.1110": "Pasta secca di grano duro all'uovo",
    "CH:1509.2091": "Olio extravergine di oliva, vetro, fino a 2 litri",
    "CH:2204.2141": "Vino rosso in bottiglia, entro il contingente",
    "CH:2204.2149": "Vino rosso in bottiglia, fuori contingente",
    "CH:2204.2121": "Vino bianco in bottiglia, entro il contingente",
    "CH:2204.2129": "Vino bianco in bottiglia, fuori contingente",
    "CH:0406.9039": "Parmigiano Reggiano, Grana Padano (duri)",
}


# readers: each returns {ref: value-dict} and {ref: error} ------------------------------

def read_uk(con, lines, uk=None):
    uk = uk or UKTradeTariff()
    vals, errs = {}, {}
    for ref, _, _, code, _, _ in lines:
        try:
            d = uk_duties(uk.call(con, "fetch", commodity_code=code)["data"]["document"])
            vals[ref] = {"eu_rate": d["preferential_eu"], "normal_rate": d["third_country"], "vat": d["vat"]}
        except AdapterError as e:
            errs[ref] = str(e)[:200]
    return vals, errs


def read_us(con, lines, us=None):
    us = us or USITCHts()
    vals, errs = {}, {}
    for ref, _, _, code, _, _ in lines:
        try:
            d = us_general(us.call(con, "fetch", code=code)["data"]["results"], code)
            if d is None:
                errs[ref] = "code not found in HTS"
            else:
                vals[ref] = {"general_rate": d["normalised"]}
        except AdapterError as e:
            errs[ref] = str(e)[:200]
    return vals, errs


def _get(url, timeout=60, limit=40_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def ch_file_url(page_html):
    """Address of the current 'Duty rates, chapters 1-30' file on the BAZG free-data page."""
    # The page is built by JavaScript: in the raw HTML the link sits inside a data block with
    # escaped quotes (href=\"...\"), so match the address itself, not the attribute around it.
    m = re.search(r'((?:https?://[a-z0-9.-]+)?/[^"\'\\\s<>]*' + CH_FILE + r'\.xlsx)', page_html)
    if not m:
        return None
    href = m.group(1)
    return href if href.startswith("http") else "https://www.bazg.admin.ch" + href


def ch_rates(xlsx_bytes, codes, on=None):
    """BAZG duty rate file -> {tariff number: {normal_rate, eu_rate}} for the given numbers, valid on the date.

    Columns per the BAZG file description: TN8 Nr, ZCO Code, ..., LDG Nr (country group),
    ANS berechnet (rate), ANS Einheit (Fr.), ANS Vdat/Bdat berechnet (valid from/to), BGL Txt E (basis).
    Only customs relief code 00 (no special conditions) is read.
    """
    import openpyxl
    on = on or date.today()
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = None
    for r in rows:
        if r and r[0] == "TN8 Nr":
            header = {name: i for i, name in enumerate(r)}
            break
    if not header:
        raise ValueError("BAZG file: header row not found")
    c = lambda k: header[k]
    out = {}
    for r in rows:
        tn = r[c("TN8 Nr")]
        if tn not in codes or str(r[c("ZCO Code")]) != "00":
            continue
        frm, to = r[c("ANS Vdat berechnet")], r[c("ANS Bdat berechnet")]
        frm = frm.date() if isinstance(frm, datetime) else frm
        to = to.date() if isinstance(to, datetime) else to
        if (frm and frm > on) or (to and to < on):
            continue
        group = str(r[c("LDG Nr")])
        key = {CH_NORMAL_GROUP: "normal_rate", CH_EU_GROUP: "eu_rate"}.get(group)
        if not key:
            continue
        rate = r[c("ANS berechnet")]
        out.setdefault(tn, {})[key] = f"CHF {float(rate):.2f} {r[c('BGL Txt E Faktor')]}"
    for tn, v in out.items():
        v.setdefault("eu_rate", "no EU preference: normal rate applies")
    return out


def read_ch(con, lines, get=None):
    get = get or _get  # looked up at call time, so tests can switch the network off
    vals, errs = {}, {}
    try:
        url = ch_file_url(get(CH_PAGE, timeout=30).decode("utf-8", "replace"))
        if not url:
            raise ValueError("duty rate file link not found on the BAZG page")
        rates = ch_rates(get(url), {code for _, _, _, code, _, _ in lines})
    except Exception as e:  # one failure covers every Swiss line: record it on each
        return {}, {ref: f"{type(e).__name__}: {str(e)[:150]}" for ref, *_ in lines}
    for ref, _, _, code, _, _ in lines:
        if code in rates:
            vals[ref] = rates[code]
        else:
            errs[ref] = "tariff number not found in the BAZG file"
    return vals, errs


CA_PDF = "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/{year}/01-99/ch{ch}-{year}-eng.pdf"
CA_RATE = r"(?:Free|\d+(?:\.\d+)?%|\d+(?:\.\d+)?¢/(?:kg|litre)|\$\d+(?:\.\d+)?/(?:kg|litre))"
CA_ITEM = r"\d{4}\.\d{2}\.\d{2}"
CA_DEF = r"(?:\s\d\d)?(?:\s+-|\s*\n)"  # a tariff item where it is defined, not where a note mentions it


def ca_block(text, code):
    """Text of one tariff item in the CBSA PDF text, from its line to the next item."""
    m = re.search(re.escape(code) + CA_DEF, text)
    if not m:
        return None
    start = text.rfind("\n", 0, m.start()) + 1
    n = re.compile(CA_ITEM + CA_DEF).search(text, m.end())
    end = text.rfind("\n", 0, n.start()) + 1 if n else len(text)
    return text[start:max(end, m.end())]


def ca_rates(text, code):
    """CBSA chapter text -> {mfn_rate, ceta_rate} for a tariff item. None when the item is not found.

    The PDF text interleaves columns: rates sit next to lists of tariff treatment codes, and the
    preferential lists end with ':' and a rate. The MFN rate is the one rate not after a ':' list.
    """
    b = ca_block(text, code)
    if b is None:
        return None
    b = re.sub(CA_ITEM + r"(?:\s\d\d)?", " ", b)
    b = re.sub(r"(?m)^\s*\d\d\s+-[^\n]*$", " ", b)  # statistical suffix lines
    b = re.sub(r"(?:-\s*-|-(?=[A-Z][a-z]))[^\n]*?(?=\s[A-Z]{2,5},|\n|$)", " ", b)  # descriptions, up to a code list
    b = re.sub(r"\b(KGM|LTR|NMB)\b|(?<=[\d%a-z])(KGM|LTR|NMB)", " ", b)
    pref = {}
    for m in re.finditer(r"((?:[A-Z]{2,5},?\s*)+):\s*(" + CA_RATE + r"(?:\s*plus\s*" + CA_RATE + r")?)", b):
        for t in re.findall(r"[A-Z]{2,5}", m.group(1)):
            pref[t] = m.group(2)
        b = b.replace(m.group(0), " ")
    b = " ".join(re.sub(r"\b[A-Z]{2,5}\b,?", " ", b).split())
    mfn = re.search(CA_RATE + r"(?:\s*(?:plus|but not(?: less than)?)\s*(?:less than\s*)?" + CA_RATE + r")?", b)
    mfn = mfn.group(0) if mfn else None
    if mfn and "but not" in mfn and "less than" not in mfn:
        mfn = mfn.replace("but not", "but not less than")
    return {"mfn_rate": mfn, "ceta_rate": pref.get("CEUT") or "no CETA preference: MFN rate applies"}


def ca_pdf_text(pdf_bytes):
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


def read_ca(con, lines, get=None, pdf_text=None, year=None):
    get, pdf_text = get or _get, pdf_text or ca_pdf_text
    year = year or date.today().year
    vals, errs, texts = {}, {}, {}
    for ref, _, _, code, _, _ in lines:
        ch = code[:2]
        if ch not in texts:
            texts[ch] = None
            for y in (year, year - 1):
                try:
                    texts[ch] = pdf_text(get(CA_PDF.format(year=y, ch=ch)))
                    break
                except Exception as e:
                    texts[ch] = e
        t = texts[ch]
        if isinstance(t, Exception) or t is None:
            errs[ref] = f"chapter {ch} PDF could not be read: {type(t).__name__}"
            continue
        r = ca_rates(t, code)
        if r is None or r["mfn_rate"] is None:
            errs[ref] = "tariff item not found in the CBSA PDF"
        else:
            vals[ref] = r
    return vals, errs


READERS = {"UK": read_uk, "US": read_us, "CA": read_ca, "CH": read_ch}


# run ------------------------------------------------------------------------------------

def _change(con, kind, ref, summary, detail):
    from .jobs import _change as rec
    rec(con, kind, ref, summary, detail)


def due(con):
    r = con.execute("SELECT value FROM settings WHERE key='tariff_watch_last'").fetchone()
    return not r or datetime.fromisoformat(r["value"]) <= datetime.now(timezone.utc) - WEEK + timedelta(hours=1)


def run(con, readers=None):
    readers = {**READERS, **(readers or {})}
    out = {"lines": len(LINES), "read": 0, "changed": 0, "unreadable": 0}
    for dest, read in readers.items():
        lines = [l for l in LINES if l[1] == dest]
        if not lines:
            continue
        vals, errs = read(con, lines)
        for ref, err in errs.items():
            out["unreadable"] += 1
            _change(con, "tariff_unreadable", ref, f"Weekly tariff check could not read {ref}", {"error": err})
        for ref, v in vals.items():
            out["read"] += 1
            value = json.dumps(v, sort_keys=True, ensure_ascii=False)
            prev = con.execute("SELECT value FROM duty_snapshots WHERE ref=?", (ref,)).fetchone()
            if prev and prev["value"] != value:
                out["changed"] += 1
                _change(con, "tariff_changed", ref, f"Tariff for {ref} changed",
                        {"before": json.loads(prev["value"]), "after": v})
            con.execute("DELETE FROM duty_snapshots WHERE ref=?", (ref,))
            con.execute("INSERT INTO duty_snapshots(ref, value, checked_at) VALUES (?,?,?)", (ref, value, db.now()))
            con.commit()
    con.execute("DELETE FROM settings WHERE key='tariff_watch_last'")
    con.execute("INSERT INTO settings(key, value, updated_by, updated_at) VALUES ('tariff_watch_last', ?, 'job', ?)",
                (datetime.now(timezone.utc).isoformat(), db.now()))
    con.commit()
    return out


def snapshot(con):
    """Latest stored value for every line, for the staff panel."""
    stored = {r["ref"]: r for r in con.execute("SELECT ref, value, checked_at FROM duty_snapshots").fetchall()}
    return [{"ref": ref, "destination": dest, "product": p, "code": code, "description": desc,
             "value": json.loads(stored[ref]["value"]) if ref in stored else None,
             "checked_at": stored[ref]["checked_at"] if ref in stored else None}
            for ref, dest, p, code, _, desc in LINES]
