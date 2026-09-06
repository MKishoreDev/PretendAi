"""
database.leaderboard – helpers for storing and querying leaderboard scores.

Each entry records the player's name, game mode, final score, rank label, and
average reply time so the leaderboard can be filtered and sorted in various ways.
"""

from datetime import datetime, timezone

from database.connection import get_db


_memory_leaderboard = []


def add_score(
    name: str,
    mode: str,
    final: int,
    rank: str,
    avg_reply_ms: int,
    archetype: dict = None,
    character_name: str = "",
) -> dict:
    db = get_db()
    now = datetime.now(timezone.utc)
    entry = {
        "name": name[:24],
        "mode": mode,
        "final": final,
        "rank": rank,
        "avg_reply_ms": avg_reply_ms,
        "archetype": archetype or {},
        "character_name": character_name,
        "at": int(now.timestamp()),
        "created_at": now,
    }

    if db is not None:
        db["leaderboard"].insert_one(entry)
    else:
        _memory_leaderboard.append(entry)
    return {k: v for k, v in entry.items() if k != "_id"}


def get_top_scores(mode: str = None, limit: int = 25) -> list[dict]:
    db = get_db()
    if db is not None:
        filter_query = {} if not mode or mode == "all" else {"mode": mode}
        scores = list(
            db["leaderboard"]
            .find(filter_query)
            .sort("final", -1)
            .limit(limit)
        )
        return [{k: v for k, v in s.items() if k != "_id"} for s in scores]

    res = [s for s in _memory_leaderboard if not mode or mode == "all" or s.get("mode") == mode]
    res.sort(key=lambda x: x.get("final", 0), reverse=True)
    return res[:limit]


def get_recent_scores(mode: str = None, limit: int = 25) -> list[dict]:
    db = get_db()
    if db is not None:
        filter_query = {} if not mode or mode == "all" else {"mode": mode}
        scores = list(
            db["leaderboard"]
            .find(filter_query)
            .sort("at", -1)
            .limit(limit)
        )
        return [{k: v for k, v in s.items() if k != "_id"} for s in scores]

    res = [s for s in _memory_leaderboard if not mode or mode == "all" or s.get("mode") == mode]
    res.sort(key=lambda x: x.get("at", 0), reverse=True)
    return res[:limit]


def get_leaderboard(mode: str = None, limit: int = 25) -> dict:
    return {
        "top": get_top_scores(mode, limit),
        "recent": get_recent_scores(mode, limit),
    }


def count_scores(mode: str = None) -> int:
    db = get_db()
    if db is not None:
        filter_query = {} if not mode or mode == "all" else {"mode": mode}
        return db["leaderboard"].count_documents(filter_query)
    return len([s for s in _memory_leaderboard if not mode or mode == "all" or s.get("mode") == mode])
