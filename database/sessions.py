"""
database.sessions – CRUD helpers for game session documents with in-memory fallback.

Each session document stores the persona, full chat history, timing info,
and the final evaluation result once the game ends.
"""

import time
from datetime import datetime, timezone

from database.connection import get_db

_in_memory_sessions = {}


def create_session(
    session_id: str,
    name: str,
    mode: str,
    persona: str,
    opening: str,
    duration: int,
) -> dict:
    """
    Insert a new session document and return it.
    """
    db = get_db()
    now = time.time()

    session = {
        "_id": session_id,
        "name": name[:24],
        "mode": mode,
        "persona": persona,
        "history": [
            {
                "from": "ai_user",
                "text": opening,
                "at": now,
            }
        ],
        "started_at": now,
        "ends_at": now + duration,
        "finished": False,
        "created_at": datetime.now(timezone.utc),
    }

    if db is not None:
        try:
            db["sessions"].insert_one(session)
        except Exception as e:
            print(f"MongoDB write failed ({e}); storing session in memory.")
            _in_memory_sessions[session_id] = session
    else:
        _in_memory_sessions[session_id] = session

    return session


def get_session(session_id: str) -> dict | None:
    """Return the session document for session_id, or None if not found."""
    db = get_db()
    if db is not None:
        try:
            res = db["sessions"].find_one({"_id": session_id})
            if res:
                return res
        except Exception:
            pass
    return _in_memory_sessions.get(session_id)


def update_session(session_id: str, updates: dict) -> None:
    """Apply a $set patch to the session document."""
    db = get_db()
    if db is not None:
        try:
            db["sessions"].update_one({"_id": session_id}, {"$set": updates})
            return
        except Exception:
            pass
    if session_id in _in_memory_sessions:
        _in_memory_sessions[session_id].update(updates)


def add_history_entry(session_id: str, entry: dict) -> None:
    """Append a single turn to the session's history array."""
    db = get_db()
    if db is not None:
        try:
            db["sessions"].update_one({"_id": session_id}, {"$push": {"history": entry}})
            return
        except Exception:
            pass
    if session_id in _in_memory_sessions:
        _in_memory_sessions[session_id].setdefault("history", []).append(entry)


def delete_session(session_id: str) -> None:
    """Permanently delete a session document."""
    db = get_db()
    if db is not None:
        try:
            db["sessions"].delete_one({"_id": session_id})
        except Exception:
            pass
    _in_memory_sessions.pop(session_id, None)
