"""Parallel requests: threaded server, one pooled Postgres connection per request (2 Nov 2026)."""
import json
import os
import threading
import time
import unittest
import urllib.request
from unittest import mock

from vialibera import app, db


class FakeRaw:
    def __init__(self, status=0):
        self.closed, self.status, self.calls = False, status, []

    def get_transaction_status(self):
        return self.status

    def commit(self):
        self.calls.append("commit")
        self.status = 0

    def rollback(self):
        self.calls.append("rollback")
        self.status = 0


class FakePool:
    def __init__(self):
        self.out, self.returned, self.lock = set(), [], threading.Lock()

    def get(self):
        c = db.PG.__new__(db.PG)
        c.raw = FakeRaw()
        with self.lock:
            self.out.add(id(c))
        return c

    def put(self, c, close=False):
        with self.lock:
            self.out.discard(id(c))
            self.returned.append((c, close))


class Finish(unittest.TestCase):
    def con(self, status):
        c = db.PG.__new__(db.PG)
        c.raw = FakeRaw(status)
        return c

    def test_unsaved_writes_are_committed(self):
        c = self.con(2)
        self.assertTrue(db.finish(c))
        self.assertEqual(c.raw.calls, ["commit"])

    def test_failed_transaction_is_rolled_back(self):
        c = self.con(3)
        self.assertTrue(db.finish(c))
        self.assertEqual(c.raw.calls, ["rollback"])

    def test_broken_connection_is_not_reused(self):
        self.assertFalse(db.finish(self.con(4)))
        c = self.con(0)
        c.raw.closed = True
        self.assertFalse(db.finish(c))


class Pool(unittest.TestCase):
    def setUp(self):
        self.pool = FakePool()
        for p in (mock.patch.dict(os.environ, {"CLOUDSQL_INSTANCE": "test:eu:db"}),
                  mock.patch.object(app, "_pool", self.pool),
                  mock.patch.object(app, "_get_pool", lambda: self.pool)):
            p.start()
            self.addCleanup(p.stop)

    def test_each_thread_gets_its_own_connection_and_gives_it_back(self):
        n = app.POOL_SIZE
        seen, barrier = [], threading.Barrier(n)

        def work():
            try:
                c = app.con()
                self.assertIs(app.con(), c)  # same handle for the whole request
                c.raw  # first database use borrows a connection
                seen.append(id(c._pg))
                barrier.wait(timeout=5)  # the whole pool is in use at the same time
            finally:
                app.release_con()

        ts = [threading.Thread(target=work) for _ in range(n)]
        [t.start() for t in ts]
        [t.join(10) for t in ts]
        self.assertEqual(len(set(seen)), n)
        self.assertEqual(self.pool.out, set())
        self.assertEqual(len(self.pool.returned), n)

    def test_request_beyond_the_pool_waits_for_a_free_connection(self):
        held, got = [], threading.Event()

        def hold():
            held.append(app.con().raw)
            time.sleep(0.5)
            app.release_con()

        ts = [threading.Thread(target=hold) for _ in range(app.POOL_SIZE)]
        [t.start() for t in ts]
        time.sleep(0.1)  # the pool is now fully in use

        def extra():
            app.con().raw
            got.set()
            app.release_con()

        e = threading.Thread(target=extra)
        e.start()
        self.assertFalse(got.wait(0.2))  # still waiting
        self.assertTrue(got.wait(3))  # served once a connection came back
        [t.join(5) for t in ts + [e]]
        self.assertEqual(self.pool.out, set())

    def test_slots_are_released(self):
        for _ in range(app.POOL_SIZE * 3):  # more than the pool size, one after another
            app.con().raw
            app.release_con()
        self.assertEqual(self.pool.out, set())


class OutsideCalls(unittest.TestCase):
    """Step A: a request lends its connection back during slow outside calls (AI, VIES, Core...)."""

    def setUp(self):
        self.pool = FakePool()
        for p in (mock.patch.dict(os.environ, {"CLOUDSQL_INSTANCE": "test:eu:db"}),
                  mock.patch.object(app, "_pool", self.pool),
                  mock.patch.object(app, "_get_pool", lambda: self.pool)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(app.release_con)

    def test_connection_is_lent_back_during_an_outside_call_and_borrowed_again_after(self):
        c = app.con()
        first = c.raw
        first.status = 2  # unsaved writes
        with db.outside_call():
            self.assertEqual(self.pool.out, set())  # nothing held while waiting
            self.assertEqual(first.calls, ["commit"])  # writes saved before lending it back
        self.assertIsNotNone(c.raw)  # the same handle works again: borrows a connection
        self.assertEqual(len(self.pool.out), 1)
        app.release_con()
        self.assertEqual(self.pool.out, set())

    def test_many_slow_requests_share_few_connections(self):
        # 3 x the pool size, each "waiting for the AI" for 0.3 s: none should wait for a connection
        n, waited = app.POOL_SIZE * 3, []

        def request():
            try:
                c = app.con()
                c.raw  # read the case
                with db.outside_call():
                    time.sleep(0.3)  # the AI is thinking
                t = time.time()
                c.raw  # save the reply
                waited.append(time.time() - t)
            finally:
                app.release_con()

        ts = [threading.Thread(target=request) for _ in range(n)]
        t0 = time.time()
        [t.start() for t in ts]
        [t.join(10) for t in ts]
        self.assertEqual(len(waited), n)
        self.assertLess(time.time() - t0, 0.8)  # holding connections through the wait: 3 batches x 0.3 s, over 0.9 s
        self.assertEqual(self.pool.out, set())

    def test_no_effect_without_a_request(self):
        with db.outside_call():
            pass
        self.assertEqual(self.pool.returned, [])


class ThreadedServer(unittest.TestCase):
    def test_slow_requests_run_in_parallel(self):
        active, peak, lock = [0], [0], threading.Lock()

        def slow_get(handler):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.3)
            with lock:
                active[0] -= 1
            handler._send(200, {"ok": True})

        with mock.patch.dict(os.environ, {"CLOUDSQL_INSTANCE": "test:eu:db"}), \
                mock.patch.object(app.Handler, "_get", slow_get), mock.patch.object(app, "release_con", lambda: None):
            srv = app.Server(("127.0.0.1", 0), app.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{srv.server_address[1]}/healthz"
            t0 = time.time()
            ts = [threading.Thread(target=lambda: json.loads(urllib.request.urlopen(url, timeout=5).read())) for _ in range(10)]
            [t.start() for t in ts]
            [t.join(5) for t in ts]
            took = time.time() - t0
            srv.shutdown()
        self.assertGreaterEqual(peak[0], 5)
        self.assertLess(took, 2.0)  # one at a time would take 3 s


class SchemaSetup(unittest.TestCase):
    """Instance start must not lock tables when the schema is already up to date (3 Nov 2026)."""

    class FakePG:
        def __init__(self, existing):
            self.existing, self.sql = existing, []

        def executescript(self, script):
            self.sql.append("SCRIPT")

        def execute(self, sql, params=()):
            self.sql.append(sql)
            rows = [{"table_name": t, "column_name": c} for t, c in self.existing]
            return mock.Mock(fetchall=lambda: rows)

        def commit(self):
            pass

    def test_no_alter_when_every_column_exists(self):
        pg = self.FakePG(db.PG_ADDED_COLUMNS)
        db.setup_pg(pg)
        self.assertEqual([s for s in pg.sql if "ALTER" in s], [])

    def test_only_missing_columns_are_added(self):
        pg = self.FakePG([c for c in db.PG_ADDED_COLUMNS if c != ("source_snapshots", "page_text")])
        db.setup_pg(pg)
        self.assertEqual([s for s in pg.sql if "ALTER" in s],
                         ["ALTER TABLE source_snapshots ADD COLUMN IF NOT EXISTS page_text TEXT"])


class HoldDiagnostics(unittest.TestCase):
    def setUp(self):
        self.pool = FakePool()
        for p in (mock.patch.dict(os.environ, {"CLOUDSQL_INSTANCE": "test:eu:db"}),
                  mock.patch.object(app, "_pool", self.pool),
                  mock.patch.object(app, "_get_pool", lambda: self.pool),
                  mock.patch.object(app, "HOLD_LOG_S", 0.05)):
            p.start()
            self.addCleanup(p.stop)
        self.logs = []
        p = mock.patch.object(app, "_log", self.logs.append)
        p.start()
        self.addCleanup(p.stop)

    def test_long_hold_is_logged_with_path_and_place(self):
        app._local.path = "POST /chat"
        app.con().raw
        time.sleep(0.1)
        app.release_con()
        self.assertEqual(len(self.logs), 1)
        self.assertIn("DB_HOLD path=POST /chat", self.logs[0])

    def test_hold_line_says_how_much_time_was_in_queries(self):
        app._local.path = "POST /chat"
        c = app.con()
        pg = c._get()
        pg.execute = lambda sql, params=(): time.sleep(0.04 if "consents" in sql else 0.01)
        c.execute("SELECT 1 FROM consents WHERE user_sub=?", ("u",))
        c.execute("SELECT 2")
        time.sleep(0.05)
        app.release_con()
        self.assertIn("queries=2", self.logs[0])
        self.assertIn("[SELECT 1 FROM consents WHERE user_sub=?]", self.logs[0])

    def test_short_hold_is_not_logged(self):
        app.con().raw
        app.release_con()
        self.assertEqual(self.logs, [])

    def test_busy_lists_the_holders(self):
        slots = threading.BoundedSemaphore(1)
        slots.acquire()  # the only connection is taken
        with mock.patch.object(app, "_slots", slots), mock.patch.object(slots, "acquire", lambda timeout: False):
            app._holders[1] = ("POST /chat", time.time() - 12, "agent.py:95 turn")
            self.addCleanup(app._holders.pop, 1, None)
            app._local.path = "POST /me"
            with self.assertRaises(RuntimeError):
                app.con().raw
        self.assertIn("DB_BUSY path=POST /me", self.logs[0])
        self.assertIn("POST /chat held 12", self.logs[0])
        self.assertIn("agent.py:95 turn", self.logs[0])
        app._local.con = None


class ColdStart(unittest.TestCase):
    """3 Nov 2026: on a new instance, 20 requests each fetched the AI key while holding a database connection."""

    def test_ai_client_is_created_once_under_parallel_requests(self):
        made = []

        def slow_secret(name):
            time.sleep(0.2)
            return "key"
        with mock.patch.object(app, "_client", None), mock.patch.object(app, "get_secret", slow_secret), \
                mock.patch.object(app.anthropic, "Anthropic", lambda api_key: made.append(api_key) or object()):
            ts = [threading.Thread(target=app.client) for _ in range(20)]
            [t.start() for t in ts]
            [t.join(5) for t in ts]
        self.assertEqual(len(made), 1)

    def test_secret_fetch_does_not_hold_a_database_connection(self):
        from vialibera import secrets
        pool, seen = FakePool(), []

        class SM:
            def access_secret_version(self, request):
                seen.append(set(pool.out))  # what is held while the network call runs
                return mock.Mock(payload=mock.Mock(data=b"value"))
        with mock.patch.dict(os.environ, {"CLOUDSQL_INSTANCE": "test:eu:db", "GCP_PROJECT": "p"}), \
                mock.patch.object(app, "_pool", pool), mock.patch.object(app, "_get_pool", lambda: pool), \
                mock.patch.object(secrets, "_client", lambda: SM()):
            os.environ.pop("SOME_SECRET", None)
            app.con().raw  # the request holds a connection
            self.assertEqual(secrets.get_secret("SOME_SECRET"), "value")
            app.release_con()
        self.assertEqual(seen, [set()])

    def test_warm_up_prepares_and_survives_failures(self):
        logs = []
        with mock.patch.object(app, "_log", logs.append), mock.patch.object(app, "client", lambda: None), \
                mock.patch.object(app.voice, "api_key", mock.Mock(side_effect=RuntimeError("no key"))):
            app.warm_up()
        self.assertTrue(any("ai client ready" in l for l in logs))
        self.assertTrue(any("voice key failed" in l for l in logs))

    def test_missing_voice_key_is_not_fetched_on_every_request(self):
        from vialibera import voice
        calls = []

        def missing(name):
            calls.append(name)
            raise RuntimeError("not found")
        with mock.patch.object(voice, "_KEY", None), mock.patch.object(voice, "_KEY_AT", 0.0), \
                mock.patch.object(voice, "get_secret", missing), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ELEVENLABS_API_KEY", None)
            for _ in range(10):
                voice.api_key()
        self.assertEqual(len(calls), 1)
