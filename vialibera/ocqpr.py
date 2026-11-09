"""Look up a company by VAT number in OCQ PR's public list of certified operators.

OCQ PR (Organismo Controllo Qualita Produzioni Regolamentate, Reggio Emilia) controls Parmigiano Reggiano DOP,
Aceto Balsamico Tradizionale di Reggio Emilia, Erbazzone Reggiano and a few voluntary chains. Its website publishes
the operators it certifies and allows a search by VAT number (a plain GET). We call it only when a person asks for a
check, one VAT per request, with a short cache. The result is what OCQ PR's public list says on a given date: it is
not a certificate and not our own verification. Other control bodies are not covered here.
"""
import html
import re
import time
import urllib.parse
import urllib.request

HOST = "www.ocqpr.it"
SEARCH = "https://www.ocqpr.it/aziende-certificate/itemlist/filter?moduleId=178&Itemid=327&searchword6="
USER_AGENT = "MioTEM/1.0 (+https://veripura.com; contact thomas@veripura.com)"
MAX_BYTES = 600_000
MAX_RECORDS = 40
TTL = 3600
_cache = {}

NOTE = {
    "it": "Dato dall'elenco pubblico di OCQ PR, l'organismo di controllo del Parmigiano Reggiano DOP, alla data indicata. Non è un certificato e non sostituisce la verifica presso l'organismo di controllo. Copre solo le aziende controllate da OCQ PR.",
    "en": "Data from the public list of OCQ PR, the control body for Parmigiano Reggiano DOP, as of the date shown. It is not a certificate and does not replace confirmation by the control body. It covers only companies controlled by OCQ PR.",
}
SOURCE = {"label": "OCQ PR, aziende certificate", "url": "https://www.ocqpr.it/aziende-certificate"}


def normalise_vat(raw):
    """Italian VAT as 11 digits, or None. Accepts an IT prefix, spaces and dots."""
    s = re.sub(r"[\s.\-]", "", str(raw or "")).upper()
    if s.startswith("IT"):
        s = s[2:]
    return s if re.fullmatch(r"\d{11}", s) else None


def search_url(vat):
    return SEARCH + urllib.parse.quote(vat)


def fetch(url, timeout=10):
    """GET a page on the OCQ PR host only, with an identifying User-Agent and a size cap."""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != HOST:
        raise ValueError("host not allowed")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_BYTES).decode("utf-8", "replace")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


_BLOCK = re.compile(r'<div[^>]*\bparametro\b[^>]*>\s*<strong>(.*?)</strong>\s*(?:<br\s*/?>)?\s*(.*?)</div>', re.S | re.I)
_KEYS = {"RAGIONE SOCIALE": "name", "FILIERA CERTIFICATA": "chain", "TIPO ATTIVITA'": "activity",
         "STATO SOGGETTO": "subject_status", "COMUNE (PROV)": "municipality"}


def parse_results(page):
    """Records from a result page: name, chain, activity, subject_status, validity_status, municipality, detail."""
    out, cur = [], None
    for label, val in _BLOCK.findall(page):
        label = _text(label).upper().replace("’", "'")
        if label == "RAGIONE SOCIALE":
            cur = {"name": _text(val), "detail": None}
            m = re.search(r'href="(/aziende-certificate/[^"#?]+)"', val)
            if m:
                cur["detail"] = m.group(1)
            out.append(cur)
        elif cur is None:
            continue
        elif label.startswith("STATO di VALIDIT".upper()) or label.startswith("STATO DI VALIDIT"):
            cur["validity_status"] = _text(val)
        elif label in _KEYS:
            cur[_KEYS[label]] = _text(val)
    return out


_MONTHS = {m: i + 1 for i, m in enumerate("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}


def list_date(page):
    """'aggiornato al 03 novembre 2026' (or dd/mm/yyyy) as ISO date, or None."""
    t = _text(page)
    m = re.search(r"aggiornat[oa]\s+al\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})", t, re.I)
    if m and m.group(2).lower() in _MONTHS:
        return "%s-%02d-%02d" % (m.group(3), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"aggiornat[oa]\s+al\s+(\d{1,2})/(\d{1,2})/(\d{4})", t, re.I)
    return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))) if m else None


def parse_detail(page):
    """VAT, tax code, certificate number, issue date and 'valid for productions from' out of a detail page."""
    t = _text(page)
    def g(pat):
        m = re.search(pat, t, re.I)
        return m.group(1).strip() if m else None
    return {"vat": g(r"partita\s+iva\D{0,5}(\d{11})"), "tax_code": g(r"codice\s+fiscale\D{0,5}([A-Z0-9]{11,16})"),
            "certificate_no": g(r"n[°oº]\s*certificato\s*:?\s*([0-9A-Za-z/\-]+)"),
            "issued": g(r"data\s+emissione\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})"),
            "valid_from": g(r"valido\s+per\s+produzioni\s+dal\s*(\d{1,2}/\d{1,2}/\d{2,4})")}


def check_vat(raw, lang="it", fetcher=None, now=None):
    """Result dict for one VAT. status: 'listed' | 'not_listed' | 'unavailable' | 'invalid'."""
    lang = "en" if lang == "en" else "it"
    vat = normalise_vat(raw)
    base = {"vat": vat, "note": NOTE[lang], "source": SOURCE}
    if not vat:
        return dict(base, status="invalid", records=[])
    fetcher = fetcher or fetch
    now = now if now is not None else time.time()
    hit = _cache.get(vat)
    if hit and now - hit[0] < TTL and fetcher is fetch:
        return dict(hit[1], note=NOTE[lang])
    try:
        page = fetcher(search_url(vat))
        recs = parse_results(page)[:MAX_RECORDS]
        # one search can return many productions of the same company: confirm the VAT once, on the first detail page
        confirmed, cert = None, {}
        if recs and recs[0].get("detail"):
            try:
                d = parse_detail(fetcher("https://" + HOST + recs[0]["detail"]))
                confirmed = (d["vat"] == vat) if d["vat"] else None
                cert = {k: v for k, v in d.items() if v and k != "vat"}
            except Exception:
                pass
        if confirmed is False:
            recs = []
        names = list(dict.fromkeys(r["name"] for r in recs))
        res = dict(base, status="listed" if recs else "not_listed", records=recs, companies=names, confirmed_vat=confirmed,
                   first_certificate=cert, list_date=list_date(page), checked=time.strftime("%Y-%m-%d", time.gmtime(now)))
    except Exception:
        return dict(base, status="unavailable", records=[])
    if fetcher is fetch:
        _cache[vat] = (now, res)
    return res
