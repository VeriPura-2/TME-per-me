"""Company library and project documents. A project is a case (one product for one market)."""
import hashlib
import re
import uuid

from . import accounts, db, storage

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
           "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
           "csv": "text/csv", "txt": "text/plain"}
MAGIC = {"pdf": b"%PDF", "png": b"\x89PNG", "jpg": b"\xff\xd8", "jpeg": b"\xff\xd8", "docx": b"PK", "xlsx": b"PK"}

# (type id, Italian label, English label, keywords seen in file names)
TYPES = [
    ("company_registration", "Visura camerale / registrazione", "Company registration", ["visura", "camerale", "registrazione", "registration", "chamber"]),
    ("tax_ids", "Partita IVA / EORI", "VAT / EORI", ["eori", "vat", "partita"]),
    ("insurance", "Assicurazione", "Insurance", ["assicurazione", "insurance", "polizza"]),
    ("certificate", "Certificato", "Certificate", ["certificat", "brc", "ifs", "iso", "halal", "kosher", "biologico", "organic", "dop", "docg", "igp"]),
    ("facility_approval", "Autorizzazione stabilimento", "Facility approval", ["stabilimento", "approval", "autorizzazione", "haccp"]),
    ("spec_sheet", "Scheda tecnica", "Spec sheet", ["scheda", "spec", "datasheet", "ingredient"]),
    ("label", "Etichetta", "Label", ["etichetta", "label", "artwork", "packaging"]),
    ("lab_analysis", "Analisi di laboratorio", "Lab analysis", ["analisi", "analysis", "lab", "coa", "certificate_of_analysis"]),
    ("photo", "Foto", "Photo", ["foto", "photo", "img", "jpg"]),
    ("invoice", "Fattura", "Invoice", ["fattura", "invoice", "proforma"]),
    ("packing_list", "Packing list", "Packing list", ["packing", "colli"]),
    ("transport", "Documento di trasporto", "Transport document", ["bol", "lading", "cmr", "awb", "ddt", "trasporto"]),
    ("origin", "Certificato di origine", "Certificate of origin", ["origine", "origin", "eur1", "eur.1"]),
    ("customs", "Documento doganale", "Customs document", ["dogana", "customs", "dau", "fda", "prior", "notice"]),
    ("contract", "Contratto / accordo", "Contract", ["contratto", "contract", "agreement", "accordo"]),
    ("template", "Modello", "Template", ["template", "modello"]),
    ("other", "Altro", "Other", []),
]
TYPE_IDS = [t[0] for t in TYPES]
COMPANY_LEVEL = {"company_registration", "tax_ids", "insurance", "facility_approval", "template"}


def propose(filename):
    """Propose a document type from the file name. Reading the content comes later with CORE."""
    low = filename.lower()
    for tid, _, _, words in TYPES:
        if any(w in low for w in words):
            return tid
    return "other"


def _ext(filename):
    m = re.search(r"\.([A-Za-z0-9]+)$", filename)
    return m.group(1).lower() if m else ""


def _clean(name):
    return re.sub(r"[^\w.\- ]", "_", name.replace("\\", "/").split("/")[-1])[:120] or "file"


def upload(con, who, filename, data, product=None, market=None, case_id=None):
    if not who:
        return 400, {"error": "sign-in required"}
    fn = _clean(filename)
    ext = _ext(fn)
    if ext not in ALLOWED:
        return 400, {"error": "file type not allowed", "allowed": sorted(ALLOWED)}
    if len(data) == 0 or len(data) > MAX_BYTES:
        return 400, {"error": "file must be between 1 byte and 10 MB"}
    magic = MAGIC.get(ext)
    if magic and not data.startswith(magic):
        return 400, {"error": "file content does not match its type"}
    sha = hashlib.sha256(data).hexdigest()
    comp = _company_of(con, who)
    dup = con.execute("SELECT id FROM documents WHERE sha256=? AND (owner_sub=? OR (company_id IS NOT NULL AND company_id=?))",
                      (sha, who["user"], comp)).fetchone()
    if dup:
        return 200, {"id": dup["id"], "duplicate": True}
    did = str(uuid.uuid4())
    key = f"{comp or 'user-' + who['user'].replace('|', '_')}/{did}.{ext}"
    storage.store().put(key, data)
    dtype = propose(fn)
    con.execute("INSERT INTO documents(id, owner_sub, company_id, title, filename, mime, size, sha256, store_key, doc_type, "
                "product, market, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, who["user"], comp, fn.rsplit(".", 1)[0], fn, ALLOWED[ext], len(data), sha, key, dtype,
                 None if dtype in COMPANY_LEVEL else product, market, "proposed", db.now()))
    if case_id:
        link(con, who, case_id, did, commit=False)
    con.commit()
    db.log_event(con, case_id, "client", "document_uploaded", {"document": did, "type": dtype})
    return 200, {"id": did, "doc_type": dtype, "status": "proposed"}


def _company_of(con, who):
    r = con.execute("SELECT company_id FROM memberships WHERE user_sub=? AND status='active' LIMIT 1", (who["user"],)).fetchone()
    return r["company_id"] if r else None


def can_see(con, row, who):
    if who is None:
        return True
    if row["owner_sub"] == who["user"]:
        return True
    return bool(row["company_id"]) and accounts.is_member(con, row["company_id"], who["user"])


def get_doc(con, doc_id, who):
    row = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return row if row and can_see(con, row, who) else None


def link(con, who, case_id, doc_id, commit=True):
    case = con.execute("SELECT owner_sub, company_id, org_id FROM cases WHERE id=?", (case_id,)).fetchone()
    if case is None or not accounts.can_access(con, case, who) or get_doc(con, doc_id, who) is None:
        return False
    con.execute("INSERT INTO project_docs(case_id, document_id, created_at) VALUES (?,?,?) ON CONFLICT (case_id, document_id) DO NOTHING",
                (case_id, doc_id, db.now()))
    if commit:
        con.commit()
    return True


def update(con, who, doc_id, fields):
    row = get_doc(con, doc_id, who)
    if row is None:
        return None
    sets, vals = [], []
    if fields.get("doc_type") in TYPE_IDS:
        sets.append("doc_type=?"); vals.append(fields["doc_type"])
    for k in ("product", "market", "valid_until", "title"):
        if k in fields:
            sets.append(f"{k}=?"); vals.append((fields[k] or None) if k != "title" else (fields[k] or row["title"]))
    if fields.get("confirm"):
        sets.append("status=?"); vals.append("confirmed")
    if sets:
        con.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", (*vals, doc_id))
        con.commit()
    return get_doc(con, doc_id, who)


def listing(con, who, case_id=None, product=None, doc_type=None):
    comp = _company_of(con, who) if who else None
    sql = ("SELECT d.* FROM documents d WHERE (d.owner_sub=? OR (d.company_id IS NOT NULL AND d.company_id=?))")
    args = [who["user"] if who else "", comp or ""]
    if case_id:
        sql += " AND d.id IN (SELECT document_id FROM project_docs WHERE case_id=?)"
        args.append(case_id)
    if product:
        sql += " AND d.product=?"; args.append(product)
    if doc_type:
        sql += " AND d.doc_type=?"; args.append(doc_type)
    rows = con.execute(sql + " ORDER BY d.created_at DESC", tuple(args)).fetchall()
    return [{k: r[k] for k in ("id", "title", "filename", "mime", "size", "doc_type", "product", "market",
                               "valid_until", "status", "created_at")} for r in rows]
