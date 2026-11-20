"""Daily job: keep tariff and checklist data fresh, and tell staff what changed.

Called once a day by Google Cloud Scheduler (POST /jobs/daily with the X-Job-Secret header),
or by a superadmin from the staff panel. Each run:
  1. runs the live known-answer tariff checks,
  2. (lane duties are refreshed by the weekly tariff check, step 5),
  3. checks every checklist source page for changes (checklist rows using a changed page go
     back to "staff to verify" until a TEM or staff confirms them again),
  4. re-checks VIES for companies whose last check could not run,
  5. once every 7 days, runs the weekly tariff check for every lane with a duty (tariff_watch).
Findings go to data_changes, shown in the staff panel. Nothing here changes a figure that a
client sees without staff seeing it first, except fresher official duty values.
"""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from . import db, requirements, tariff_watch, vat_check
from .adapters.base import AdapterError

UA = "MioTEM data check (contact: aeoconsultsas@pec.it)"


def _change(con, kind, ref, summary, detail=None):
    con.execute("INSERT INTO data_changes(id, at, kind, ref, summary, detail) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), db.now(), kind, ref, summary[:300], json.dumps(detail or {}, ensure_ascii=False)))
    con.commit()


LAST_SEEN = {}  # url -> what the last fetch of it saw (status, size, bot-check header)
RETRY_PAUSE = 8  # seconds before the one retry of a page that answered "too many requests" or a server error (19 Nov 2026)


def _fetch_text(url, timeout=15):  # fetched 8 at a time (_fetch_all): 42 sources stay well under the request limit
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code not in (429, 500, 502, 503, 504):
            raise
        time.sleep(RETRY_PAUSE)  # EU PDFs answered 429 on some days; one more try before it counts as unreadable
        r = urllib.request.urlopen(req, timeout=timeout)
    with r:
        raw = r.read(3_000_000).decode("utf-8", "replace")
    # What the server answered, kept for the Data changes alert if the page then counts as unreadable (20 Nov 2026:
    # ten EUR-Lex pages were unreadable and the alert did not say why).
    LAST_SEEN[url] = {"status": getattr(r, "status", None), "bytes": len(raw), "waf": r.headers.get("x-amzn-waf-action"),
                      "start": " ".join(raw[:160].split()) if len(raw) < 3000 else ""}
    return page_text(raw)


BLOCK_END = re.compile(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|dd|dt|section|article|table|ul|ol)>")


def page_text(raw):
    """Readable text of a page, one line per block (paragraph, list item, table row), so changes can be shown by line."""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = BLOCK_END.sub("\n", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    text = re.sub(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?\b", " ", text)  # dates change daily
    # control characters (PDF sources give binary bytes): Postgres refuses NUL in text, and none are readable anyway
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    return "\n".join(l for l in (" ".join(line.split()) for line in text.splitlines()) if l)


CONFIRM_HOURS = 20   # a changed text is flagged only if it is still there at a run this many hours later
SHRINK_MIN = 400     # a page of at least this many characters that loses more than half its text was not read properly
TEXT_KEEP = 500_000  # characters of a page kept for tomorrow's comparison (only the latest version is stored)
DIFF_LINES = 200  # changed lines saved with a Data changes alert (was 40; a cut-off hid the end of long amendment lists, 19 Nov 2026)

# Lines that carry no rule and change on their own. Dropped before two versions of a page are compared (19 Nov 2026).
NOISE_ANY = re.compile(r"(?i)^(skip to (main )?content|saltar al contenido principal|aller au contenu principal|zum hauptinhalt|"
                       r"passer au contenu|vai al contenuto)")
NOISE_BY_HOST = {  # host fragment -> pattern of lines to ignore (taken from the alerts of 10 to 19 Nov)
    "cscb.ca": re.compile(r'^["\u201c\u201e\u00ab].*["\u201d\u00bb]$'),        # rotating customer quotes
    "aida.ineris.fr": re.compile(r"(?i)^th[ée]matiques li[ée]es"),
    "xtares.admin.ch": re.compile(r"(?i)maintenance|wartung|entretien|manutenzione"),
}


def comparable_lines(url, text):
    """Lines of a page that matter for a comparison: no menu, language or rotating-quote lines.
    EUR-Lex pages also lose short lines without a digit (menus, series labels); a legal change always carries a number."""
    host_re = next((rx for h, rx in NOISE_BY_HOST.items() if h in (url or "")), None)
    eurlex = "eur-lex.europa.eu" in (url or "")
    out = []
    for line in (text or "").splitlines():
        if NOISE_ANY.match(line) or (host_re and host_re.search(line)):
            continue
        if eurlex and len(line) < 60 and not re.search(r"\d", line):
            continue
        out.append(line)
    return out


def fingerprint(url, text):
    """Same hash for the same set of lines, in any order. A reordered amendment list is not a change."""
    return hashlib.sha256("\n".join(sorted(set(comparable_lines(url, text)))).encode()).hexdigest()


def text_diff(old, new, limit=DIFF_LINES, url=None):
    """{"removed": [...], "added": [...], "more": n} lines that differ as sets (order ignored), at most `limit` in total,
    each cut to 300 characters; `more` counts what did not fit."""
    o, n = comparable_lines(url, old), comparable_lines(url, new)
    so, sn = set(o), set(n)
    removed = [l[:300] for l in dict.fromkeys(o) if l not in sn]
    added = [l[:300] for l in dict.fromkeys(n) if l not in so]
    total = len(removed) + len(added)
    # share the limit, so a page replaced as a whole still shows what came in its place (14 Nov 2026)
    keep_removed = max(limit // 2, limit - len(added))
    removed = removed[:keep_removed]
    added = added[:limit - len(removed)]
    return {"removed": removed, "added": added, "more": total - len(removed) - len(added)}


# 1 + 2: tariffs ---------------------------------------------------------------------

def check_tariffs(con, uk=None, us=None):
    out = {"known_answers": "pass"}  # lane duties: weekly check (tariff_watch)
    try:
        from .check_tariffs import results
        for ka_id, ok, got, expect in results(uk=uk, us=us):
            if not ok:
                out["known_answers"] = "fail"
                _change(con, "known_answer_failed", ka_id, f"Known answer {ka_id} no longer matches the live tariff",
                        {"got": got, "expected": expect})
    except AdapterError as e:
        out["known_answers"] = "unavailable"
        _change(con, "known_answer_failed", "tariff_service", "Tariff service unavailable during the daily check", {"error": str(e)[:200]})
    return out


# 3: checklist sources ------------------------------------------------------------------

def source_urls():
    """URLs the job checks: each source, or its watch URL when the source refuses cloud servers."""
    urls = {requirements.watch_url(r["source"]) for r in requirements.ROWS if r["source"] and not requirements.importer_only(r)}
    urls |= {requirements.watch_url(n["source"]) for n in requirements.NOT_NEEDED if n.get("source")}
    return sorted(urls)


def _fetch_all(urls, fetch):
    """{url: page text or exception}. Pages are fetched 8 at a time so 40+ sources fit the job's time limit."""
    def one(url):
        try:
            return url, fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            return url, e
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(one, urls))


def _hours_since(at):
    try:
        return (datetime.fromisoformat(db.now()) - datetime.fromisoformat(at)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0


def _read_snapshot(con, url):
    """The first database read after the downloads. If the connection was dropped meanwhile (4, 5 and 8 Nov 2026),
    reconnect and try once more; a second failure is raised as before."""
    sql = "SELECT sha256, page_text, pending_sha, pending_at FROM source_snapshots WHERE url=?"
    try:
        return con.execute(sql, (url,)).fetchone()
    except Exception as e:
        if type(e).__name__ not in ("OperationalError", "InterfaceError"):
            raise
        try:
            con.rollback()
        except Exception:
            pass
        return con.execute(sql, (url,)).fetchone()


def check_sources(con, fetch=_fetch_text):
    changed = unreachable = 0
    with db.outside_call():  # 20 to 40 s of downloads: no connection held meanwhile
        pages = _fetch_all(source_urls(), fetch)
    for url in source_urls():
        text = pages[url]
        if isinstance(text, Exception):
            unreachable += 1
            _change(con, "source_unreachable", url, "Checklist source could not be read today",
                    {"error": type(text).__name__, "info": str(text)[:200]})
            continue
        text = text[:TEXT_KEEP]
        sha = fingerprint(url, text)
        prev = _read_snapshot(con, url)
        if prev is None:
            con.execute("INSERT INTO source_snapshots(url, sha256, checked_at, page_text) VALUES (?,?,?,?)", (url, sha, db.now(), text))
        elif prev["page_text"] is None:
            # first run that keeps text: take it as the starting point, no alert (the fingerprint format changed too)
            con.execute("UPDATE source_snapshots SET sha256=?, page_text=?, checked_at=? WHERE url=?", (sha, text, db.now(), url))
        elif fingerprint(url, prev["page_text"]) == sha:  # yesterday's text under today's rules, so a rule change here raises nothing
            con.execute("UPDATE source_snapshots SET checked_at=?, pending_sha=NULL, pending_at=NULL WHERE url=?", (db.now(), url))
        elif len(prev["page_text"]) >= SHRINK_MIN and len(text) < len(prev["page_text"]) / 2:
            # most of the page is gone: a bot check or an error page, not a rule change. Yesterday's text is kept.
            unreachable += 1
            _change(con, "source_unreachable", url, "Checklist source could not be read today",
                    {"error": "page_shrank", "chars": len(text), "was": len(prev["page_text"]), **LAST_SEEN.get(url, {})})
        elif prev["pending_sha"] != sha or _hours_since(prev["pending_at"]) < CONFIRM_HOURS:
            # first sighting of this text: wait for a later run. Rotating page parts and pages that flip
            # between two versions never show the same new text twice in a row, so they stay quiet.
            if prev["pending_sha"] != sha:
                con.execute("UPDATE source_snapshots SET pending_sha=?, pending_at=?, checked_at=? WHERE url=?", (sha, db.now(), db.now(), url))
        else:
            changed += 1
            rows = [r["id"] for r in requirements.ROWS if r["source"] and requirements.watch_url(r["source"]) == url
                    and not requirements.importer_only(r)]
            _change(con, "source_changed", url, f"Checklist source changed: {len(rows)} item(s) to re-verify",
                    {"items": rows, **text_diff(prev["page_text"], text, url=url)})
            # only the newest text is kept: yesterday's is replaced, the changed lines stay with the alert
            con.execute("UPDATE source_snapshots SET sha256=?, page_text=?, checked_at=?, changed_at=?, pending_sha=NULL, pending_at=NULL "
                        "WHERE url=?", (sha, text, db.now(), db.now(), url))
        con.commit()
    return {"sources": len(source_urls()), "changed": changed, "unreachable": unreachable}


def apply_source_flags(con, case_id, req, staff=True):
    """Checklist rows whose source changed since they were confirmed go back to 'staff to verify', for staff only.
    Exporters and TEM firms keep seeing the row as it was until staff have looked at the change (decision 14 Nov 2026):
    most changes are page noise, and the flag said nothing about what changed."""
    if not req or not staff:
        return req
    changed = {r["url"]: r["changed_at"] for r in con.execute(
        "SELECT url, changed_at FROM source_snapshots WHERE changed_at IS NOT NULL").fetchall()}
    for i in req["data"]["items"]:
        at = changed.get(requirements.watch_url(i.get("source")))
        if not at:
            continue
        conf = i.get("confirmed")
        if conf and conf["at"] >= at:
            continue  # confirmed again after the change
        i["verified"], i["confirmed"] = False, None
        i["source_changed"] = at
    return req


# 4: VIES re-checks ---------------------------------------------------------------------

def recheck_vies(con, http=None):
    n = 0
    for r in con.execute("SELECT id FROM companies WHERE vat LIKE 'IT%' AND (vies_state IS NULL OR vies_state='unavailable' "
                         "OR vies_state='not_in_vies')").fetchall():
        prev = con.execute("SELECT vies_state FROM companies WHERE id=?", (r["id"],)).fetchone()["vies_state"]
        res = vat_check.check_company(con, r["id"], http)
        n += 1
        if res and res["state"] == "valid" and prev != "valid":
            _change(con, "vies_rechecked", r["id"], "Company now confirmed in VIES", {"before": prev})
    return {"companies_rechecked": n}


PARTS = ("sources", "vies", "tariffs")  # Cloud Scheduler calls each part on its own, so one failure does not stop the others


AI_ALERT_EVERY = timedelta(hours=1)


def ai_unavailable(con, err):
    """Staff alert when the AI service fails (for example: credit balance too low). At most one an hour."""
    since = (datetime.now(timezone.utc) - AI_ALERT_EVERY).isoformat(timespec="seconds")
    if con.execute("SELECT 1 FROM data_changes WHERE kind='ai_unavailable' AND at > ?", (since,)).fetchone():
        return False
    detail = " ".join(str(getattr(err, "message", None) or err).split())[:300]
    _change(con, "ai_unavailable", type(err).__name__, f"AI service unavailable: {detail}"[:300],
            {"error": type(err).__name__, "status": getattr(err, "status_code", None), "message": detail})
    return True


def run_part(con, part, uk=None, us=None, fetch=_fetch_text, vies_http=None, tariff_readers=None):
    """One part of the daily job, in its own request with its own time limit."""
    if part not in PARTS:
        raise ValueError(f"unknown job part: {part}")
    out = {"part": part, "started": db.now()}
    if part == "sources":
        out["tariffs"] = check_tariffs(con, uk, us)  # known answers: quick, kept with the source check
        out["sources"] = check_sources(con, fetch)
    elif part == "vies":
        out["vies"] = recheck_vies(con, vies_http)
    elif tariff_watch.due(con):
        out["tariff_watch"] = tariff_watch.run(con, tariff_readers)
    else:
        out["tariff_watch"] = "not due"
    out["finished"] = db.now()
    db.log_event(con, None, "job", "daily_job", out)
    return out


def run_daily(con, uk=None, us=None, fetch=_fetch_text, vies_http=None, tariff_readers=None):
    """All parts in one call (tests, and the old single scheduler call). A failing part is recorded, the rest still run."""
    out = {"started": db.now()}
    for part in PARTS:
        try:
            r = run_part(con, part, uk, us, fetch, vies_http, tariff_readers)
            out.update({k: v for k, v in r.items() if k not in ("part", "started", "finished")})
        except Exception as e:
            try:
                con.rollback()
            except Exception:
                pass
            out[part + "_error"] = type(e).__name__
            _change(con, "job_failed", part, f"Daily job part '{part}' failed", {"error": f"{type(e).__name__}: {e}"[:300]})
    out["finished"] = db.now()
    return out


# staff -------------------------------------------------------------------------------

def changes(con, include_dismissed=False, only_dismissed=False):
    where = " WHERE status='dismissed'" if only_dismissed else ("" if include_dismissed else " WHERE status='open'")
    q = "SELECT * FROM data_changes" + where + " ORDER BY at DESC LIMIT 200"
    return [{"id": r["id"], "at": r["at"], "kind": r["kind"], "ref": r["ref"], "summary": r["summary"],
             "detail": json.loads(r["detail"] or "{}"), "status": r["status"]} for r in con.execute(q).fetchall()]


def dismiss(con, who, change_id):
    con.execute("UPDATE data_changes SET status='dismissed', dismissed_by=?, dismissed_at=? WHERE id=?",
                (who["user"], db.now(), change_id))
    con.commit()
    return 200, {"ok": True}


def dismiss_all(con, who, expected=None):
    """Dismiss every open alert. With `expected`, refuse if the open count changed since the person saw it."""
    n = con.execute("SELECT COUNT(*) AS n FROM data_changes WHERE status='open'").fetchone()["n"]
    if expected is not None and int(expected) != n:
        return 409, {"error": "count_changed", "count": n}
    con.execute("UPDATE data_changes SET status='dismissed', dismissed_by=?, dismissed_at=? WHERE status='open'", (who["user"], db.now()))
    con.commit()
    return 200, {"ok": True, "dismissed": n}


def restore(con, who, change_id):
    """Bring a dismissed alert back to the open list."""
    con.execute("UPDATE data_changes SET status='open', dismissed_by=NULL, dismissed_at=NULL WHERE id=? AND status='dismissed'", (change_id,))
    con.commit()
    return 200, {"ok": True}
