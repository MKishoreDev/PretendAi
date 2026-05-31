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

# Module-level singletons; populated by get_db() on first call.
_client = None
_db = None


def get_db():
    """
    Return the shared MongoDB database instance, creating it on first call.

    Uses a module-level singleton so the connection is reused across requests.

    Raises:
        ServerSelectionTimeoutError: If MongoDB is unreachable.
    """
    global _client, _db
    if _db is None:
        try:
            _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            # Ping verifies the connection is alive before we hand it out.
            _client.admin.command("ping")
            _db = _client["pretendai"]
            print("Connected to MongoDB: pretendai")
        except ServerSelectionTimeoutError as e:
            print(f"MongoDB connection failed: {e}")
            raise
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

    Called once at application startup.  Safe to run on an already-initialised
    database – MongoDB ignores duplicate create_collection / create_index calls.
    """
    db = get_db()

    # Sessions collection – TTL index auto-expires documents after 1 hour.
    if "sessions" not in db.list_collection_names():
        db.create_collection("sessions")
    db["sessions"].create_index("created_at", expireAfterSeconds=3600)

    # Leaderboard collection – indexed for both top-score and recent queries.
    if "leaderboard" not in db.list_collection_names():
        db.create_collection("leaderboard")
    db["leaderboard"].create_index([("final", DESCENDING)])
    db["leaderboard"].create_index([("at", DESCENDING)])

    print(f"Database initialised with collections: {db.list_collection_names()}")
