import unittest

from vialibera import db


class PostgresSchemaSplit(unittest.TestCase):
    """Postgres runs the schema statement by statement (split on ';'). Every piece must be a whole statement."""

    def test_every_statement_is_complete(self):
        script = "\n".join(line.split("--", 1)[0] for line in db.SCHEMA.splitlines())
        for stmt in script.split(";"):
            s = stmt.strip()
            if s:
                self.assertTrue(s.upper().startswith("CREATE TABLE"), s[:80])
                self.assertEqual(s.count("("), s.count(")"), s[:80])

    def test_no_semicolon_inside_comments(self):
        for line in db.SCHEMA.splitlines():
            if "--" in line:
                self.assertNotIn(";", line.split("--", 1)[1], line)
