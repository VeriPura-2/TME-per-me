import os
import time
import unittest
from types import SimpleNamespace as NS

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ.update(DB_PATH=":memory:", AUTH0_DOMAIN="t.eu.auth0.com", AUTH0_AUDIENCE="https://api.vialibera")
from vialibera import app, auth

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def tok(key=KEY, **over):
    c = {"sub": "u1", "org_id": "org_a", "iss": "https://t.eu.auth0.com/",
         "aud": "https://api.vialibera", "exp": int(time.time()) + 600}
    c.update(over)
    c = {k: v for k, v in c.items() if v is not None}
    return "Bearer " + jwt.encode(c, key, algorithm="RS256")


def kf(_):
    return KEY.public_key()


class Fake:
    messages = NS(create=lambda **kw: NS(content=[NS(type="text", text="ok", model_dump=lambda: {"type": "text", "text": "ok"})]))


class AuthTest(unittest.TestCase):
    def test_valid(self):
        w = auth.verify(tok(), kf)
        self.assertEqual((w["user"], w["org"]), ("u1", "org_a"))

    def test_rejects(self):
        for bad in (None, "Bearer x", tok(key=OTHER), tok(exp=int(time.time()) - 5),
                    tok(aud="nope"), tok(iss="https://evil/")):
            with self.assertRaises(auth.AuthError):
                auth.verify(bad, kf)

    def test_company_isolation(self):
        a = {"user": "u1", "org": "org_a", "roles": []}
        b = {"user": "u2", "org": "org_b", "roles": []}
        from vialibera import accounts
        for w in (a, b):
            accounts.record_consent(app.con(), w["user"], app.TERMS_VERSION, "it", True)
        _, out = app.handle_chat({"message": "hi"}, llm=Fake(), who=a)
        self.assertEqual(app.handle_chat({"message": "x", "case_id": out["case_id"]}, llm=Fake(), who=a)[0], 200)
        self.assertEqual(app.handle_chat({"message": "x", "case_id": out["case_id"]}, llm=Fake(), who=b)[0], 404)
        self.assertEqual(app.handle_chat({"message": "x", "case_id": "nope"}, llm=Fake(), who=a)[0], 404)


if __name__ == "__main__":
    unittest.main()
