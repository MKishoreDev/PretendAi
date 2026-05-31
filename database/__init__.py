"""
database package – public re-exports for the rest of the application.

Connection management lives in database.connection to avoid circular imports
(leaderboard.py and sessions.py need get_db, and this file imports from them).
"""

from database.connection import get_db, init_db, close_db
from database.leaderboard import add_score, get_leaderboard, get_top_scores, get_recent_scores, count_scores
from database.sessions import create_session, get_session, update_session, add_history_entry, delete_session

__all__ = [
    # connection
    "get_db", "init_db", "close_db",
    # leaderboard
    "add_score", "get_leaderboard", "get_top_scores", "get_recent_scores", "count_scores",
    # sessions
    "create_session", "get_session", "update_session", "add_history_entry", "delete_session",
]
