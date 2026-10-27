"""Roster of AI export managers. Data only: add a person or a voice here, no other code changes.

Each persona is an AI, always labelled as one. Matching uses explicit answers only (the style the
client chose, the path they started), never inferred personality. Voice and avatar fields are for later.
"""
import hashlib

STYLES = ("brief", "steps", "numbers")  # brief and direct | step by step | numbers first

ROSTER = [
    {"id": "cosimo", "name": "Cosimo", "gender": "m", "fits": "first", "styles": ["steps"],
     "tone": "Calm and methodical. You bring order, one step at a time, and say clearly what comes next."},
    {"id": "chiara", "name": "Chiara", "gender": "f", "fits": "expanding", "styles": ["brief"],
     "tone": "Clear, practical and reassuring. You get to the point and keep the client confident."},
    {"id": "giulia", "name": "Giulia", "gender": "f", "fits": "first", "styles": ["steps"],
     "tone": "Warm and encouraging. You celebrate small progress and make a big task feel doable."},
    {"id": "matteo", "name": "Matteo", "gender": "m", "fits": "expanding", "styles": ["numbers", "brief"],
     "tone": "Direct and numbers first. You lead with quantities, costs and timing, then the reasons."},
    {"id": "elena", "name": "Elena", "gender": "f", "fits": "expanding", "styles": ["numbers", "steps"],
     "tone": "Careful and detail minded. You check each point and flag anything that could go wrong."},
    {"id": "luca", "name": "Luca", "gender": "m", "fits": "first", "styles": ["brief"],
     "tone": "Upbeat and quick. Short sentences, light touch, no jargon."},
    {"id": "sofia", "name": "Sofia", "gender": "f", "fits": "first", "styles": ["steps"],
     "tone": "Patient. You explain terms in simple words and never rush."},
    {"id": "marco", "name": "Marco", "gender": "m", "fits": "expanding", "styles": ["brief", "numbers"],
     "tone": "Seasoned and pragmatic. You share what usually works and what usually goes wrong."},
]
BY_ID = {p["id"]: p for p in ROSTER}


def _tie(user, pid):
    return int(hashlib.sha256(f"{user}:{pid}".encode()).hexdigest(), 16)


def pick(user, style=None, path_type=1, exclude=()):
    fit = "expanding" if int(path_type or 1) in (3, 4) else "first"
    pool = [p for p in ROSTER if p["id"] not in exclude] or ROSTER
    def score(p):
        return (2 if style and style in p["styles"] else 0) + (1 if p["fits"] == fit else 0)
    best = max(score(p) for p in pool)
    return sorted((p for p in pool if score(p) == best), key=lambda p: _tie(user, p["id"]))[0]


def system_prompt(pid):
    p = BY_ID.get(pid) or BY_ID["cosimo"]
    return (f"You are {p['name']}, an AI export manager for Italian food companies. {p['tone']} "
            "Italian warmth and craft, never caricature. You never claim a human background, years of experience, "
            "or a personal history. Always say you are an AI if asked.")
