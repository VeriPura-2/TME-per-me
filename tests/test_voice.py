import json
import os
import unittest

os.environ["DB_PATH"] = ":memory:"
os.environ["ELEVENLABS_API_KEY"] = "test-key"
os.environ["ELEVENLABS_VOICE_DEFAULT"] = "voice123"
os.environ["LOCAL_STORE"] = __import__("tempfile").mkdtemp()
os.environ["VOICE_REPLIES"] = "1"
from vialibera import accounts, app, voice


def who(u):
    return {"user": u, "org": None, "roles": []}


class VoiceTest(unittest.TestCase):
    def setUp(self):
        voice._KEY = None
        accounts.record_consent(app.con(), "v1", app.TERMS_VERSION, "it", True)
        app.con().execute("DELETE FROM voice_usage"); app.con().commit()
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

    def test_total_budget_stops_everyone(self):
        os.environ["VOICE_TOTAL_CHARS"] = "30"
        try:
            self.assertEqual(app.handle_speak({"text": "x" * 20}, who("v1"), post=self.fake)[0], 200)
            code, out = app.handle_speak({"text": "y" * 20}, who("v1"), post=self.fake)
            self.assertEqual((code, out["error"]), (429, "voice_budget_used"))
        finally:
            del os.environ["VOICE_TOTAL_CHARS"]

    def test_intro_is_generated_once_then_served_free(self):
        accounts.save_profile(app.con(), "v1", persona_id="cosimo")
        c1, a1 = app.handle_intro({"lang": "it"}, who("v1"), post=self.fake)
        c2, a2 = app.handle_intro({"lang": "it"}, who("v1"), post=self.fake)
        self.assertEqual((c1, c2, a1, a2), (200, 200, b"ID3audio", b"ID3audio"))
        self.assertEqual(len(self.calls), 1)
        said = json.loads(self.calls[0].data)["text"]
        self.assertIn("Cosimo", said)
        self.assertIn("per iscritto", said)

    def test_intro_english_says_rest_is_text(self):
        accounts.save_profile(app.con(), "v1", persona_id="giulia")
        app.handle_intro({"lang": "en"}, who("v1"), post=self.fake)
        self.assertIn("continue in writing", json.loads(self.calls[0].data)["text"])

    def test_intro_picks_a_persona_when_none(self):
        app.con().execute("DELETE FROM profiles WHERE user_sub='v1'"); app.con().commit()
        self.assertEqual(app.handle_intro({"lang": "it"}, who("v1"), post=self.fake)[0], 200)
        self.assertIsNotNone(accounts.get_profile(app.con(), "v1")["persona_id"])

    def test_gender_lists_choose_stable_voice(self):
        os.environ["ELEVENLABS_VOICES_F"] = "f1,f2"; os.environ["ELEVENLABS_VOICES_M"] = "m1,m2"
        try:
            self.assertIn(voice.voice_for("chiara"), ("f1", "f2"))
            self.assertIn(voice.voice_for("marco"), ("m1", "m2"))
            self.assertEqual(voice.voice_for("chiara"), voice.voice_for("chiara"))
        finally:
            del os.environ["ELEVENLABS_VOICES_F"], os.environ["ELEVENLABS_VOICES_M"]

    def test_reply_voice_can_be_switched_off(self):
        os.environ["VOICE_REPLIES"] = "0"
        try:
            self.assertEqual(app.handle_speak({"text": "Ciao"}, who("v1"), post=self.fake)[0], 404)
        finally:
            os.environ["VOICE_REPLIES"] = "1"

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
