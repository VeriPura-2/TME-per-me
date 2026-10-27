"""Object storage for client documents. Local folder for dev and tests, Google Cloud Storage in the EU for staging.

Files are streamed through the app after an access check, so there are no public or signed links.
"""
import os


class LocalStore:
    def __init__(self, root):
        self.root = root

    def put(self, key, data):
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, key):
        with open(os.path.join(self.root, key), "rb") as f:
            return f.read()


class GcsStore:
    def __init__(self, bucket):
        from google.cloud import storage
        self.bucket = storage.Client().bucket(bucket)

    def put(self, key, data):
        self.bucket.blob(key).upload_from_string(data)

    def get(self, key):
        return self.bucket.blob(key).download_as_bytes()


_store = None


def store():
    global _store
    if _store is None:
        bucket = os.environ.get("STORAGE_BUCKET")
        _store = GcsStore(bucket) if bucket else LocalStore(os.environ.get("LOCAL_STORE", "/tmp/vialibera_files"))
    return _store
