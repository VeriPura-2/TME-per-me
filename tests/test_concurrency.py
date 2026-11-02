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
                self.assertIs(app.con(), c)  # same connection for the whole request
                seen.append(id(c))
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
            held.append(app.con())
            time.sleep(0.5)
            app.release_con()

        ts = [threading.Thread(target=hold) for _ in range(app.POOL_SIZE)]
        [t.start() for t in ts]
        time.sleep(0.1)  # the pool is now fully in use

        def extra():
            app.con()
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
            app.con()
            app.release_con()
        self.assertEqual(self.pool.out, set())


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
