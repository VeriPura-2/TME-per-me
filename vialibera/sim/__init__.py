"""Simulated features. Everything here is removable: delete the file, set the
feature to "live" in features.py. Nothing outside this folder imports from it
except through sim.tag().

Rules: sample data only, never a claim about the user's own product, no
compliance verdicts, no invented statistics.
"""
from ..features import is_sim

NOTE = {
    "it": "Esempio simulato. Non è un controllo del tuo prodotto.",
    "en": "Simulated example. Not a check of your product.",
}


def tag(feature, payload):
    """Mark a payload as simulated. The UI badge and note come from this flag alone."""
    if not is_sim(feature):
        raise RuntimeError(f"{feature} is not in sim mode; remove its sim call")
    return {"simulated": True, "feature": feature, "note": NOTE, "data": payload}
