"""Case file store, event log and evidence record (SQLite for staging)."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  path_type INTEGER NOT NULL,          -- 1..4, see product flow spec section 2
  status TEXT NOT NULL DEFAULT 'draft',
  org_id TEXT,                         -- legacy Auth0 organization id
  owner_sub TEXT,                      -- user who started the case
  company_id TEXT,                     -- company record once the VAT number is known
  company TEXT NOT NULL DEFAULT '{}',  -- JSON
  product TEXT NOT NULL DEFAULT '{}',  -- JSON
  market TEXT NOT NULL DEFAULT '{}',   -- JSON
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  vat TEXT NOT NULL UNIQUE,            -- normalised, with country prefix
  legal_name TEXT,
  status TEXT NOT NULL DEFAULT 'unverified',
  plan TEXT,                           -- the company pays: esplora, parti or cresci
  created_by TEXT,                     -- set when VeriPura staff created the record on the client's behalf
  created_at TEXT NOT NULL,
  vies_state TEXT,                     -- valid, not_in_vies, unavailable (see vat_check.py)
  vies_name TEXT,
  vies_address TEXT,
  vies_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS memberships (
  company_id TEXT NOT NULL,
  user_sub TEXT NOT NULL,
  role TEXT NOT NULL,                  -- owner, member, reviewer
  status TEXT NOT NULL DEFAULT 'active',  -- active, pending (access requested)
  label TEXT,                          -- display text sent by the person's browser (email), never trusted for access
  created_at TEXT NOT NULL,
  PRIMARY KEY (company_id, user_sub)
);
CREATE TABLE IF NOT EXISTS team_invites (
  token TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  role TEXT NOT NULL,
  created_by TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  user_sub TEXT PRIMARY KEY,
  persona_id TEXT,
  style TEXT,                          -- brief, steps or numbers, chosen by the person
  plan TEXT,                           -- esplora, parti or cresci
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  owner_sub TEXT NOT NULL,             -- uploader
  company_id TEXT,                     -- set once the company exists, then the library belongs to it
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  store_key TEXT NOT NULL,             -- object path in storage
  doc_type TEXT,                       -- see docs.TYPES
  product TEXT,                        -- free text product name, NULL = company level
  market TEXT,                         -- country, NULL = not market specific
  valid_until TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',   -- proposed (filing awaiting confirmation) or confirmed
  source TEXT NOT NULL DEFAULT 'upload',     -- upload, generated, staff
  version_of TEXT,                     -- earlier document this replaces
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_docs (
  case_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (case_id, document_id)
);
CREATE TABLE IF NOT EXISTS consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_sub TEXT NOT NULL,
  terms_version TEXT NOT NULL,
  lang TEXT NOT NULL,
  onerous_clauses INTEGER NOT NULL,    -- 1 if the specific approval box was ticked
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES cases(id),
  code TEXT NOT NULL,                  -- menu item code
  state TEXT NOT NULL DEFAULT 'proposed',
  price_cents INTEGER,                 -- from the VeriPura menu only, NULL = to be set
  is_compliance INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  actor TEXT NOT NULL,                 -- who
  item_version INTEGER NOT NULL,       -- version seen
  at TEXT NOT NULL                     -- when
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,                 -- client, agent, staff, system, adapter:<id>
  kind TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT,
  at TEXT NOT NULL,
  provider TEXT NOT NULL,
  units REAL NOT NULL,
  cost_cents REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY,
  inviter_sub TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invite_uses (
  invitee_sub TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  accepted_at TEXT NOT NULL,
  granted_at TEXT
);
CREATE TABLE IF NOT EXISTS company_consents (
  company_id TEXT NOT NULL,
  terms_version TEXT NOT NULL,
  accepted_by TEXT NOT NULL,           -- the owner who accepted for the company
  lang TEXT,
  at TEXT NOT NULL,
  PRIMARY KEY (company_id, terms_version)
);
CREATE TABLE IF NOT EXISTS credit_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_sub TEXT NOT NULL,              -- the holder: a person's sub, or 'co:<company id>' (the company holds credit once the person has one)
  delta_cents INTEGER NOT NULL,        -- grant positive, use negative
  kind TEXT NOT NULL,                  -- grant or use
  code TEXT,
  at TEXT NOT NULL,
  expires_at TEXT,                     -- grants only
  simulated INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
CREATE TABLE IF NOT EXISTS voice_usage (
  user_sub TEXT NOT NULL,
  day TEXT NOT NULL,
  chars INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_sub, day)
);
CREATE TABLE IF NOT EXISTS histories (
  case_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,                  -- JSON list of API messages
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stripe_customers (
  holder TEXT PRIMARY KEY,             -- 'co:<company id>' or a person's sub: who pays
  customer_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stripe_subs (
  holder TEXT PRIMARY KEY,
  subscription_id TEXT,
  plan TEXT NOT NULL,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stripe_events (
  id TEXT PRIMARY KEY,                 -- Stripe event id, processed once
  type TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tem_firms (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  vat TEXT,
  seats INTEGER,                       -- NULL = not limited until seat prices are set
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tem_members (
  firm_id TEXT NOT NULL,
  user_sub TEXT NOT NULL,
  role TEXT NOT NULL,                  -- lead or member
  label TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (firm_id, user_sub)
);
CREATE TABLE IF NOT EXISTS tem_invites (
  token TEXT PRIMARY KEY,
  firm_id TEXT NOT NULL,
  role TEXT NOT NULL,
  created_by TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tem_clients (
  firm_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  status TEXT NOT NULL,                -- active or revoked
  engaged_at TEXT NOT NULL,
  engaged_by TEXT NOT NULL,            -- client signatory (signed-in user)
  signatory TEXT NOT NULL,             -- JSON: name, role, email
  scope TEXT NOT NULL,                 -- JSON: what the TEM may do
  engagement_doc TEXT,                 -- document id of the signed engagement record
  revoked_at TEXT,
  revoked_by TEXT,
  PRIMARY KEY (firm_id, company_id)
);
CREATE TABLE IF NOT EXISTS tem_requests (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  firm_id TEXT NOT NULL,
  tool TEXT,                           -- NULL = the general "other tools" line
  note TEXT,
  status TEXT NOT NULL,                -- open or done
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  done_by TEXT,
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS tem_assignments (
  firm_id TEXT NOT NULL,
  company_id TEXT NOT NULL,
  user_sub TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (firm_id, company_id, user_sub)
);
CREATE TABLE IF NOT EXISTS engagement_links (
  token TEXT PRIMARY KEY,
  firm_id TEXT NOT NULL,
  created_by TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_by TEXT,
  company_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_counts (
  owner_key TEXT NOT NULL,             -- company id, or "u:" plus the user when there is no company
  kind TEXT NOT NULL,                  -- covered, free_check
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (owner_key, kind)
);
CREATE TABLE IF NOT EXISTS counted_cases (
  case_id TEXT PRIMARY KEY,
  owner_key TEXT NOT NULL,
  kind TEXT NOT NULL                   -- covered or uncovered
);
CREATE TABLE IF NOT EXISTS lane_requests (
  id TEXT PRIMARY KEY,
  case_id TEXT,
  company_id TEXT,
  user_sub TEXT,
  product TEXT,
  country TEXT,
  timing TEXT,
  volume TEXT,
  buyer TEXT,
  notes TEXT,
  source TEXT NOT NULL,                -- chat (the AI asked) or start_form
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cert_requests (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  company_id TEXT,
  body_id TEXT NOT NULL,               -- control body id from the MASAF table
  body_name TEXT,
  denomination TEXT NOT NULL,
  state TEXT NOT NULL,                 -- prepared, sent or reply_received
  consent INTEGER NOT NULL,            -- 1 when the producer agreed to the request
  doc_id TEXT,                         -- the uploaded reply, when there is one
  prepared_by TEXT,
  sent_by TEXT,
  reply_by TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  reply_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tem_interest (   -- a TEM or export consultant asks to join, from the public landing page
  id TEXT PRIMARY KEY,
  firm_name TEXT NOT NULL,
  email TEXT NOT NULL,
  clients TEXT,                        -- rough number of clients, as typed
  lang TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS route_interest (   -- a landing visitor asks to be told when a route we do not cover yet is ready
  id TEXT PRIMARY KEY,
  visitor_id TEXT,
  product TEXT,                        -- in the visitor's own words
  country TEXT,
  email TEXT NOT NULL,
  name TEXT,
  lang TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS anon_chats (   -- a landing page conversation before sign-in
  visitor_id TEXT PRIMARY KEY,
  ip_hash TEXT NOT NULL,
  role TEXT,                           -- exporter, tem, looking
  history TEXT NOT NULL,               -- API messages, JSON
  answers TEXT NOT NULL,               -- what the visitor told us, JSON
  messages INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_interest (
  id TEXT PRIMARY KEY,
  case_id TEXT,
  company_id TEXT,
  user_sub TEXT,
  tool TEXT NOT NULL,                  -- a tool card id from tools.py ("Tell me when it's ready")
  user_type TEXT,                      -- exporter (no TEM), tem, client (of a TEM)
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_visibility (
  case_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  visible INTEGER NOT NULL,            -- 1 shown to the TEM's client, 0 hidden, no row means the default in tools.py
  set_by TEXT NOT NULL,
  set_at TEXT NOT NULL,
  PRIMARY KEY (case_id, tool)
);
CREATE TABLE IF NOT EXISTS case_notes (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  author TEXT NOT NULL,
  author_label TEXT,
  visibility TEXT NOT NULL,            -- internal (TEM firm and VeriPura staff) or client
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklist_confirmations (
  case_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  confirmed_by TEXT NOT NULL,
  by_label TEXT,
  note TEXT,
  at TEXT NOT NULL,
  PRIMARY KEY (case_id, item_id)
);
CREATE TABLE IF NOT EXISTS checklist_marks (   -- ticked by hand by the exporter: not verified by us
  case_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  marked_by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (case_id, item_id)
);
CREATE TABLE IF NOT EXISTS core_consignments (
  case_id TEXT PRIMARY KEY,
  consignment_id TEXT NOT NULL,        -- VeriPura Core consignment for this project
  simulated INTEGER NOT NULL DEFAULT 0,
  last_status TEXT,                    -- JSON, latest status answer
  checked_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS core_checks (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  via TEXT NOT NULL,                   -- staff or auto
  actor TEXT NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,                 -- done, unknown (send outcome not known), error
  core_status TEXT,
  validation_level TEXT,
  requires_review INTEGER,
  outcome TEXT,                        -- matched, flagged, flagged_critical, not_checked
  alerts TEXT,                         -- JSON
  raw_ref TEXT,
  error TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tariff_cache (
  key TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_changes (
  id TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,                  -- duty_changed, known_answer_failed, source_changed, source_unreachable, vies_rechecked
  ref TEXT NOT NULL,                   -- what changed: lane code, source url, company id
  summary TEXT NOT NULL,
  detail TEXT,                         -- JSON
  status TEXT NOT NULL DEFAULT 'open', -- open or dismissed
  dismissed_by TEXT,
  dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS source_snapshots (
  url TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  changed_at TEXT,                     -- last time the text changed: checklist rows using it need re-verifying
  page_text TEXT,                      -- latest page text only, for showing what changed next time
  pending_sha TEXT,                    -- a different text seen once: flagged only if still there at a later run
  pending_at TEXT
);
CREATE TABLE IF NOT EXISTS duty_snapshots (
  ref TEXT PRIMARY KEY,
  value TEXT NOT NULL,                 -- JSON of the duty lines
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_responses (
  ref TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  provider TEXT NOT NULL,
  body TEXT NOT NULL
);
"""

CASE_STATES = ["draft", "interviewing", "options ready", "items selected", "quoted",
               "approved", "paid", "in progress", "delivered", "follow-up active", "closed"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_outside_hook = None  # set by app: saves the request's writes and lends its connection back to the pool


def set_outside_hook(fn):
    global _outside_hook
    _outside_hook = fn


@contextmanager
def outside_call():
    """Wrap any slow call to an outside service (AI, VIES, Core, Stripe, voice, storage, official sites).
    Before it starts, the request's database connection is committed and lent back to the pool, so a
    request waiting 30 s for the AI does not hold one of the few connections. The next database use
    borrows a connection again. No effect on SQLite (local dev, tests) or outside a request."""
    if _outside_hook:
        _outside_hook()
    yield


def pg_sql(sql):
    """Our SQL uses ? placeholders (sqlite style). For psycopg2: double literal %, then ? becomes %s."""
    return sql.replace("%", "%%").replace("?", "%s")


class PG:
    """Thin wrapper giving a psycopg2 connection the sqlite3 calls the code uses."""

    postgres = True

    def __init__(self, raw):
        import psycopg2.extras
        self.raw = raw
        self._cur = lambda: raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=()):
        cur = self._cur()
        # psycopg2 reads every % as a placeholder marker, so a literal % (LIKE 'IT%') must be doubled.
        cur.execute(pg_sql(sql), params)
        return cur

    def executescript(self, script):
        script = "\n".join(line.split("--", 1)[0] for line in script.splitlines())  # comments may contain ";"
        for stmt in script.split(";"):
            if stmt.strip():
                self.execute(stmt)
        self.raw.commit()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


ADDED_COLUMNS = [("companies", c) for c in ("vies_state", "vies_name", "vies_address", "vies_checked_at")] + [
    ("source_snapshots", "page_text"), ("companies", "owner_confirmed"), ("tem_firms", "max_projects"), ("anon_chats", "user_sub"),
    ("tem_firms", "max_clients"), ("tem_firms", "trial"), ("tem_interest", "source"), ("tem_interest", "note"), ("tem_interest", "user_sub"),
    ("cases", "vertical"), ("route_interest", "phone"), ("route_interest", "details"),
    ("source_snapshots", "pending_sha"), ("source_snapshots", "pending_at")]  # empty = food, see verticals.py


def connect(path=":memory:"):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, col in ADDED_COLUMNS:  # existing SQLite files created before these columns
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    return con


def connect_pg(host, dbname, user, password):
    """host is the Cloud SQL socket dir, e.g. /cloudsql/PROJECT:REGION:INSTANCE"""
    import psycopg2
    return setup_pg(PG(psycopg2.connect(host=host, dbname=dbname, user=user, password=password)))


class PGPool:
    """Up to `size` Postgres connections shared by the request threads; schema set up once."""

    def __init__(self, host, dbname, user, password, size):
        from psycopg2.pool import ThreadedConnectionPool
        self.pool = ThreadedConnectionPool(1, size, host=host, dbname=dbname, user=user, password=password)
        first = self.get()
        try:
            setup_pg(first)
        finally:
            self.put(first)

    def get(self):
        """A connection that answers. One the server closed while it sat idle (Cloud SQL, 8 Nov 2026) still looks
        open to psycopg2 until a query fails on it, so each borrow runs SELECT 1 and swaps a dead one for a new one."""
        for _ in range(self.pool.maxconn + 1):
            raw = self.pool.getconn()
            try:
                cur = raw.cursor()
                cur.execute("SELECT 1")
                cur.close()
                raw.rollback()  # the check opened a transaction: end it, the request starts clean
            except Exception:
                self.pool.putconn(raw, close=True)
                continue
            return PG(raw)
        return PG(self.pool.getconn())

    def put(self, con, close=False):
        self.pool.putconn(con.raw, close=close)


def finish(con):
    """End of a request: keep what it wrote, drop a failed transaction (psycopg2 transaction status)."""
    raw = con.raw
    if raw.closed:
        return False
    status = raw.get_transaction_status()  # 0 idle, 1 active, 2 in transaction, 3 in error, 4 unknown
    if status == 3:
        raw.rollback()
    elif status == 2:  # unsaved writes: commit, as the shared connection's next commit used to
        raw.commit()
    elif status != 0:
        return False  # busy or broken: close it rather than reuse it
    return True


PG_ADDED_COLUMNS = [("cases", "org_id"), ("cases", "owner_sub"), ("cases", "company_id"), ("profiles", "plan"),
                    ("companies", "plan"), ("companies", "created_by"), ("memberships", "label")] + ADDED_COLUMNS


def setup_pg(con):
    """Schema setup, run once when an instance starts. ALTER TABLE locks the whole table in Postgres even when
    the column already exists (ADD COLUMN IF NOT EXISTS), and every query on that table queues behind the lock.
    New instances start under load, so only missing columns are added (3 Nov 2026: 30 replies at once timed out)."""
    con.executescript(SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"))
    have = {(r["table_name"], r["column_name"]) for r in con.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()").fetchall()}
    con.commit()
    for table, col in PG_ADDED_COLUMNS:
        if (table, col) not in have:
            con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT")
            con.commit()  # hold the table lock as briefly as possible
    return con


def log_event(con, case_id, actor, kind, data=None):
    con.execute("INSERT INTO events(case_id, at, actor, kind, data) VALUES (?,?,?,?,?)",
                (case_id, now(), actor, kind, json.dumps(data or {}, ensure_ascii=False)))
    con.commit()


def create_case(con, path_type, actor="agent", org_id=None, owner_sub=None):
    cid = str(uuid.uuid4())
    t = now()
    con.execute("INSERT INTO cases(id, path_type, org_id, owner_sub, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (cid, path_type, org_id, owner_sub, t, t))
    log_event(con, cid, actor, "case_created", {"path_type": path_type})
    return cid


def case_read(con, case_id):
    row = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        raise KeyError(case_id)
    out = dict(row)
    for k in ("company", "product", "market"):
        out[k] = json.loads(out[k])
    return out


def case_write(con, case_id, section, fields, actor="agent"):
    """Merge fields into company, product or market. Logs the change."""
    if section not in ("company", "product", "market"):
        raise ValueError("section must be company, product or market")
    cur = case_read(con, case_id)[section]
    cur.update(fields)
    con.execute(f"UPDATE cases SET {section}=?, updated_at=? WHERE id=?",
                (json.dumps(cur, ensure_ascii=False), now(), case_id))
    log_event(con, case_id, actor, "case_updated", {"section": section, "fields": fields})
    return cur


def load_history(con, case_id):
    row = con.execute("SELECT data FROM histories WHERE case_id=?", (case_id,)).fetchone()
    return json.loads(row["data"]) if row else []


def save_history(con, case_id, history):
    con.execute("INSERT INTO histories(case_id, data, updated_at) VALUES (?,?,?) "
                "ON CONFLICT (case_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (case_id, json.dumps(history, default=str, ensure_ascii=False), now()))
    con.commit()
