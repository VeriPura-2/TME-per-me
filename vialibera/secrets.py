"""Secret loading. Env var first (local dev), then Google Cloud Secret Manager."""
import os


def get_secret(name, project=None):
    val = os.environ.get(name)
    if val:
        return val
    project = project or os.environ.get("GCP_PROJECT")
    if not project:
        raise RuntimeError(f"{name} not in environment and GCP_PROJECT not set")
    from google.cloud import secretmanager
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project}/secrets/{name}/versions/latest"
    return client.access_secret_version(request={"name": path}).payload.data.decode("utf-8")
