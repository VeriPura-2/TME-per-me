"""Funding schemes for the Funding card (F5, 22 Nov 2026).

The data lives in data/funding.json. Every fact carries its official source and the date staff checked it.
A scheme not checked for STALE_DAYS shows a line asking the reader to check the official page.
Status changes are made by staff only: the weekly source watch (jobs.py) flags a changed page, a person updates the file.
"""
import json
import os
from datetime import date

STALE_DAYS = 30
STATUSES = ("open", "closed", "check", "no_window")
FACT_FIELDS = ("applicant", "grant_share", "min_eur", "max_eur", "min_project_eur", "sizes", "regions",
               "excluded_ateco", "deadline", "max_destinations")
_PATH = os.path.join(os.path.dirname(__file__), "data", "funding.json")


def schemes():
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)["schemes"]


def _stale(checked, today=None):
    try:
        return ((today or date.today()) - date.fromisoformat(checked)).days > STALE_DAYS
    except (TypeError, ValueError):
        return True


def card_links():
    """The scheme lines the Funding card shows: label, status, note, link and check date.
    The page itself marks a line as old when the check date is more than STALE_DAYS ago, so the card data never depends on today."""
    out = []
    for s in schemes():
        st = s["status"]
        out.append({"id": s["id"], "label": s["label"], "status": st["value"], "note": s.get("note"), "url": s["url"],
                    "checked": st["checked"]})
    return out


def last_checked():
    return max(s["status"]["checked"] for s in schemes())


def source_urls():
    """Official pages the weekly source watch reads: each scheme's link and every fact source."""
    urls = set()
    for s in schemes():
        urls.add(s["url"])
        urls.add(s["status"]["source"])
        urls |= {v["source"] for v in s.get("facts", {}).values() if v.get("source")}
    return urls


def scheme_for_url(url):
    return [s["id"] for s in schemes() if url == s["url"] or url == s["status"]["source"]
            or any(v.get("source") == url for v in s.get("facts", {}).values())]


def stale_list(today=None):
    """For staff: schemes not checked in STALE_DAYS."""
    return [{"id": s["id"], "checked": s["status"]["checked"]} for s in schemes() if _stale(s["status"]["checked"], today)]
