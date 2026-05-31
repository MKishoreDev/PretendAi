"""
models – Pydantic request body schemas for the PretendAI API.
"""

from typing import Optional

from pydantic import BaseModel


class StartReq(BaseModel):
    """Body for POST /api/start – begin a new game session."""
    mode: str = "classic"           # one of: classic | interview | chaos | jailbreak
    name: Optional[str] = "Anonymous"  # display name shown on the leaderboard


class ReplyReq(BaseModel):
    """Body for POST /api/reply – submit the player's response to the AI persona."""
    session_id: str   # hex UUID returned by /api/start
    reply: str        # the player's message (pretending to be an AI assistant)


class FinishReq(BaseModel):
    """Body for POST /api/finish – end the session and trigger evaluation."""
    session_id: str   # hex UUID returned by /api/start
