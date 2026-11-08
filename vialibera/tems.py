"""TEM firms (export consultants) working for client companies. Mode 1: the TEM is a platform user.

A TEM firm has a lead and members (seats). A superadmin creates the firm and the lead invite.
The firm gets a client only through an engagement link: the client signs in, fills in the company
details and accepts what the TEM may do. The client can revoke access at any time.

Access rule: a TEM user sees a client company only when the firm's link to it is active AND the user
is the firm lead or is assigned to that client. Every opening of a client project is logged and the
client can see the log. A TEM cannot pay, change the client's plan or manage the client's team.
"""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from . import accounts, db, docs, permissions, storage

LINK_DAYS = 14
SCOPE = {
    "it": ["Creare e gestire progetti di esportazione per l'azienda",
           "Caricare, archiviare e gestire i documenti dell'azienda",
           "Inviare documenti a VeriPura CORE per la verifica (servizio ospitato negli Stati Uniti)",
           "Agire per conto dell'azienda all'interno di MioTEM"],
    "en": ["Create and run export projects for the company",
           "Upload, file and manage the company's documents",
           "Send documents to VeriPura CORE for checking (service hosted in the United States)",
           "Act on the company's behalf inside MioTEM"],
}


def _exp(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


# who is who -----------------------------------------------------------------------

def firm_of(con, user_sub):
    r = con.execute("SELECT m.firm_id, m.role, f.name FROM tem_members m JOIN tem_firms f ON f.id=m.firm_id "
                    "WHERE m.user_sub=? AND f.status='active' LIMIT 1", (user_sub,)).fetchone()
    return dict(r) if r else None


def has_access(con, who, company_id):
    """True when this user may work on this client company as a TEM."""
    if not who or not company_id:
        return False
    f = firm_of(con, who["user"])
    if not f:
        return False
    link = con.execute("SELECT status FROM tem_clients WHERE firm_id=? AND company_id=?", (f["firm_id"], company_id)).fetchone()
    if not link or link["status"] != "active":
        return False
    if f["role"] == "lead":
        return True
    return con.execute("SELECT 1 FROM tem_assignments WHERE firm_id=? AND company_id=? AND user_sub=?",
                       (f["firm_id"], company_id, who["user"])).fetchone() is not None


def _lead(con, who):
    f = firm_of(con, who["user"]) if who else None
    return f if f and f["role"] == "lead" else None


def _label(con, who):
    f = firm_of(con, who["user"])
    r = con.execute("SELECT label FROM tem_members WHERE firm_id=? AND user_sub=?", (f["firm_id"], who["user"])).fetchone() if f else None
    return ((r["label"] if r and r["label"] else who["user"][-8:]) + (" · " + f["name"] if f else ""))


def log_access(con, who, case_row, action):
    f = firm_of(con, who["user"])
    db.log_event(con, case_row["id"], who["user"], "tem_access",
                 {"action": action, "company": case_row["company_id"], "firm": f["firm_id"] if f else None,
                  "firm_name": f["name"] if f else None})


# superadmin: firms -----------------------------------------------------------------

def create_firm(con, who, name, vat=None, seats=None):
    if not permissions.is_superadmin(who):
        return 403, {"error": "forbidden"}
    name = str(name or "").strip()[:160]
    if not name:
        return 400, {"error": "name required"}
    fid = str(uuid.uuid4())
    con.execute("INSERT INTO tem_firms(id, name, vat, seats, created_by, created_at) VALUES (?,?,?,?,?,?)",
                (fid, name, (vat or "").strip()[:20] or None, int(seats) if seats else None, who["user"], db.now()))
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO tem_invites(token, firm_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, fid, "lead", who["user"], _exp(LINK_DAYS), db.now()))
    con.commit()
    db.log_event(con, None, who["user"], "staff_change", {"action": "tem_firm_created", "firm": fid})
    return 200, {"firm": fid, "lead_token": token}


def list_firms(con, who):
    if not permissions.is_staff(who):
        return 403, {"error": "forbidden"}
    out = []
    for f in con.execute("SELECT * FROM tem_firms ORDER BY created_at DESC").fetchall():
        n = con.execute("SELECT COUNT(*) AS n FROM tem_members WHERE firm_id=?", (f["id"],)).fetchone()["n"]
        c = con.execute("SELECT COUNT(*) AS n FROM tem_clients WHERE firm_id=? AND status='active'", (f["id"],)).fetchone()["n"]
        out.append({"id": f["id"], "name": f["name"], "vat": f["vat"], "seats": f["seats"], "members": n, "clients": c,
                    "status": f["status"]})
    return 200, {"firms": out}


def lead_link(con, who, firm_id):
    if not permissions.is_superadmin(who):
        return 403, {"error": "forbidden"}
    if not con.execute("SELECT 1 FROM tem_firms WHERE id=?", (firm_id,)).fetchone():
        return 404, {"error": "no such firm"}
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO tem_invites(token, firm_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, firm_id, "lead", who["user"], _exp(LINK_DAYS), db.now()))
    con.commit()
    return 200, {"token": token}


# firm team ----------------------------------------------------------------------

def invite_member(con, who):
    f = _lead(con, who)
    if not f:
        return 403, {"error": "forbidden"}
    seats = con.execute("SELECT seats FROM tem_firms WHERE id=?", (f["firm_id"],)).fetchone()["seats"]
    used = con.execute("SELECT COUNT(*) AS n FROM tem_members WHERE firm_id=?", (f["firm_id"],)).fetchone()["n"]
    if seats is not None and used >= seats:
        return 400, {"error": "no_free_seat"}
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO tem_invites(token, firm_id, role, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (token, f["firm_id"], "member", who["user"], _exp(LINK_DAYS), db.now()))
    con.commit()
    return 200, {"token": token}


def join(con, who, token, label=None):
    if permissions.is_staff(who):
        return 403, {"error": "staff_cannot_join"}
    r = con.execute("SELECT * FROM tem_invites WHERE token=?", (token,)).fetchone()
    if r is None or r["used_by"] or r["expires_at"] < db.now():
        return 400, {"error": "invite_invalid"}
    cur = firm_of(con, who["user"])
    if cur and cur["firm_id"] != r["firm_id"]:
        return 400, {"error": "already_in_another_firm"}
    if cur:
        con.execute("UPDATE tem_members SET role=? WHERE firm_id=? AND user_sub=?",
                    ("lead" if r["role"] == "lead" else cur["role"], r["firm_id"], who["user"]))
    else:
        con.execute("INSERT INTO tem_members(firm_id, user_sub, role, label, created_at) VALUES (?,?,?,?,?)",
                    (r["firm_id"], who["user"], r["role"], (label or "")[:120] or None, db.now()))
    con.execute("UPDATE tem_invites SET used_by=? WHERE token=?", (who["user"], token))
    con.commit()
    db.log_event(con, None, who["user"], "tem_joined", {"firm": r["firm_id"], "role": r["role"]})
    return 200, {"ok": True, "role": r["role"]}


def remove_member(con, who, user):
    f = _lead(con, who)
    if not f or user == who["user"]:
        return 403, {"error": "forbidden"}
    con.execute("DELETE FROM tem_members WHERE firm_id=? AND user_sub=?", (f["firm_id"], user))
    con.execute("DELETE FROM tem_assignments WHERE firm_id=? AND user_sub=?", (f["firm_id"], user))
    con.commit()
    db.log_event(con, None, who["user"], "tem_member_removed", {"firm": f["firm_id"], "user": user})
    return 200, {"ok": True}


def assign(con, who, company_id, user, on=True):
    f = _lead(con, who)
    if not f:
        return 403, {"error": "forbidden"}
    if not con.execute("SELECT 1 FROM tem_members WHERE firm_id=? AND user_sub=?", (f["firm_id"], user)).fetchone():
        return 404, {"error": "not a firm member"}
    if not con.execute("SELECT 1 FROM tem_clients WHERE firm_id=? AND company_id=? AND status='active'",
                       (f["firm_id"], company_id)).fetchone():
        return 404, {"error": "not a client of the firm"}
    if on:
        con.execute("INSERT INTO tem_assignments(firm_id, company_id, user_sub, created_at) VALUES (?,?,?,?) "
                    "ON CONFLICT (firm_id, company_id, user_sub) DO NOTHING", (f["firm_id"], company_id, user, db.now()))
    else:
        con.execute("DELETE FROM tem_assignments WHERE firm_id=? AND company_id=? AND user_sub=?", (f["firm_id"], company_id, user))
    con.commit()
    db.log_event(con, None, who["user"], "tem_assignment", {"firm": f["firm_id"], "company": company_id, "user": user, "on": bool(on)})
    return 200, {"ok": True}


# engagement ---------------------------------------------------------------------

def engage_link(con, who):
    f = firm_of(con, who["user"]) if who else None
    if not f:
        return 403, {"error": "forbidden"}
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO engagement_links(token, firm_id, created_by, expires_at, created_at) VALUES (?,?,?,?,?)",
                (token, f["firm_id"], who["user"], _exp(LINK_DAYS), db.now()))
    con.commit()
    return 200, {"token": token, "expires_at": _exp(LINK_DAYS)}


def _link(con, token):
    r = con.execute("SELECT * FROM engagement_links WHERE token=?", (token,)).fetchone()
    if r is None or r["used_by"] or r["expires_at"] < db.now():
        return None
    return r


def engage_info(con, who, token):
    r = _link(con, token)
    if r is None:
        return 400, {"error": "link_invalid"}
    f = con.execute("SELECT name, vat FROM tem_firms WHERE id=?", (r["firm_id"],)).fetchone()
    return 200, {"firm": {"name": f["name"], "vat": f["vat"]}, "scope": SCOPE, "expires_at": r["expires_at"]}


def _engagement_text(firm_name, company, sig, scope, at, lang):
    lines = ["MioTEM - " + ("Incarico al consulente export" if lang == "it" else "Engagement of export consultant"), "",
             ("Consulente (TEM): " if lang == "it" else "Consultant (TEM): ") + firm_name,
             ("Azienda: " if lang == "it" else "Company: ") + f"{company['legal_name']} ({company['vat']})",
             ("Sede: " if lang == "it" else "Address: ") + (company.get("address") or "-"),
             ("Firmatario: " if lang == "it" else "Signatory: ") + f"{sig['name']}, {sig['role']} <{sig['email']}>",
             ("Data e ora (UTC): " if lang == "it" else "Date and time (UTC): ") + at, "",
             "L'azienda autorizza il consulente a:" if lang == "it" else "The company authorises the consultant to:"]
    lines += ["- " + s for s in scope]
    lines += ["", "L'azienda puo revocare questo incarico in qualsiasi momento in MioTEM." if lang == "it"
              else "The company may revoke this engagement at any time in MioTEM.",
              "Accettato online dopo l'accesso con l'email indicata." if lang == "it"
              else "Accepted online after signing in with the email shown."]
    return "\n".join(lines)


def engage_accept(con, who, token, body, terms_version):
    """The client signs in, gives company details and accepts. Creates or joins the company and links the firm."""
    if not who:
        return 400, {"error": "sign-in required"}
    if permissions.is_staff(who) or firm_of(con, who["user"]):
        return 403, {"error": "tem_or_staff_cannot_accept"}
    r = _link(con, token)
    if r is None:
        return 400, {"error": "link_invalid"}
    if not (body.get("accept_scope") and body.get("accept_core") and body.get("accept_terms") and body.get("authorised")):
        return 400, {"error": "all acceptances required"}
    from . import vat_check
    vat, err = vat_check.italian(body.get("vat"))
    if err:
        return 400, {"error": "invalid_vat", "detail": err}
    name = str(body.get("legal_name") or "").strip()[:200]
    sig = {"name": str(body.get("signatory_name") or "").strip()[:120], "role": str(body.get("signatory_role") or "").strip()[:80],
           "email": str(body.get("email") or "").strip()[:160]}
    if not (name and sig["name"] and sig["role"]):
        return 400, {"error": "company name, signatory name and role are required"}
    lang = "en" if body.get("lang") == "en" else "it"
    t = db.now()
    co = con.execute("SELECT id FROM companies WHERE vat=?", (vat,)).fetchone()
    if co is None:
        cid = str(uuid.uuid4())
        con.execute("INSERT INTO companies(id, vat, legal_name, plan, created_at) VALUES (?,?,?,?,?)", (cid, vat, name, None, t))
        con.execute("INSERT INTO memberships(company_id, user_sub, role, status, label, created_at) VALUES (?,?,?,?,?,?)",
                    (cid, who["user"], "owner", "active", sig["email"] or None, t))
    else:
        cid = co["id"]
        if permissions.role_in(con, cid, who["user"]) != "owner":
            return 403, {"error": "company_exists_owner_must_accept"}
    accounts.record_consent(con, who["user"], terms_version, lang, True)
    accounts.record_company_consent(con, who["user"], terms_version, lang)  # authority confirmed: no second acceptance on Team
    f = con.execute("SELECT name FROM tem_firms WHERE id=?", (r["firm_id"],)).fetchone()
    scope = SCOPE[lang]
    text = _engagement_text(f["name"], {"legal_name": name, "vat": vat, "address": body.get("address")}, sig, scope, t, lang)
    data = text.encode("utf-8")
    did = str(uuid.uuid4())
    key = f"{cid}/{did}.txt"
    storage.store().put(key, data)
    import hashlib
    con.execute("INSERT INTO documents(id, owner_sub, company_id, title, filename, mime, size, sha256, store_key, doc_type, "
                "status, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, who["user"], cid, "Engagement " + f["name"], f"engagement_{did[:8]}.txt", "text/plain", len(data),
                 hashlib.sha256(data).hexdigest(), key, "contract", "confirmed", "generated", t))
    con.execute("DELETE FROM tem_clients WHERE firm_id=? AND company_id=?", (r["firm_id"], cid))
    con.execute("INSERT INTO tem_clients(firm_id, company_id, status, engaged_at, engaged_by, signatory, scope, engagement_doc) "
                "VALUES (?,?,?,?,?,?,?,?)", (r["firm_id"], cid, "active", t, who["user"], json.dumps(sig), json.dumps(scope), did))
    # the TEM who sent the link works on this client from the start
    con.execute("INSERT INTO tem_assignments(firm_id, company_id, user_sub, created_at) VALUES (?,?,?,?) "
                "ON CONFLICT (firm_id, company_id, user_sub) DO NOTHING", (r["firm_id"], cid, r["created_by"], t))
    con.execute("UPDATE engagement_links SET used_by=?, company_id=? WHERE token=?", (who["user"], cid, token))
    con.commit()
    db.log_event(con, None, who["user"], "tem_engaged", {"firm": r["firm_id"], "company": cid})
    vat_check.check_company(con, cid)
    return 200, {"ok": True, "company": cid, "firm": f["name"]}


# client side ---------------------------------------------------------------------

# client requests ("Ask my TEM") ---------------------------------------------------

NOTE_MAX = 500


def ask(con, who, case_row, tool, note):
    """A client asks their TEM for help with a visible tool (or, with no tool, with other tools).
    No payment: the TEM already works for the client under the engagement."""
    from . import tools
    link = con.execute("SELECT firm_id FROM tem_clients WHERE company_id=? AND status='active' LIMIT 1", (case_row["company_id"],)).fetchone()
    if not link or firm_of(con, who["user"]):
        return 404, {"error": "no TEM works on this project"}
    tool = str(tool).strip() if tool else None
    if tool:
        always = {c["id"] for c in tools.CORE}
        if tool not in tools.TOOL_IDS or not (tool in always or tools._visibility(con, case_row["id"]).get(tool)):
            return 400, {"error": "unknown or hidden tool"}
    note = str(note or "").strip()[:NOTE_MAX] or None
    if con.execute("SELECT 1 FROM tem_requests WHERE case_id=? AND COALESCE(tool,'')=? AND status='open'",
                   (case_row["id"], tool or "")).fetchone():
        return 409, {"error": "already_open"}
    rid = uuid.uuid4().hex
    con.execute("INSERT INTO tem_requests(id, case_id, company_id, firm_id, tool, note, status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, case_row["id"], case_row["company_id"], link["firm_id"], tool, note, "open", who["user"], db.now()))
    con.commit()
    db.log_event(con, case_row["id"], who["user"], "tem_request", {"tool": tool})
    return 200, {"ok": True, "id": rid}


def request_done(con, who, request_id):
    r = con.execute("SELECT * FROM tem_requests WHERE id=?", (request_id,)).fetchone()
    case = con.execute("SELECT * FROM cases WHERE id=?", (r["case_id"],)).fetchone() if r else None
    if r is None or case is None or not has_access(con, who, r["company_id"]):
        return 404, {"error": "no such request"}
    con.execute("UPDATE tem_requests SET status='done', done_by=?, done_at=? WHERE id=? AND status='open'",
                (who["user"], db.now(), request_id))
    con.commit()
    log_access(con, who, case, "request_done")
    return 200, {"ok": True}


def client_view(con, who):
    """For the client's owner: the firms working for the company and their access log."""
    cid = permissions.company_of(con, who["user"]) if who else None
    if not cid:
        return 200, {"firms": [], "log": []}
    owner = permissions.role_in(con, cid, who["user"]) == "owner"
    firms = [{"id": r["firm_id"], "name": r["name"], "status": r["status"], "since": r["engaged_at"], "revoked_at": r["revoked_at"]}
             for r in con.execute("SELECT c.*, f.name FROM tem_clients c JOIN tem_firms f ON f.id=c.firm_id WHERE c.company_id=? "
                                  "ORDER BY c.engaged_at DESC", (cid,)).fetchall()]
    log = [{"at": e["at"], "action": json.loads(e["data"]).get("action"), "firm": json.loads(e["data"]).get("firm_name")}
           for e in con.execute("SELECT e.at, e.data FROM events e JOIN cases c ON c.id=e.case_id "
                                "WHERE c.company_id=? AND e.kind='tem_access' ORDER BY e.id DESC LIMIT 50", (cid,)).fetchall()]
    return 200, {"firms": firms, "log": log, "can_revoke": owner}


def revoke(con, who, firm_id):
    cid = permissions.company_of(con, who["user"]) if who else None
    if not cid or permissions.role_in(con, cid, who["user"]) != "owner":
        return 403, {"error": "forbidden"}
    con.execute("UPDATE tem_clients SET status='revoked', revoked_at=?, revoked_by=? WHERE firm_id=? AND company_id=?",
                (db.now(), who["user"], firm_id, cid))
    con.execute("DELETE FROM tem_assignments WHERE firm_id=? AND company_id=?", (firm_id, cid))
    con.commit()
    db.log_event(con, None, who["user"], "tem_revoked", {"firm": firm_id, "company": cid})
    return 200, {"ok": True}


# TEM workspace ---------------------------------------------------------------------

def overview(con, who):
    f = firm_of(con, who["user"]) if who else None
    if not f:
        return 200, {"firm": None}
    lead = f["role"] == "lead"
    fr = con.execute("SELECT * FROM tem_firms WHERE id=?", (f["firm_id"],)).fetchone()
    members = [dict(r) for r in con.execute("SELECT user_sub AS user, role, label FROM tem_members WHERE firm_id=? ORDER BY created_at",
                                            (f["firm_id"],)).fetchall()] if lead else []
    from . import requirements, tools
    names = {c["id"]: c["name"] for c in tools.for_case(None, None)}
    clients = []
    for c in con.execute("SELECT t.company_id, t.engaged_at, co.legal_name, co.vat FROM tem_clients t JOIN companies co ON co.id=t.company_id "
                         "WHERE t.firm_id=? AND t.status='active' ORDER BY co.legal_name", (f["firm_id"],)).fetchall():
        if not has_access(con, who, c["company_id"]):
            continue
        projects = []
        have = {d["doc_type"] for d in con.execute("SELECT doc_type FROM documents WHERE company_id=?", (c["company_id"],)).fetchall()}
        for k in con.execute("SELECT id, status, product, market, updated_at FROM cases WHERE company_id=? ORDER BY updated_at DESC",
                             (c["company_id"],)).fetchall():
            prod, mkt = json.loads(k["product"] or "{}"), json.loads(k["market"] or "{}")
            req = requirements.required(prod.get("category"), mkt.get("country"), have)
            mine = [i for i in req["data"]["items"] if not i["importer_side"]] if req else None
            missing = sum(1 for i in mine if not i["on_file"]) if req else None
            docs_n = {"have": len(mine) - missing, "total": len(mine)} if req else None
            projects.append({"id": k["id"], "status": k["status"], "product": prod.get("name_brand") or prod.get("category"),
                             "category": prod.get("category"), "country": mkt.get("country"), "missing": missing, "docs": docs_n,
                             "updated_at": k["updated_at"]})
        assigned = [r["user_sub"] for r in con.execute("SELECT user_sub FROM tem_assignments WHERE firm_id=? AND company_id=?",
                                                        (f["firm_id"], c["company_id"])).fetchall()]
        requests = [{"id": q["id"], "case_id": q["case_id"], "tool": q["tool"], "tool_name": names.get(q["tool"]), "note": q["note"], "at": q["created_at"],
                     "project": " → ".join(x for x in [(json.loads(q["product"] or "{}").get("name_brand") or json.loads(q["product"] or "{}").get("category")),
                                                       json.loads(q["market"] or "{}").get("country")] if x)}
                    for q in con.execute("SELECT r.*, k.product, k.market FROM tem_requests r JOIN cases k ON k.id=r.case_id "
                                         "WHERE r.firm_id=? AND r.company_id=? AND r.status='open' ORDER BY r.created_at",
                                         (f["firm_id"], c["company_id"])).fetchall()]
        clients.append({"id": c["company_id"], "name": c["legal_name"], "vat": c["vat"], "since": c["engaged_at"],
                        "projects": projects, "assigned": assigned if lead else None, "requests": requests})
    return 200, {"firm": {"id": f["firm_id"], "name": f["name"], "seats": fr["seats"]}, "role": f["role"], "members": members,
                 "clients": clients}


def new_project(con, who, company_id, category=None, country=None, name=None):
    if not has_access(con, who, company_id):
        return 404, {"error": "no such client"}
    cid = db.create_case(con, 1, owner_sub=who["user"])
    con.execute("UPDATE cases SET company_id=? WHERE id=?", (company_id, cid))
    if category or name:
        db.case_write(con, cid, "product", {k: v for k, v in (("category", category), ("name_brand", name)) if v}, actor=who["user"])
    if country:
        db.case_write(con, cid, "market", {"country": country}, actor=who["user"])
    co = con.execute("SELECT legal_name, vat FROM companies WHERE id=?", (company_id,)).fetchone()
    db.case_write(con, cid, "company", {"legal_name": co["legal_name"], "vat_number": co["vat"]}, actor=who["user"])
    con.commit()
    db.log_event(con, cid, who["user"], "tem_project_created", {"company": company_id})
    return 200, {"case_id": cid}


def _case_tem(con, who, case_id):
    row = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None or not has_access(con, who, row["company_id"]):
        return None
    return row


def project(con, who, case_id):
    """Everything a TEM needs on one project. Logged as a TEM access."""
    from . import core_checks, duties, fields, requirements, tools
    row = _case_tem(con, who, case_id)
    if row is None:
        return 404, {"error": "no such project"}
    log_access(con, who, row, "open_project")
    case = db.case_read(con, case_id)
    have = {d["doc_type"] for d in con.execute("SELECT doc_type FROM documents WHERE company_id=?", (row["company_id"],)).fetchall()}
    req = requirements.required(case["product"].get("category"), case["market"].get("country"), have)
    if req:
        from . import jobs, vat_check
        apply_confirmations(con, case_id, req)
        jobs.apply_source_flags(con, case_id, req)
        vat_check.apply_to_checklist(con, row["company_id"], req)
    pdocs = [dict(r) for r in con.execute(
        "SELECT d.id, d.filename, d.doc_type, d.status, d.created_at FROM project_docs p JOIN documents d ON d.id=p.document_id "
        "WHERE p.case_id=? ORDER BY d.created_at", (case_id,)).fetchall()]
    library = [dict(r) for r in con.execute(
        "SELECT id, filename, doc_type, created_at FROM documents WHERE company_id=? ORDER BY created_at DESC LIMIT 100",
        (row["company_id"],)).fetchall()]
    transcript = []
    for m in db.load_history(con, case_id):
        if isinstance(m.get("content"), str):
            transcript.append({"role": m["role"], "text": m["content"]})
        else:
            txt = " ".join(b.get("text", "") for b in m["content"] if isinstance(b, dict) and b.get("type") == "text").strip()
            if txt:
                transcript.append({"role": m["role"], "text": txt})
    answered, total, missing, _ = fields.status(case)
    co = con.execute("SELECT legal_name, vat FROM companies WHERE id=?", (row["company_id"],)).fetchone()
    return 200, {"case": {"id": case_id, "status": row["status"], "company": case["company"], "product": case["product"],
                          "market": case["market"], "client": {"id": row["company_id"], "name": co["legal_name"], "vat": co["vat"]}},
                 "progress": {"answered": answered, "total": total, "missing": [{"label": m[2], "later": m[4]} for m in missing]},
                 "required_docs": req, "documents": pdocs, "library": library,
                 "core": core_checks.summary(con, case_id), "notes": notes(con, case_id, internal=True), "transcript": transcript,
                 "duties": duties.for_case(con, case),
                 "tools": tools.for_viewer(con, row, case["product"].get("category"), case["market"].get("country"), "tem")}


# checklist confirmations and notes ---------------------------------------------------

def apply_confirmations(con, case_id, req):
    conf = {r["item_id"]: r for r in con.execute("SELECT * FROM checklist_confirmations WHERE case_id=?", (case_id,)).fetchall()}
    for i in req["data"]["items"]:
        c = conf.get(i["id"])
        if c:
            i["verified"] = True
            i["confirmed"] = {"by": c["by_label"], "note": c["note"], "at": c["at"]}
    return req


def confirm_item(con, who, case_id, item_id, note=None, on=True):
    row = _case_tem(con, who, case_id)
    if row is None and not permissions.is_superadmin(who):
        return 404, {"error": "no such project"}
    row = row or con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        return 404, {"error": "no such project"}
    label = _label(con, who) if firm_of(con, who["user"]) else "VeriPura staff"
    if on:
        con.execute("DELETE FROM checklist_confirmations WHERE case_id=? AND item_id=?", (case_id, item_id))
        con.execute("INSERT INTO checklist_confirmations(case_id, item_id, confirmed_by, by_label, note, at) VALUES (?,?,?,?,?,?)",
                    (case_id, str(item_id)[:60], who["user"], label, (note or "")[:500] or None, db.now()))
    else:
        con.execute("DELETE FROM checklist_confirmations WHERE case_id=? AND item_id=?", (case_id, item_id))
    con.commit()
    db.log_event(con, case_id, who["user"], "checklist_confirmed" if on else "checklist_unconfirmed", {"item": item_id})
    return 200, {"ok": True}


def notes(con, case_id, internal=False):
    q = "SELECT * FROM case_notes WHERE case_id=?" + ("" if internal else " AND visibility='client'") + " ORDER BY created_at"
    return [{"id": r["id"], "by": r["author_label"], "visibility": r["visibility"], "text": r["text"], "at": r["created_at"]}
            for r in con.execute(q, (case_id,)).fetchall()]


def add_note(con, who, case_id, text, visibility="internal"):
    row = _case_tem(con, who, case_id)
    staff = permissions.is_superadmin(who)
    if row is None and not staff:
        return 404, {"error": "no such project"}
    text = str(text or "").strip()[:4000]
    if not text:
        return 400, {"error": "text required"}
    vis = "client" if visibility == "client" else "internal"
    label = _label(con, who) if firm_of(con, who["user"]) else "VeriPura staff"
    con.execute("INSERT INTO case_notes(id, case_id, author, author_label, visibility, text, created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), case_id, who["user"], label, vis, text, db.now()))
    con.commit()
    db.log_event(con, case_id, who["user"], "note_added", {"visibility": vis})
    return 200, {"ok": True}
