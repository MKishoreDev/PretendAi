"""
database.sessions – CRUD helpers for game session documents.

Each session document stores the persona, full chat history, timing info,
and the final evaluation result once the game ends.
"""

import time
from datetime import datetime, timezone

from database.connection import get_db


_memory_sessions = {}


def create_session(
    session_id: str,
    name: str,
    mode: str,
    persona: str,
    opening: str,
    duration: int,
    character_name: str = "",
    challenge_id: str = None,
) -> dict:
    db = get_db()
    now = time.time()

    session = {
        "_id": session_id,
        "name": name[:24],
        "mode": mode,
        "persona": persona,
        "character_name": character_name,
        "challenge_id": challenge_id,
        "history": [
            {
                "from": "ai_user",
                "text": opening,
                "at": now,
            }
        ],
        "started_at": now,
        "ends_at": now + duration,
        "duration": duration,
        "finished": False,
        "created_at": datetime.now(timezone.utc),
    }

    if db is not None:
        db["sessions"].insert_one(session)
    else:
        _memory_sessions[session_id] = session
    return session


def get_session(session_id: str) -> dict | None:
    db = get_db()
    if db is not None:
        return db["sessions"].find_one({"_id": session_id})
    return _memory_sessions.get(session_id)


def update_session(session_id: str, updates: dict) -> None:
    db = get_db()
    if db is not None:
        db["sessions"].update_one({"_id": session_id}, {"$set": updates})
    elif session_id in _memory_sessions:
        _memory_sessions[session_id].update(updates)


def add_history_entry(session_id: str, entry: dict) -> None:
    db = get_db()
    if db is not None:
        db["sessions"].update_one({"_id": session_id}, {"$push": {"history": entry}})
    elif session_id in _memory_sessions:
        _memory_sessions[session_id].setdefault("history", []).append(entry)


def delete_session(session_id: str) -> None:
    db = get_db()
    if db is not None:
        db["sessions"].delete_one({"_id": session_id})
    else:
        _memory_sessions.pop(session_id, None)
