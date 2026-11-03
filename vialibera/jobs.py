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
import difflib
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import db, requirements, tariff_watch, vat_check
from .adapters.base import AdapterError

UA = "MioTEM data check (contact: aeoconsultsas@pec.it)"


def _change(con, kind, ref, summary, detail=None):
    con.execute("INSERT INTO data_changes(id, at, kind, ref, summary, detail) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), db.now(), kind, ref, summary[:300], json.dumps(detail or {}, ensure_ascii=False)))
    con.commit()


def _fetch_text(url, timeout=15):  # fetched 8 at a time (_fetch_all): 42 sources stay well under the request limit
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(3_000_000).decode("utf-8", "replace")
    return page_text(raw)


BLOCK_END = re.compile(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|dd|dt|section|article|table|ul|ol)>")


def page_text(raw):
    """Readable text of a page, one line per block (paragraph, list item, table row), so changes can be shown by line."""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = BLOCK_END.sub("\n", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    text = re.sub(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?\b", " ", text)  # dates change daily
    return "\n".join(l for l in (" ".join(line.split()) for line in text.splitlines()) if l)


TEXT_KEEP = 500_000  # characters of a page kept for tomorrow's comparison (only the latest version is stored)
DIFF_LINES = 40  # changed lines saved with a Data changes alert


def text_diff(old, new, limit=DIFF_LINES):
    """{"removed": [...], "added": [...]} lines that differ, at most `limit` in total, each cut to 300 characters."""
    removed, added = [], []
    for line in difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        if len(removed) + len(added) >= limit:
            break
        (removed if line.startswith("-") else added).append(line[1:][:300])
    return {"removed": removed, "added": added}


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


def check_sources(con, fetch=_fetch_text):
    changed = unreachable = 0
    with db.outside_call():  # 20 to 40 s of downloads: no connection held meanwhile
        pages = _fetch_all(source_urls(), fetch)
    for url in source_urls():
        text = pages[url]
        if isinstance(text, Exception):
            unreachable += 1
            _change(con, "source_unreachable", url, "Checklist source could not be read today", {"error": type(text).__name__})
            continue
        text = text[:TEXT_KEEP]
        sha = hashlib.sha256(text.encode()).hexdigest()
        prev = con.execute("SELECT sha256, page_text FROM source_snapshots WHERE url=?", (url,)).fetchone()
        if prev is None:
            con.execute("INSERT INTO source_snapshots(url, sha256, checked_at, page_text) VALUES (?,?,?,?)", (url, sha, db.now(), text))
        elif prev["page_text"] is None:
            # first run that keeps text: take it as the starting point, no alert (the fingerprint format changed too)
            con.execute("UPDATE source_snapshots SET sha256=?, page_text=?, checked_at=? WHERE url=?", (sha, text, db.now(), url))
        elif prev["sha256"] != sha:
            changed += 1
            rows = [r["id"] for r in requirements.ROWS if r["source"] and requirements.watch_url(r["source"]) == url
                    and not requirements.importer_only(r)]
            _change(con, "source_changed", url, f"Checklist source changed: {len(rows)} item(s) to re-verify",
                    {"items": rows, **text_diff(prev["page_text"], text)})
            # only the newest text is kept: yesterday's is replaced, the changed lines stay with the alert
            con.execute("UPDATE source_snapshots SET sha256=?, page_text=?, checked_at=?, changed_at=? WHERE url=?",
                        (sha, text, db.now(), db.now(), url))
        else:
            con.execute("UPDATE source_snapshots SET checked_at=? WHERE url=?", (db.now(), url))
        con.commit()
    return {"sources": len(source_urls()), "changed": changed, "unreachable": unreachable}


def apply_source_flags(con, case_id, req):
    """Checklist rows whose source changed since they were confirmed go back to 'staff to verify'."""
    if not req:
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

def changes(con, include_dismissed=False):
    q = "SELECT * FROM data_changes" + ("" if include_dismissed else " WHERE status='open'") + " ORDER BY at DESC LIMIT 200"
    return [{"id": r["id"], "at": r["at"], "kind": r["kind"], "ref": r["ref"], "summary": r["summary"],
             "detail": json.loads(r["detail"] or "{}"), "status": r["status"]} for r in con.execute(q).fetchall()]


def dismiss(con, who, change_id):
    con.execute("UPDATE data_changes SET status='dismissed', dismissed_by=?, dismissed_at=? WHERE id=?",
                (who["user"], db.now(), change_id))
    con.commit()
    return 200, {"ok": True}
