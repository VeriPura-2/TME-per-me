"""Spoken replies through ElevenLabs text to speech. Server side only: the key never reaches the browser.

Config (environment, or Secret Manager for the key):
  ELEVENLABS_API_KEY      secret, issued by the EU workspace if EU residency is used
  ELEVENLABS_BASE         default https://api.eu.residency.elevenlabs.io (EU residency, Enterprise plan)
  ELEVENLABS_MODEL        default eleven_flash_v2_5 (supports Italian)
  ELEVENLABS_VOICES       JSON map of persona id to voice id, e.g. {"cosimo": "..."}
  ELEVENLABS_VOICE_DEFAULT  fallback voice id
  VOICE_DAILY_CHARS       per user per day, default 1500
  VOICE_TOTAL_CHARS       hard budget across all users, default 15000 (protects the credits)
Stock library voices only. No cloned voices of real people.
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import db
from .secrets import get_secret

MAX_REPLY_CHARS = 700
INTRO = {"it": "Sono {name}, un export manager con intelligenza artificiale.",
         "en": "I am {name}, an AI export manager."}
_KEY = None


def api_key():
    global _KEY
    if _KEY is None:
        try:
            _KEY = get_secret("ELEVENLABS_API_KEY")
        except Exception:
            return None
    return _KEY


def configured():
    return bool(api_key())


def clean(text):
    """Remove the option buttons line and markdown marks, cap the length at a sentence."""
    lines = [l for l in text.splitlines() if not l.strip().startswith("OPTIONS:")]
    t = re.sub(r"[*_`#>]+", "", " ".join(lines))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > MAX_REPLY_CHARS:
        cut = t[:MAX_REPLY_CHARS]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = cut[:end + 1] if end > 200 else cut
    return t


def voice_for(persona_id):
    try:
        m = json.loads(os.environ.get("ELEVENLABS_VOICES", "{}"))
    except ValueError:
        m = {}
    return m.get(persona_id) or os.environ.get("ELEVENLABS_VOICE_DEFAULT")


def _used_today(con, user):
    row = con.execute("SELECT chars FROM voice_usage WHERE user_sub=? AND day=?", (user, db.now()[:10])).fetchone()
    return row["chars"] if row else 0


def _add_usage(con, user, n):
    con.execute("INSERT INTO voice_usage(user_sub, day, chars) VALUES (?,?,?) "
                "ON CONFLICT (user_sub, day) DO UPDATE SET chars=voice_usage.chars+excluded.chars",
                (user, db.now()[:10], n))
    con.execute("INSERT INTO usage_events(case_id, at, provider, units) VALUES (?,?,?,?)",
                (None, db.now(), "elevenlabs", n))
    con.commit()


def speak(con, user, text, persona_id, lang="it", intro_name=None, post=None):
    """Returns (status, audio bytes or error dict). `post` is injectable for tests."""
    key = api_key()
    voice = voice_for(persona_id)
    if not key or not voice:
        return 503, {"error": "voice_not_configured"}
    t = clean(text)
    if intro_name:
        t = INTRO["en" if lang == "en" else "it"].format(name=intro_name) + " " + t
    if not t:
        return 400, {"error": "nothing to say"}
    limit = int(os.environ.get("VOICE_DAILY_CHARS", "1500"))
    if _used_today(con, user) + len(t) > limit:
        return 429, {"error": "voice_daily_limit"}
    total = con.execute("SELECT COALESCE(SUM(chars), 0) AS n FROM voice_usage").fetchone()["n"]
    if total + len(t) > int(os.environ.get("VOICE_TOTAL_CHARS", "15000")):
        return 429, {"error": "voice_budget_used"}
    base = os.environ.get("ELEVENLABS_BASE", "https://api.eu.residency.elevenlabs.io").rstrip("/")
    body = json.dumps({"text": t, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")}).encode()
    req = urllib.request.Request(f"{base}/v1/text-to-speech/{voice}?output_format=mp3_44100_64", data=body,
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    try:
        audio = (post or (lambda r: urllib.request.urlopen(r, timeout=30).read()))(req)
    except urllib.error.HTTPError as e:
        return 502, {"error": "voice_provider_error", "status": e.code}
    except Exception:
        return 502, {"error": "voice_unavailable"}
    _add_usage(con, user, len(t))
    return 200, audio
