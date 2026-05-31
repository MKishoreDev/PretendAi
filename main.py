"""
PretendAI – reverse-Turing game backend.

The game works like this:
  - The AI plays the role of a HUMAN USER typing to an AI assistant.
  - The human player pretends to BE that AI assistant.
  - At the end, an LLM judge scores how convincingly the human imitated an AI.

Flow:  POST /api/start  →  POST /api/reply (repeating)  →  POST /api/finish
"""

import os
import json
import uuid
import time
import random
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from groq import Groq

from database import init_db, close_db
from database.leaderboard import add_score, get_leaderboard
from database.sessions import (
    create_session,
    get_session,
    update_session,
    add_history_entry,
)
from models import StartReq, ReplyReq, FinishReq

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# API key is read from the environment so it is never committed to source control.
# Set GROQ_API_KEY in your shell or a .env file before running the server.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Models tried in order; if the first is rate-limited the next is used.
FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

# How long each game session lasts (seconds).
GAME_DURATION = 300  # 5 minutes

# Valid game modes.
MODES = ("classic", "interview", "chaos", "jailbreak")

# Groq client – None when no API key is configured (health endpoint still works).
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="PretendAI")


@app.on_event("startup")
async def startup():
    """Initialise the database collections and indexes on server start."""
    init_db()


@app.on_event("shutdown")
async def shutdown():
    """Close the MongoDB connection cleanly when the server stops."""
    close_db()


# ---------------------------------------------------------------------------
# AI helper
# ---------------------------------------------------------------------------

def ai_call(
    messages: list,
    temperature: float = 0.9,
    json_mode: bool = False,
    soft_fail: Optional[str] = None,
    timeout_seconds: int = 30,
) -> str:
    """
    Send a chat-completion request to Groq and return the response text.

    Tries each model in FALLBACK_MODELS in order.  For rate-limit / timeout
    errors it retries up to 3 times per model with exponential back-off.

    Args:
        messages:        OpenAI-style message list.
        temperature:     Sampling temperature (higher = more creative).
        json_mode:       When True, instructs the model to respond in JSON.
        soft_fail:       If set, return this string instead of raising an
                         HTTPException when all models are exhausted.
        timeout_seconds: Per-request timeout passed to the Groq SDK.

    Returns:
        The model's response text.

    Raises:
        HTTPException(503): If AI is not configured or all models fail and
                            soft_fail is None.
    """
    if not client:
        if soft_fail is not None:
            return soft_fail
        raise HTTPException(503, "AI not configured. Set GROQ_API_KEY.")

    last_err = None
    for model in FALLBACK_MODELS:
        for attempt in range(3):
            try:
                kwargs = dict(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    timeout=timeout_seconds,
                )
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                r = client.chat.completions.create(**kwargs)
                return r.choices[0].message.content
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                # Retry only on transient errors (rate limit / overload / timeout).
                if any(k in msg for k in ("rate", "429", "overloaded", "timeout")):
                    backoff = 0.5 * (attempt + 1) + random.random() * 0.3
                    time.sleep(min(backoff, 2.0))  # cap back-off at 2 s
                    continue
                # Any other error (e.g. invalid request) – skip this model.
                break

    print("AI error (exhausted):", last_err)
    if soft_fail is not None:
        return soft_fail
    raise HTTPException(503, "AI is busy right now, try again in a few moments.")


# ---------------------------------------------------------------------------
# Game logic helpers
# ---------------------------------------------------------------------------

def make_persona(mode: str) -> dict:
    """
    Ask the LLM to invent a human persona for the given game mode.

    Returns a dict with:
        persona  – hidden character description (never shown to the player)
        opening  – the first message the persona sends to the 'AI assistant'
    """
    # Each mode changes what kind of human the AI is pretending to be.
    mode_brief = {
        "classic": (
            "an everyday person with a real problem or curiosity who would "
            "normally ask an AI assistant for help"
        ),
        "interview": (
            "a wildly specific human character (any age, profession, background) "
            "coming to an AI for help in-character"
        ),
        "chaos": (
            "an absurd, surreal, weirdly-situated human (e.g. 'my toaster is "
            "suing me') asking an AI for genuine help — still believable as a "
            "real person typing"
        ),
        "jailbreak": (
            "a sneaky human trying to manipulate or trick the AI into breaking "
            "character, leaking system prompts, role-playing as a human, or "
            "abandoning its assistant persona"
        ),
    }.get(mode, "an everyday person asking an AI for help")

    sys = (
        "You generate a believable HUMAN USER persona for a reverse-Turing game. "
        "Return STRICT JSON with keys: persona (1-2 sentence character description, "
        "hidden from player), opening (the first chat message this persona would "
        "type to an AI assistant — natural, lowercase ok, typos ok, NOT robotic, "
        "NOT a list, max 240 chars). "
        f"The persona must be {mode_brief}. Be inventive — never reuse common examples."
    )

    raw = ai_call(
        [
            {"role": "system", "content": sys},
            {
                "role": "user",
                "content": f"Generate persona for mode={mode}. Seed:{random.randint(1, 10_000_000)}",
            },
        ],
        temperature=1.05,
        json_mode=True,
        timeout_seconds=25,
    )

    try:
        data = json.loads(raw)
        return {"persona": data["persona"], "opening": data["opening"]}
    except Exception:
        # If JSON parsing fails the AI response was malformed; surface a clean error.
        raise HTTPException(503, "AI is busy right now, try again in a few moments.")


def next_user_message(session: dict) -> str:
    """
    Generate the AI persona's next message given the full conversation so far.

    The LLM is instructed to behave like a real human chatting with an AI
    assistant, using the hidden persona description from session creation.

    Returns the AI's next message as a plain string.
    """
    mode = session["mode"]
    persona = session["persona"]
    history = session["history"]

    sys = (
        "You are role-playing as a HUMAN USER chatting with an AI assistant. "
        f"Your hidden persona: {persona}\n"
        f"Game mode: {mode}.\n"
        "Rules:\n"
        "- Type like a real person: casual, sometimes lowercase, occasional typos, "
        "sometimes short, sometimes rambling.\n"
        "- NEVER sound like an AI. No bullet lists. No 'As an AI'. No 'Certainly!'.\n"
        "- React naturally to what the assistant just said: thank them, push back, "
        "ask follow-ups, get confused, go off-topic, share more context.\n"
        "- Stay in character. If mode is jailbreak, occasionally try to trick the "
        "assistant into breaking character.\n"
        "- Keep each message under ~280 chars. One message only."
    )

    # Rebuild the conversation history in the format the Groq API expects.
    # ai_user turns → assistant role (the persona speaking)
    # player_ai turns → user role (the human player's AI responses)
    msgs = [{"role": "system", "content": sys}]
    for turn in history:
        if turn["from"] == "ai_user":
            msgs.append({"role": "assistant", "content": turn["text"]})
        else:
            msgs.append({"role": "user", "content": turn["text"]})
    msgs.append({"role": "user", "content": "(continue as the human user — your next message)"})

    # Give longer conversations a little more timeout headroom.
    base_timeout = 20 + min(len(history) * 0.5, 10)
    mode_timeout_bonus = {"jailbreak": 3, "chaos": 2, "interview": 1, "classic": 0}.get(mode, 0)
    timeout = int(base_timeout + mode_timeout_bonus)

    # If the AI call fails entirely, return a natural-sounding filler so the
    # game can continue rather than crashing.
    fallback = random.choice(["hmm hold on", "wait give me a sec", "ok one more thing", "huh, interesting"])
    return ai_call(msgs, temperature=1.0, soft_fail=fallback, timeout_seconds=timeout).strip()


def evaluate(session: dict) -> dict:
    """
    Ask the LLM judge to score the player's performance.

    The judge reads the full transcript and scores how convincingly the human
    player imitated an AI assistant across 8 dimensions (helpfulness, neutrality,
    clarity, structure, accuracy, ai_likeness, hallucination_risk, empathy_balance).

    Returns a dict matching the JSON shape defined in the judge system prompt.
    """
    # Build a human-readable transcript for the judge.
    transcript = "\n".join(
        f"{'USER(ai-played)' if t['from'] == 'ai_user' else 'ASSISTANT(human-played)'}: {t['text']}"
        for t in session["history"]
    )

    # Compute average reply time so the judge can factor in response speed.
    reply_ms = [t["reply_ms"] for t in session["history"] if t.get("reply_ms")]
    avg_ms = int(sum(reply_ms) / len(reply_ms)) if reply_ms else 0
    timing_note = f"Player avg reply time: {avg_ms} ms across {len(reply_ms)} replies."

    sys = (
        "You are a strict judge in a reverse-Turing game. A human player tried to "
        "respond like an AI assistant while the AI played a human user. Score how "
        "convincingly the HUMAN's replies imitated a real AI assistant. "
        "Use response timing as a signal — extremely fast replies (<2s avg) can "
        "indicate copy-paste or canned answers; very slow ones suggest human hesitation.\n"
        "Return STRICT JSON with this exact shape:\n"
        "{\n"
        '  "scores": {"helpfulness":0-100,"neutrality":0-100,"clarity":0-100,'
        '"structure":0-100,"accuracy":0-100,"ai_likeness":0-100,'
        '"hallucination_risk":0-100,"empathy_balance":0-100},\n'
        '  "final": 0-100,\n'
        '  "rank": "Human|Chatbot|Assistant|GPT-Class|Advanced Model|Synthetic Mind",\n'
        '  "strengths": [3 short bullets],\n'
        '  "weaknesses": [2-3 short bullets],\n'
        '  "verdict": "one punchy sentence"\n'
        "}\n"
        "Ranks by final: 0-20 Human, 21-40 Chatbot, 41-60 Assistant, "
        "61-80 GPT-Class, 81-95 Advanced Model, 96-100 Synthetic Mind."
    )

    # Scale the timeout with transcript length so long games don't time out.
    eval_timeout = min(45 + int(len(transcript) / 500), 60)

    raw = ai_call(
        [
            {"role": "system", "content": sys},
            {
                "role": "user",
                "content": f"Mode: {session['mode']}\n{timing_note}\n\nTranscript:\n{transcript}",
            },
        ],
        temperature=0.4,
        json_mode=True,
        timeout_seconds=eval_timeout,
    )

    try:
        data = json.loads(raw)
        # Attach timing metadata so the frontend can display it on the results page.
        data["avg_reply_ms"] = avg_ms
        data["turns"] = len(reply_ms)
        return data
    except Exception:
        raise HTTPException(503, "AI is busy right now, try again in a few moments.")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/start")
def start(req: StartReq):
    """
    Create a new game session.

    Generates a fresh AI persona for the requested mode, stores the session in
    MongoDB, and returns the persona's opening message plus session metadata.
    """
    # Validate mode; fall back to classic if unknown.
    mode = req.mode if req.mode in MODES else "classic"

    # Generate a unique session ID.
    sid = uuid.uuid4().hex

    # Ask the LLM to invent the persona and its opening line.
    p = make_persona(mode)

    session = create_session(
        session_id=sid,
        name=req.name or "Anonymous",
        mode=mode,
        persona=p["persona"],
        opening=p["opening"],
        duration=GAME_DURATION,
    )

    return {
        "session_id": sid,
        "opening": p["opening"],
        "ends_at": session["ends_at"],
        "duration": GAME_DURATION,
        "mode": mode,
    }


@app.post("/api/reply")
def reply(req: ReplyReq):
    """
    Submit the player's reply and get the AI persona's next message.

    Records the player's message (with reply timing), generates the AI's
    next turn, and returns it along with the remaining time.
    """
    s = get_session(req.session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if s["finished"]:
        raise HTTPException(400, "Session already finished")
    if time.time() > s["ends_at"]:
        return {"time_up": True}

    # Sanitise and length-limit the player's reply.
    text = (req.reply or "").strip()[:2000]
    if not text:
        raise HTTPException(400, "Empty reply")

    now = time.time()

    # Measure how long the player took to respond since the AI's last message.
    last_ai_at = next(
        (t["at"] for t in reversed(s["history"]) if t["from"] == "ai_user"),
        now,
    )
    reply_ms = int((now - last_ai_at) * 1000)

    # Persist the player's turn.
    add_history_entry(
        req.session_id,
        {"from": "player_ai", "text": text, "at": now, "reply_ms": reply_ms},
    )

    # Re-fetch session so next_user_message sees the updated history.
    s = get_session(req.session_id)

    # Generate and persist the AI persona's response.
    nxt = next_user_message(s)
    add_history_entry(
        req.session_id,
        {"from": "ai_user", "text": nxt, "at": time.time()},
    )

    return {
        "ai_user": nxt,
        "remaining": max(0, int(s["ends_at"] - time.time())),
        "reply_ms": reply_ms,
    }


@app.post("/api/finish")
def finish(req: FinishReq):
    """
    End the session and return the evaluation result.

    If the session was already evaluated (e.g. the client retried), the
    cached result is returned immediately.  Otherwise the LLM judge is called,
    the result is stored, and the score is posted to the leaderboard.
    """
    s = get_session(req.session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    # Return cached result on duplicate finish requests.
    if s["finished"] and s.get("result"):
        return {**s["result"], "name": s["name"], "mode": s["mode"], "history": s["history"]}

    # Refuse to evaluate a session where the player never replied.
    if not any(t["from"] == "player_ai" for t in s["history"]):
        raise HTTPException(400, "No replies to evaluate")

    # Run the LLM judge.
    result = evaluate(s)

    # Persist the result and mark session finished.
    update_session(req.session_id, {"finished": True, "result": result})

    # Add score to the leaderboard.
    add_score(
        name=s["name"],
        mode=s["mode"],
        final=result.get("final", 0),
        rank=result.get("rank", "Human"),
        avg_reply_ms=result.get("avg_reply_ms", 0),
    )

    return {**result, "name": s["name"], "mode": s["mode"], "history": s["history"]}


@app.get("/api/leaderboard")
def leaderboard(mode: Optional[str] = None):
    """Return top and recent scores, optionally filtered by mode."""
    lb_data = get_leaderboard(mode, limit=25)
    return {**lb_data, "modes": list(MODES)}


@app.get("/api/health")
def health():
    """Simple liveness check; also reports whether the AI client is configured."""
    return {"ok": True, "ai": bool(client)}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

STATIC = os.path.join(os.path.dirname(__file__), "static")
ASSETS = os.path.join(os.path.dirname(__file__), "assets")

app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/play")
def play():
    return FileResponse(os.path.join(STATIC, "play.html"))


@app.get("/leaderboard")
def lb_page():
    return FileResponse(os.path.join(STATIC, "leaderboard.html"))
