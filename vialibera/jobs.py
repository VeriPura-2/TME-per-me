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
import urllib.error
import urllib.request
import uuid

from . import db, requirements, tariff_watch, vat_check
from .adapters.base import AdapterError

UA = "MioTEM data check (contact: aeoconsultsas@pec.it)"


def _change(con, kind, ref, summary, detail=None):
    con.execute("INSERT INTO data_changes(id, at, kind, ref, summary, detail) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), db.now(), kind, ref, summary[:300], json.dumps(detail or {}, ensure_ascii=False)))
    con.commit()


def _fetch_text(url, timeout=10):  # 14 sources: worst case well under the Cloud Run request limit
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(3_000_000).decode("utf-8", "replace")
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    text = re.sub(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?\b", " ", text)  # dates change daily
    return " ".join(text.split())


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


def check_sources(con, fetch=_fetch_text):
    changed = unreachable = 0
    for url in source_urls():
        try:
            sha = hashlib.sha256(fetch(url).encode()).hexdigest()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            unreachable += 1
            _change(con, "source_unreachable", url, "Checklist source could not be read today", {"error": type(e).__name__})
            continue
        prev = con.execute("SELECT sha256 FROM source_snapshots WHERE url=?", (url,)).fetchone()
        if prev is None:
            con.execute("INSERT INTO source_snapshots(url, sha256, checked_at) VALUES (?,?,?)", (url, sha, db.now()))
        elif prev["sha256"] != sha:
            changed += 1
            rows = [r["id"] for r in requirements.ROWS if r["source"] and requirements.watch_url(r["source"]) == url
                    and not requirements.importer_only(r)]
            _change(con, "source_changed", url, f"Checklist source changed: {len(rows)} item(s) to re-verify", {"items": rows})
            con.execute("UPDATE source_snapshots SET sha256=?, checked_at=?, changed_at=? WHERE url=?", (sha, db.now(), db.now(), url))
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


def run_daily(con, uk=None, us=None, fetch=_fetch_text, vies_http=None, tariff_readers=None):
    out = {"started": db.now()}
    out["tariffs"] = check_tariffs(con, uk, us)
    out["sources"] = check_sources(con, fetch)
    out["vies"] = recheck_vies(con, vies_http)
    if tariff_watch.due(con):
        out["tariff_watch"] = tariff_watch.run(con, tariff_readers)
    out["finished"] = db.now()
    db.log_event(con, None, "job", "daily_job", out)
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
