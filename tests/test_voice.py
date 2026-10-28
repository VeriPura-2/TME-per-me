import json
import os
import unittest

os.environ["DB_PATH"] = ":memory:"
os.environ["ELEVENLABS_API_KEY"] = "test-key"
os.environ["ELEVENLABS_VOICE_DEFAULT"] = "voice123"
from vialibera import accounts, app, voice


def who(u):
    return {"user": u, "org": None, "roles": []}


class VoiceTest(unittest.TestCase):
    def setUp(self):
        voice._KEY = None
        accounts.record_consent(app.con(), "v1", app.TERMS_VERSION, "it", True)
        self.calls = []

    def fake(self, req):
        self.calls.append(req)
        return b"ID3audio"

    def test_clean_removes_options_and_markdown(self):
        out = voice.clean("**Ciao** il prodotto?\nOPTIONS: vino | pasta")
        self.assertEqual(out, "Ciao il prodotto?")

    def test_speak_calls_eu_endpoint_with_key_header_and_no_key_in_body(self):
        code, audio = app.handle_speak({"text": "Ciao"}, who("v1"), post=self.fake)
        self.assertEqual((code, audio), (200, b"ID3audio"))
        r = self.calls[0]
        self.assertTrue(r.full_url.startswith("https://api.eu.residency.elevenlabs.io/v1/text-to-speech/voice123"))
        self.assertEqual(r.get_header("Xi-api-key"), "test-key")
        self.assertNotIn("test-key", r.data.decode())
        self.assertEqual(json.loads(r.data)["model_id"], "eleven_flash_v2_5")

    def test_intro_names_the_ai(self):
        accounts.save_profile(app.con(), "v1", persona_id="cosimo")
        app.handle_speak({"text": "Ciao", "intro": True}, who("v1"), post=self.fake)
        self.assertIn("Cosimo", json.loads(self.calls[0].data)["text"])
        self.assertIn("intelligenza artificiale", json.loads(self.calls[0].data)["text"])

    def test_daily_limit(self):
        os.environ["VOICE_DAILY_CHARS"] = "30"
        try:
            self.assertEqual(app.handle_speak({"text": "x" * 20}, who("v1"), post=self.fake)[0], 200)
            self.assertEqual(app.handle_speak({"text": "y" * 20}, who("v1"), post=self.fake)[0], 429)
        finally:
            del os.environ["VOICE_DAILY_CHARS"]

    def test_provider_failure_is_a_clean_error(self):
        def boom(r):
            raise RuntimeError("down")
        self.assertEqual(app.handle_speak({"text": "Ciao"}, who("v1"), post=boom)[0], 502)

    def test_not_configured(self):
        saved = os.environ.pop("ELEVENLABS_VOICE_DEFAULT")
        try:
            self.assertEqual(app.handle_speak({"text": "Ciao"}, who("v1"), post=self.fake)[0], 503)
        finally:
            os.environ["ELEVENLABS_VOICE_DEFAULT"] = saved

    def test_long_reply_is_capped(self):
        self.assertLessEqual(len(voice.clean("Frase. " * 500)), voice.MAX_REPLY_CHARS)


if __name__ == "__main__":
    unittest.main()
