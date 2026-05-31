"""
database.leaderboard – helpers for storing and querying leaderboard scores.

Each entry records the player's name, game mode, final score, rank label, and
average reply time so the leaderboard can be filtered and sorted in various ways.
"""

from datetime import datetime, timezone

from database import get_db


def add_score(
    name: str,
    mode: str,
    final: int,
    rank: str,
    avg_reply_ms: int,
) -> dict:
    """
    Insert a new leaderboard entry and return it (without the MongoDB _id).

    Args:
        name:         Player display name (truncated to 24 chars).
        mode:         Game mode the score was achieved in.
        final:        Overall score 0-100 from the LLM judge.
        rank:         Rank label (e.g. "GPT-Class") assigned by the judge.
        avg_reply_ms: Player's average reply time in milliseconds.

    Returns:
        The inserted entry dict.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    entry = {
        "name": name[:24],
        "mode": mode,
        "final": final,
        "rank": rank,
        "avg_reply_ms": avg_reply_ms,
        # Integer Unix timestamp used for sorting in get_recent_scores.
        "at": int(now.timestamp()),
        # Full datetime used by any TTL index if added in future.
        "created_at": now,
    }

    db["leaderboard"].insert_one(entry)
    # Return the entry without the MongoDB-generated _id field.
    return {k: v for k, v in entry.items() if k != "_id"}


def get_top_scores(mode: str = None, limit: int = 25) -> list[dict]:
    """
    Return the highest-scoring entries, sorted by final score descending.

    Args:
        mode:  Optional mode filter ("all" or None returns every mode).
        limit: Maximum number of entries to return.
    """
    db = get_db()
    filter_query = {} if not mode or mode == "all" else {"mode": mode}
    scores = list(
        db["leaderboard"]
        .find(filter_query)
        .sort("final", -1)
        .limit(limit)
    )
    return [{k: v for k, v in s.items() if k != "_id"} for s in scores]


def get_recent_scores(mode: str = None, limit: int = 25) -> list[dict]:
    """
    Return the most recently submitted entries, sorted by time descending.

    Args:
        mode:  Optional mode filter ("all" or None returns every mode).
        limit: Maximum number of entries to return.
    """
    db = get_db()
    filter_query = {} if not mode or mode == "all" else {"mode": mode}
    scores = list(
        db["leaderboard"]
        .find(filter_query)
        .sort("at", -1)
        .limit(limit)
    )
    return [{k: v for k, v in s.items() if k != "_id"} for s in scores]


def get_leaderboard(mode: str = None, limit: int = 25) -> dict:
    """
    Return both top scores and recent scores in a single dict.

    Used by the /api/leaderboard endpoint.
    """
    return {
        "top": get_top_scores(mode, limit),
        "recent": get_recent_scores(mode, limit),
    }


def count_scores(mode: str = None) -> int:
    """Return the total number of leaderboard entries, optionally filtered by mode."""
    db = get_db()
    filter_query = {} if not mode or mode == "all" else {"mode": mode}
    return db["leaderboard"].count_documents(filter_query)
