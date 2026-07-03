"""Lazy Firestore client — uses ADC on Agent Engine, service account key locally."""

import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore as _fs

_client = None


def db():
    global _client
    if _client is not None:
        return _client

    if not firebase_admin._apps:
        key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred, {"projectId": os.environ.get("GOOGLE_CLOUD_PROJECT", "fello-pt")})
        else:
            # On Agent Engine / GCE — Application Default Credentials are available
            firebase_admin.initialize_app(options={"projectId": os.environ.get("GOOGLE_CLOUD_PROJECT", "fello-pt")})

    _client = _fs.client()
    return _client
