"""
database.leaderboard – helpers for storing and querying leaderboard scores with in-memory fallback.

Each entry records the player's name, game mode, final score, rank label, and
average reply time so the leaderboard can be filtered and sorted in various ways.
"""

from datetime import datetime, timezone

from database.connection import get_db

_in_memory_leaderboard = []


def add_score(
    name: str,
    mode: str,
    final: int,
    rank: str,
    avg_reply_ms: int,
) -> dict:
    """
    Insert a new leaderboard entry and return it (without the MongoDB _id).
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    entry = {
        "name": name[:24],
        "mode": mode,
        "final": final,
        "rank": rank,
        "avg_reply_ms": avg_reply_ms,
        "at": int(now.timestamp()),
        "created_at": now,
    }

    if db is not None:
        try:
            db["leaderboard"].insert_one(entry)
        except Exception as e:
            print(f"MongoDB insert_one failed ({e}); storing score in memory.")
            _in_memory_leaderboard.append(entry)
    else:
        _in_memory_leaderboard.append(entry)

    return {k: v for k, v in entry.items() if k != "_id"}


def get_top_scores(mode: str = None, limit: int = 25) -> list[dict]:
    """Return the highest-scoring entries, sorted by final score descending."""
    db = get_db()
    if db is not None:
        try:
            filter_query = {} if not mode or mode == "all" else {"mode": mode}
            scores = list(
                db["leaderboard"]
                .find(filter_query)
                .sort("final", -1)
                .limit(limit)
            )
            return [{k: v for k, v in s.items() if k != "_id"} for s in scores]
        except Exception:
            pass

    items = _in_memory_leaderboard
    if mode and mode != "all":
        items = [x for x in items if x.get("mode") == mode]
    sorted_items = sorted(items, key=lambda x: x.get("final", 0), reverse=True)[:limit]
    return [{k: v for k, v in s.items() if k != "_id"} for s in sorted_items]


def get_recent_scores(mode: str = None, limit: int = 25) -> list[dict]:
    """Return the most recently submitted entries, sorted by time descending."""
    db = get_db()
    if db is not None:
        try:
            filter_query = {} if not mode or mode == "all" else {"mode": mode}
            scores = list(
                db["leaderboard"]
                .find(filter_query)
                .sort("at", -1)
                .limit(limit)
            )
            return [{k: v for k, v in s.items() if k != "_id"} for s in scores]
        except Exception:
            pass

    items = _in_memory_leaderboard
    if mode and mode != "all":
        items = [x for x in items if x.get("mode") == mode]
    sorted_items = sorted(items, key=lambda x: x.get("at", 0), reverse=True)[:limit]
    return [{k: v for k, v in s.items() if k != "_id"} for s in sorted_items]


def get_leaderboard(mode: str = None, limit: int = 25) -> dict:
    """Return both top scores and recent scores in a single dict."""
    return {
        "top": get_top_scores(mode, limit),
        "recent": get_recent_scores(mode, limit),
    }


def count_scores(mode: str = None) -> int:
    """Return total leaderboard entries count."""
    db = get_db()
    if db is not None:
        try:
            filter_query = {} if not mode or mode == "all" else {"mode": mode}
            return db["leaderboard"].count_documents(filter_query)
        except Exception:
            pass
    if mode and mode != "all":
        return len([x for x in _in_memory_leaderboard if x.get("mode") == mode])
    return len(_in_memory_leaderboard)
