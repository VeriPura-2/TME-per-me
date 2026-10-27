"""Case file store, event log and evidence record (SQLite for staging)."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  path_type INTEGER NOT NULL,          -- 1..4, see product flow spec section 2
  status TEXT NOT NULL DEFAULT 'draft',
  company TEXT NOT NULL DEFAULT '{}',  -- JSON
  product TEXT NOT NULL DEFAULT '{}',  -- JSON
  market TEXT NOT NULL DEFAULT '{}',   -- JSON
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS histories (
  case_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,                  -- JSON list of API messages
  updated_at TEXT NOT NULL
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


class PG:
    """Thin wrapper giving a psycopg2 connection the sqlite3 calls the code uses."""

    postgres = True

    def __init__(self, raw):
        import psycopg2.extras
        self.raw = raw
        self._cur = lambda: raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=()):
        cur = self._cur()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executescript(self, script):
        for stmt in script.split(";"):
            if stmt.strip():
                self.execute(stmt)
        self.raw.commit()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


def connect(path=":memory:"):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def connect_pg(host, dbname, user, password):
    """host is the Cloud SQL socket dir, e.g. /cloudsql/PROJECT:REGION:INSTANCE"""
    import psycopg2
    con = PG(psycopg2.connect(host=host, dbname=dbname, user=user, password=password))
    con.executescript(SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"))
    return con


def log_event(con, case_id, actor, kind, data=None):
    con.execute("INSERT INTO events(case_id, at, actor, kind, data) VALUES (?,?,?,?,?)",
                (case_id, now(), actor, kind, json.dumps(data or {}, ensure_ascii=False)))
    con.commit()


def create_case(con, path_type, actor="agent"):
    cid = str(uuid.uuid4())
    t = now()
    con.execute("INSERT INTO cases(id, path_type, created_at, updated_at) VALUES (?,?,?,?)",
                (cid, path_type, t, t))
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
