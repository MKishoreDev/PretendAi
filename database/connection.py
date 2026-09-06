"""
database.connection – MongoDB connection singleton.

Kept in its own module so leaderboard.py and sessions.py can import get_db
without triggering the circular import that would occur if they imported from
database/__init__.py (which itself imports from those two modules).
"""

import os

from pymongo import DESCENDING, MongoClient
from pymongo.errors import ServerSelectionTimeoutError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load the connection URI from the environment so credentials are never
# committed to source control.  Copy .env.example → .env and fill it in.
MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://localhost:27017",  # safe local fallback for development
)

_in_memory_mode = False
_client = None
_db = None


def get_db():
    """
    Return the shared MongoDB database instance, creating it on first call.
    Falls back gracefully if MongoDB is unreachable.
    """
    global _client, _db, _in_memory_mode
    if _in_memory_mode:
        return None
    if _db is None:
        try:
            _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=1000)
            # Ping verifies the connection is alive before we hand it out.
            _client.admin.command("ping")
            _db = _client["pretendai"]
            print("Connected to MongoDB: pretendai")
        except Exception as e:
            print(f"MongoDB connection unavailable ({e}). Running in in-memory mode.")
            _in_memory_mode = True
            return None
    return _db


def close_db():
    """Close the MongoDB connection and reset the singletons."""
    global _client, _db
    if _client:
        _client.close()
        _db = None
        _client = None
        print("MongoDB connection closed")


def init_db():
    """
    Ensure required collections and indexes exist.

    Called once at application startup. Safe to run on an already-initialised
    database.
    """
    db = get_db()

    # Sessions collection – TTL index auto-expires documents after 7 days (604,800 seconds).
    if "sessions" not in db.list_collection_names():
        db.create_collection("sessions")

    # Safely recreate TTL index if it exists with older 1-hour expiration
    try:
        db["sessions"].create_index("created_at", expireAfterSeconds=604800)
    except Exception:
        try:
            db["sessions"].drop_index("created_at_1")
            db["sessions"].create_index("created_at", expireAfterSeconds=604800)
        except Exception:
            pass

    # Leaderboard collection – indexed for both top-score and recent queries.
    if "leaderboard" not in db.list_collection_names():
        db.create_collection("leaderboard")
    db["leaderboard"].create_index([("final", DESCENDING)])
    db["leaderboard"].create_index([("at", DESCENDING)])

    print(f"Database initialised with collections: {db.list_collection_names()}")
