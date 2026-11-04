"""Required-fields checklist for the interview (draft v0.1, see interview fields doc).

The code decides what is still missing. Claude phrases the question and records the answer
with case_write using the exact key. A value of "unknown" counts as answered and is flagged
for VeriPura staff. Goal fields are stored in the market section.
"""
UNKNOWN = "unknown"
LATER = "later"  # client chose to skip for now; not blocking, asked again before a quote

# (section, key, label, how to ask, category or None for all)
REQUIRED = [
    ("product", "category", "Product category", "options: wine | spirits | pasta | olive oil | cheese and dairy | cured meat | preserves | bakery | other", None),
    ("product", "name_brand", "Product name and brand", "free text", None),
    ("market", "country", "Destination country", "options: UK | USA | Canada | Germany | France | Spain | Netherlands | Belgium | Austria | Switzerland | other", None),
    ("product", "description_ingredients", "Short description and main ingredients", "free text", None),
    ("product", "allergens", "Allergens", "multi options: gluten | milk | eggs | nuts | soy | sulphites | none", None),
    ("product", "pack_size", "Pack size and units per case", "free text", None),
    ("product", "shelf_life_storage", "Shelf life and storage", "options: ambient | chilled | frozen", None),
    ("product", "claims", "Claims on the label", "multi options: organic | PDO/PGI | halal | vegan | gluten free | none", None),
    ("product", "label_status", "Label status", "options: final | can still change | no label yet", None),
    ("product", "abv", "Alcohol percentage on the label", "free number", "wine"),
    ("product", "vintage", "Vintage", "free text", "wine"),
    ("product", "appellation", "Appellation", "free text", "wine"),
    ("product", "producer_type", "Producer type", "options: grower | bottler | merchant", "wine"),
    ("product", "abv", "Alcohol percentage on the label", "free number", "spirits"),
    ("product", "egg_wheat_type", "Egg content and wheat type", "options: durum no egg | durum with egg | other", "pasta"),
    ("product", "fresh_or_dry", "Fresh or dry", "options: dry | fresh", "pasta"),
    ("product", "oil_grade_harvest", "Grade and harvest year", "free text", "olive oil"),
    ("product", "milk_pasteurised_age", "Milk type, raw or pasteurised, ageing time", "free text", "cheese and dairy"),
    ("product", "species_establishment", "Species, cured or cooked, establishment approval number", "free text", "cured meat"),
    ("market", "importer_status", "Importer or buyer status", "options: have one | looking | not sure", None),
    ("market", "channel", "Sales channel", "options: importer | direct to consumer | retail chain | horeca | marketplace", None),
    ("market", "first_shipment", "First shipment size", "free text (cases or pallets, rough value)", None),
    ("market", "timing", "Target timing", "options: within 3 months | within 6 months | later", None),
    ("market", "needs", "Help wanted", "multi options: tariff and duty | label check | export documents | find importer | logistics | certification | other", None),
    ("market", "approver", "Who approves decisions", "options: the person chatting | someone else", None),
    ("company", "legal_name", "Legal company name", "free text", None),
    ("company", "vat_number", "VAT number (partita IVA)", "free text", None),
    ("company", "address_region", "Registered address", "free text: street and number, postcode, city and province, for example Via Roma 1, 12051 Alba (CN)", None),
    ("company", "size", "Company size", "options: micro under 10 staff | small 10-49 | medium 50-249", None),
    ("company", "contact", "Main contact name, email, phone", "free text", None),
    ("company", "export_experience", "Export experience", "options: none | occasional | regular", None),
    ("company", "certifications", "Certifications held", "multi options: organic | DOP/DOCG/IGP | halal | kosher | BRC | IFS | ISO | none", None),
    ("company", "export_registration", "Export registration (EORI, and Italian excise status for wine)", "options: all in place | partly | not started | not sure", "wine"),
    ("company", "export_registration", "Export registration (EORI, and Italian excise status for spirits)", "options: all in place | partly | not started | not sure", "spirits"),
    ("company", "export_registration", "Export registration (EORI number)", "options: all in place | not started | not sure", None),
]


EXTRA = [("market", "importer_name", "Importer or buyer name", "free text", None)]


def allowed_keys():
    """Every key the case file accepts, per section; "notes" in each section takes anything else worth keeping."""
    out = {"company": {"notes"}, "product": {"notes"}, "market": {"notes"}}
    for sec, key, *_ in REQUIRED + EXTRA:
        out[sec].add(key)
    return out


def check_write(section, fields):
    """Splits a case_write into accepted fields and an error naming the wrong keys and where they belong."""
    allowed = allowed_keys()
    if section not in allowed:
        return {}, f"section must be one of: {', '.join(sorted(allowed))}"
    ok = {k: v for k, v in (fields or {}).items() if k in allowed[section]}
    bad = [k for k in (fields or {}) if k not in allowed[section]]
    if not bad:
        return ok, None
    hints = []
    for k in bad:
        home = [s for s, keys in allowed.items() if k in keys and s != section]
        hints.append(f"{k} belongs in section {home[0]}" if home else f"{k} is not a field")
    return ok, ("Not saved: " + "; ".join(hints) + f". Valid keys for {section}: {', '.join(sorted(allowed[section]))}. "
                "Write each fact again with the right section and key (see FIELDS).")


def field_guide():
    """The full list of case-file fields, for the agent's fixed instructions (same text on every call, so it caches)."""
    lines, seen = [], set()
    for sec, key, label, how, only in REQUIRED + EXTRA:
        tag = f"{sec}.{key}"
        extra = f" ({only} only)" if only else ""
        if tag in seen:
            lines.append(f"  {tag}{extra}: {how}")
            continue
        seen.add(tag)
        lines.append(f"- {tag}: {label}{extra}; {how}")
    return ("FIELDS (case_write uses exactly these sections and keys; anything else goes in that section's notes):\n"
            + "\n".join(lines))


def _norm(v):
    return str(v).strip().lower()


def applicable(case):
    cat = _norm(case["product"].get("category", ""))
    seen, out = set(), []
    for sec, key, label, how, only in REQUIRED:
        if only and only != cat:
            continue
        if (sec, key) in seen:
            continue
        seen.add((sec, key))
        out.append((sec, key, label, how))
    return out


def status(case):
    """Return (answered, total, missing list, unknown keys). Category extras only count once category is known."""
    items = applicable(case)
    missing, unknowns, answered = [], [], 0
    for sec, key, label, how in items:
        v = case[sec].get(key)
        if v in (None, "", [], {}) or _norm(v) == LATER:
            missing.append((sec, key, label, how, _norm(v) == LATER))
        else:
            answered += 1
            if _norm(v) == UNKNOWN:
                unknowns.append(key)
    return answered, len(items), missing, unknowns


def prompt_note(case):
    answered, total, missing, unknowns = status(case)
    fresh = [m for m in missing if not m[4]]
    deferred = [m for m in missing if m[4]]
    if missing and not fresh:
        names = ", ".join(m[1] for m in deferred)
        note = (f"CHECKLIST: {answered} of {total} answered. Only skipped items remain: {names}. Do not push. Let the client "
                "explore or ask questions, answer them, and mention once that these are needed before a quote or payment.")
    elif not missing:
        note = f"CHECKLIST: complete ({answered} of {total}). Summarise the case for the client and ask them to confirm."
    else:
        sec, key, label, how, _ = fresh[0]
        note = (f"CHECKLIST: {answered} of {total} required answers recorded. Next field to ask: "
                f"section={sec} key={key} ({label}); format: {how}. Ask only this one, then record the answer "
                f"with case_write using exactly that section and key. If the client does not know, record \"unknown\". If the client wants to skip it for now, record \"later\" and move on.")
    if deferred and fresh:
        note += " Skipped for now (ask again later, never insist): " + ", ".join(m[1] for m in deferred) + "."
    if unknowns:
        note += " Flag these for staff: " + ", ".join(unknowns) + "."
    return note
