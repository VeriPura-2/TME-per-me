"""Client report under the TEM firm's name (C3, 22 Nov 2026).

A printable page per client project: route, documents received, documents outstanding, checks done, importers
contacted and the notes the TEM marked for the client. Rows not confirmed by staff keep the "staff to verify" label,
and Core results run in test mode say so. Built from the same data the TEM sees; nothing the client cannot see
(hours, margin, internal notes, hidden financing lines) goes in.
"""
from datetime import date
from html import escape

from . import funding_check

T = {
    "en": {"title": "{firm}: export documents status for {client}", "route": "Route", "prepared": "Prepared on {d}",
           "received": "Documents received", "outstanding": "Documents outstanding", "checks": "Checks done",
           "contacts": "Importers contacted", "notes": "Notes", "none": "None yet.", "verify": "staff to verify",
           "prepares": "prepared by", "test": "test mode", "print": "Print or save as PDF",
           "footer": "Prepared by {firm} with MioTEM, powered by VeriPura Core. Rows marked staff to verify have not been confirmed yet."},
    "it": {"title": "{firm}: stato dei documenti export per {client}", "route": "Rotta", "prepared": "Preparato il {d}",
           "received": "Documenti ricevuti", "outstanding": "Documenti mancanti", "checks": "Controlli eseguiti",
           "contacts": "Importatori contattati", "notes": "Note", "none": "Nessuno per ora.", "verify": "da verificare dallo staff",
           "prepares": "a cura di", "test": "modalità di prova", "print": "Stampa o salva in PDF",
           "footer": "Preparato da {firm} con MioTEM, powered by VeriPura Core. Le righe da verificare dallo staff non sono ancora confermate."},
}
OUTCOME = {"en": {"contacted": "Contacted", "replied": "Replied", "samples": "Samples sent", "meeting": "Meeting",
                  "not_interested": "Not interested", "order": "Order"},
           "it": {"contacted": "Contattato", "replied": "Ha risposto", "samples": "Campioni inviati", "meeting": "Incontro",
                  "not_interested": "Non interessato", "order": "Ordine"}}


def build(con, who, case_id, lang="it"):
    from . import tems
    lang = "en" if lang == "en" else "it"
    code, p = tems.project(con, who, case_id)
    if code != 200:
        return code, p
    firm = (tems.firm_of(con, who["user"]) or {}).get("name") or "TEM"
    t, e = T[lang], escape
    client = p["case"]["client"]["name"] or "-"
    prod = p["case"]["product"].get("name_brand") or p["case"]["product"].get("category") or "-"
    dest = p["case"]["market"].get("country") or "-"
    items = [i for i in ((p["required_docs"] or {}).get("data", {}).get("items") or []) if not i["importer_side"]]
    req_by_item = {q["item"]: q for q in p.get("doc_requests") or []}

    def done(i):
        q = req_by_item.get(i["id"])
        return i["on_file"] or i.get("confirmed") or (q and q["status"] in ("uploaded", "accepted"))

    def line(i):
        bits = [e(i[lang])]
        if i.get("who"):
            bits.append(f'<span class="m">({e(t["prepares"])} {e(i["who"][lang])})</span>')
        if not i.get("verified") and not i.get("confirmed"):
            bits.append(f'<span class="v">{e(t["verify"])}</span>')
        return "<li>" + " ".join(bits) + "</li>"

    def ul(rows):
        return "<ul>" + "".join(rows) + "</ul>" if rows else f'<p class="m">{e(t["none"])}</p>'

    checks = []
    for d in (p.get("core") or {}).get("documents") or []:
        if d.get("check"):
            c = d["check"]
            checks.append(f'<li>{e(d["filename"])}: {e(c["label"][lang])}' + (f' <span class="v">({e(t["test"])})</span>' if c.get("simulated") else "")
                          + f' <span class="m">{e(funding_check.fday(str(c.get("at") or "")[:10], lang))}</span></li>')
    contacts = [f'<li>{e(x["importer"])} <span class="m">{e(funding_check.fday(x["day"], lang))}</span> · {e(OUTCOME[lang][x["outcome"]])}'
                + (f'<div class="m">{e(x["note"])}</div>' if x.get("note") else "") + "</li>" for x in p.get("importer_contacts") or []]
    notes = [f'<li>{e(n["text"])} <span class="m">{e(n["by"] or "")}, {e(funding_check.fday(n["at"][:10], lang))}</span></li>'
             for n in p.get("notes") or [] if n["visibility"] == "client"]
    title = t["title"].format(firm=firm, client=client)
    html = f"""<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><title>{e(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:820px;margin:32px auto;padding:0 20px;color:#1d2a22;line-height:1.45}}
h1{{font-size:22px;margin-bottom:4px}}h2{{font-size:16px;margin:24px 0 6px;border-bottom:1px solid #ccd;padding-bottom:4px}}
.m{{color:#667}}.v{{color:#a0522d;font-size:90%}}ul{{padding-left:20px}}li{{margin:4px 0}}
footer{{margin-top:32px;border-top:1px solid #ccd;padding-top:8px;font-size:90%;color:#667}}
button{{margin-top:16px}}@media print{{button{{display:none}}}}</style></head><body>
<h1>{e(title)}</h1><div class="m">{e(t["prepared"].format(d=funding_check.fday(date.today().isoformat(), lang)))}</div>
<h2>{e(t["route"])}</h2><p>{e(prod)} → {e(dest)}</p>
<h2>{e(t["received"])}</h2>{ul([line(i) for i in items if done(i)])}
<h2>{e(t["outstanding"])}</h2>{ul([line(i) for i in items if not done(i)])}
<h2>{e(t["checks"])}</h2>{ul(checks)}
<h2>{e(t["contacts"])}</h2>{ul(contacts)}
<h2>{e(t["notes"])}</h2>{ul(notes)}
<footer>{e(t["footer"].format(firm=firm))}</footer>
<button onclick="window.print()">{e(t["print"])}</button></body></html>"""
    return 200, {"html": html, "title": title}
