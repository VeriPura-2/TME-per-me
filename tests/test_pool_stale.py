"""A pooled connection the server closed while idle is replaced, not handed out (8 Nov 2026)."""
import unittest
from unittest import mock

from vialibera import db, jobs


class Raw:
    def __init__(self, dead=False):
        self.dead, self.calls = dead, []

    def cursor(self):
        if self.dead:
            raise RuntimeError("server closed the connection unexpectedly")
        raw = self

        class Cur:
            def execute(self, sql):
                raw.calls.append(sql)

            def close(self):
                pass
        return Cur()

    def rollback(self):
        self.calls.append("rollback")


class FakeInner:
    maxconn = 3

    def __init__(self, raws):
        self.raws, self.closed = list(raws), []

    def getconn(self):
        return self.raws.pop(0)

    def putconn(self, raw, close=False):
        if close:
            self.closed.append(raw)


class FakePG:
    def __init__(self, raw):
        self.raw = raw


def pool_with(*raws):
    p = db.PGPool.__new__(db.PGPool)
    p.pool = FakeInner(raws)
    return p


class StalePool(unittest.TestCase):
    def setUp(self):  # the real wrapper needs psycopg2, which the SQLite test run does not use
        patcher = mock.patch.object(db, "PG", FakePG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dead_connection_is_replaced(self):
        dead, live = Raw(dead=True), Raw()
        p = pool_with(dead, live)
        got = p.get()
        self.assertIs(got.raw, live)
        self.assertEqual(p.pool.closed, [dead])
        self.assertEqual(live.calls, ["SELECT 1", "rollback"])  # checked, then the check's transaction ended

    def test_live_connection_is_kept(self):
        live = Raw()
        p = pool_with(live)
        self.assertIs(p.get().raw, live)
        self.assertEqual(p.pool.closed, [])


class OperationalError(Exception):
    pass


class FlakyCon:
    def __init__(self, fails):
        self.fails, self.rolled = fails, 0

    def execute(self, sql, params=()):
        if self.fails:
            self.fails -= 1
            raise OperationalError("server closed the connection unexpectedly")
        return type("R", (), {"fetchone": lambda self: None})()

    def rollback(self):
        self.rolled += 1


class SnapshotRetry(unittest.TestCase):
    def test_one_drop_is_retried(self):
        c = FlakyCon(1)
        self.assertIsNone(jobs._read_snapshot(c, "https://x"))
        self.assertEqual(c.rolled, 1)

    def test_second_drop_is_raised(self):
        with self.assertRaises(OperationalError):
            jobs._read_snapshot(FlakyCon(2), "https://x")

    def test_other_errors_are_not_retried(self):
        class Boom(FlakyCon):
            def execute(self, sql, params=()):
                raise ValueError("bad")
        with self.assertRaises(ValueError):
            jobs._read_snapshot(Boom(0), "https://x")


if __name__ == "__main__":
    unittest.main()
