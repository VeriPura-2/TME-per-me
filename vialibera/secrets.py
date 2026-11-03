"""Secret loading. Env var first (local dev), then Google Cloud Secret Manager."""
import os
import threading

from . import db

_sm = None  # one Secret Manager client per instance: creating one sets up a network channel (slow)
_sm_lock = threading.Lock()


def _client():
    global _sm
    with _sm_lock:
        if _sm is None:
            from google.cloud import secretmanager
            _sm = secretmanager.SecretManagerServiceClient()
    return _sm


def get_secret(name, project=None):
    val = os.environ.get(name)
    if val:
        return val
    project = project or os.environ.get("GCP_PROJECT")
    if not project:
        raise RuntimeError(f"{name} not in environment and GCP_PROJECT not set")
    path = f"projects/{project}/secrets/{name}/versions/latest"
    with db.outside_call():  # network call: no database connection held meanwhile
        return _client().access_secret_version(request={"name": path}).payload.data.decode("utf-8")
