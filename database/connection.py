"""
database.connection – MongoDB connection singleton with graceful fallback.

Kept in its own module so leaderboard.py and sessions.py can import get_db
without triggering circular imports.
"""

import os
from pymongo import DESCENDING, MongoClient

# Connection URI loaded from environment
MONGODB_URI = os.environ.get("MONGODB_URI", "")

_client = None
_db = None
_db_attempted = False


def get_db():
    """
    Return the shared MongoDB database instance, or None if unavailable.
    """
    global _client, _db, _db_attempted
    if not _db_attempted and _db is None:
        _db_attempted = True
        if not MONGODB_URI:
            print("No MONGODB_URI provided. Operating in in-memory mode.")
            _db = None
            return None
        try:
            timeout_ms = int(os.environ.get("MONGODB_TIMEOUT_MS", "1500"))
            _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=timeout_ms)
            _client.admin.command("ping")
            _db = _client["pretendai"]
            print("Connected to MongoDB: pretendai")
        except Exception as e:
            print(f"MongoDB connection failed ({e}). Operating in in-memory mode.")
            _db = None
    return _db


def close_db():
    """Close the MongoDB connection and reset singletons."""
    global _client, _db, _db_attempted
    if _client:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
    _db = None
    _db_attempted = False
    print("MongoDB connection closed")


def init_db():
    """
    Ensure required collections and indexes exist. Safe against connection failures.
    """
    try:
        db = get_db()
        if not db:
            print("Skipping DB index creation (MongoDB not connected).")
            return

        if "sessions" not in db.list_collection_names():
            db.create_collection("sessions")
        db["sessions"].create_index("created_at", expireAfterSeconds=3600)

        if "leaderboard" not in db.list_collection_names():
            db.create_collection("leaderboard")
        db["leaderboard"].create_index([("final", DESCENDING)])
        db["leaderboard"].create_index([("at", DESCENDING)])

        print(f"Database initialised with collections: {db.list_collection_names()}")
    except Exception as e:
        print(f"Database init warning: {e}")
