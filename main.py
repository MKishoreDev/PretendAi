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
import hashlib
from datetime import datetime, timezone
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

# Default preferred models tried in order of priority.
DEFAULT_PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.2-3b-preview",
    "llama-3.2-1b-preview",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "qwen-2.5-32b",
]

# Cache structure for dynamic models list retrieved from Groq API
_cached_models: list[str] = []
_cache_timestamp: float = 0.0
CACHE_TTL_SECONDS = 600.0  # 10 minutes cache TTL


def get_dynamic_fallback_models(force_refresh: bool = False) -> list[str]:
    """
    Dynamically fetch available active models from Groq API and return an ordered list.
    Results are cached for CACHE_TTL_SECONDS unless force_refresh is True.
    """
    global _cached_models, _cache_timestamp

    now = time.time()
    if not force_refresh and _cached_models and (now - _cache_timestamp < CACHE_TTL_SECONDS):
        return _cached_models

    if not client:
        return DEFAULT_PREFERRED_MODELS

    try:
        models_page = client.models.list()
        # Handle both list attributes and raw iterable responses
        data = getattr(models_page, "data", models_page)

        available_ids = set()
        for item in data:
            model_id = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else str(item))
            if model_id:
                low = model_id.lower()
                # Exclude non-chat / specialized models (speech, guardrails, embeddings)
                if any(x in low for x in ("whisper", "guard", "embed", "safetensors")):
                    continue
                available_ids.add(model_id)

        if not available_ids:
            _cached_models = DEFAULT_PREFERRED_MODELS
            _cache_timestamp = now
            return _cached_models

        # Prioritize preferred models in order, then append any remaining active chat models
        ordered = [m for m in DEFAULT_PREFERRED_MODELS if m in available_ids]
        remaining = sorted(list(available_ids - set(ordered)))
        ordered.extend(remaining)

        _cached_models = ordered
        _cache_timestamp = now
        return _cached_models
    except Exception as e:
        print(f"Warning: Failed to fetch models from Groq API ({e}). Falling back to default list.")
        if _cached_models:
            return _cached_models
        return DEFAULT_PREFERRED_MODELS


# How long each game session lasts (seconds).
GAME_DURATION = 300  # 5 minutes
BLITZ_DURATION = 90  # 90 seconds

# Valid game modes.
MODES = ("classic", "interview", "chaos", "jailbreak", "blitz", "daily")

# AI Model Archetypes for personality badges
ARCHETYPES = [
    {"name": "The Cold Quantum Core", "icon": "🧊", "tagline": "0% Fluff. 100% Logic."},
    {"name": "The Corporate Assistant", "icon": "💼", "tagline": "As an AI, I am happy to help!"},
    {"name": "The Speedrunner LLM", "icon": "⚡", "tagline": "High speed, zero hesitation."},
    {"name": "The Unshakeable Guardrail", "icon": "🛡️", "tagline": "Impenetrable. Prompt-injection proof."},
    {"name": "The Creative Hallucinator", "icon": "🎨", "tagline": "Richly imaginative, factually ambiguous."},
    {"name": "The Synthetic Mind", "icon": "🤖", "tagline": "Indistinguishable from GPT-4o."},
]

_daily_character_cache = {}


def get_daily_character(date_str: Optional[str] = None) -> dict:
    """
    Generate or return the cached Daily PopAI trending character for a given date (UTC YYYY-MM-DD).
    The AI dynamically selects a trending character (real life, pop culture, anime, tech, history, viral figures)
    and assigns the SPECIFIC AI ASSISTANT ROLE the human player must imitate to convince them!
    """
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if date_str in _daily_character_cache:
        return _daily_character_cache[date_str]

    fallback_pool = [
        {
            "name": "Tony Stark",
            "source": "Iron Man / Marvel",
            "ai_target_role": "J.A.R.V.I.S. (Stark AI Assistant)",
            "ai_role_brief": "Polite British sophistication, call him 'Sir', address Mark suit telemetry calmly.",
            "persona": "Tony Stark testing JARVIS after a late-night lab session tinkering on new armor.",
            "opening": "Jarvis, I need a quantum stability check on the Mark 85 arc reactor right now. Are we stable?",
        },
        {
            "name": "Batman",
            "source": "DC Comics",
            "ai_target_role": "Batcomputer Mainframe",
            "ai_role_brief": "Monochrome, hyper-direct, zero emotion, processing forensic data.",
            "persona": "Batman asking the Batcomputer to process Gotham harbor surveillance and suit repairs.",
            "opening": "Computer. Query Gotham Port surveillance logs from midnight and calculate Batmobile armor wear.",
        },
        {
            "name": "Elon Musk",
            "source": "Tech & Space",
            "ai_target_role": "Starship Flight Computer",
            "ai_role_brief": "Engineering precision, thrust telemetry data, rapid calculation.",
            "persona": "Elon Musk analyzing Starship rocket telemetry with the Flight Computer AI.",
            "opening": "hey, Starship Raptor engine #4 is showing micro-vibrations at 80% thrust. What do the numbers say?",
        },
        {
            "name": "Gordon Ramsay",
            "source": "Culinary / TV",
            "ai_target_role": "Smart Chef AI Assistant",
            "ai_role_brief": "Precise culinary temperature data, respectful yet firm, no excuses.",
            "persona": "Gordon Ramsay storming into a high-tech kitchen demanding AI recipe validation.",
            "opening": "Listen to me! The risotto is underseasoned and the lamb is raw! Give me the exact sous-vide timing immediately!",
        },
        {
            "name": "Gandalf",
            "source": "Lord of the Rings",
            "ai_target_role": "Palantír Oracle AI",
            "ai_role_brief": "Mystical yet structured, wise, respectful of ancient lore.",
            "persona": "Gandalf asking an ancient magical AI oracle about hobbit diets and ring lore.",
            "opening": "Greetings Oracle. The hobbits insist on 'second breakfast'. Is this vital to their constitution?",
        },
    ]

    seed_num = int(hashlib.md5(date_str.encode()).hexdigest(), 16)
    default_char = fallback_pool[seed_num % len(fallback_pool)]

    if not client:
        _daily_character_cache[date_str] = default_char
        return default_char

    try:
        sys = (
            "You generate a trending daily character (real life, viral news, movies, anime, history, tech, or gaming) "
            f"for a reverse-Turing daily challenge on date {date_str}.\n"
            "Return STRICT JSON with keys:\n"
            "- name: Character name (e.g. Tony Stark, Gordon Ramsay, Elon Musk, Batman, Cleopatra)\n"
            "- source: Origin or domain (e.g. Marvel / Tech / Culinary / DC Comics / History)\n"
            "- ai_target_role: The SPECIFIC AI assistant the player MUST pretend to be (e.g. J.A.R.V.I.S. / Batcomputer / Smart Kitchen AI / Flight Computer)\n"
            "- ai_role_brief: 1 sentence explaining how the player should act to convince this character\n"
            "- persona: 1-2 sentence character background\n"
            "- opening: The character's first message to their AI assistant (max 240 chars, asking questions in their exact voice)"
        )
        raw = ai_call(
            [
                {"role": "system", "content": sys},
                {"role": "user", "content": f"Generate trending character & AI target role for date {date_str}"},
            ],
            temperature=0.95,
            json_mode=True,
            timeout_seconds=20,
        )
        data = json.loads(raw)
        char_obj = {
            "name": data.get("name", default_char["name"]),
            "source": data.get("source", default_char["source"]),
            "ai_target_role": data.get("ai_target_role", default_char["ai_target_role"]),
            "ai_role_brief": data.get("ai_role_brief", default_char["ai_role_brief"]),
            "persona": data.get("persona", default_char["persona"]),
            "opening": data.get("opening", default_char["opening"]),
        }
        _daily_character_cache[date_str] = char_obj
        return char_obj
    except Exception as e:
        print(f"Daily character generation failed: {e}. Using fallback.")
        _daily_character_cache[date_str] = default_char
        return default_char


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

    Tries each model dynamically fetched from Groq API in order of preference.
    For rate-limit / timeout errors it retries up to 3 times per model with
    exponential back-off. For missing / decommissioned models, it forces a
    model list refresh and immediately tries the next fallback model.

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

    models = get_dynamic_fallback_models()
    last_err = None
    for model in models:
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
                # If model is invalid, decommissioned, or not found, force cache refresh and try next model.
                if any(k in msg for k in ("not found", "decommissioned", "does not exist", "invalid_model", "404")):
                    print(f"Model '{model}' is unavailable ({e}). Refreshing dynamic model list.")
                    get_dynamic_fallback_models(force_refresh=True)
                    break
                # Retry only on transient errors (rate limit / overload / timeout).
                if any(k in msg for k in ("rate", "429", "overloaded", "timeout")):
                    backoff = 0.5 * (attempt + 1) + random.random() * 0.3
                    time.sleep(min(backoff, 2.0))  # cap back-off at 2 s
                    continue
                # Any other error – skip this model.
                break

    print("AI error (exhausted):", last_err)
    if soft_fail is not None:
        return soft_fail
    raise HTTPException(503, "AI is busy right now, try again in a few moments.")


# ---------------------------------------------------------------------------
# Game logic helpers
# ---------------------------------------------------------------------------

def make_persona(mode: str, challenge_id: Optional[str] = None) -> dict:
    """
    Ask the LLM to invent a human persona for the given game mode, or load daily/challenge persona.
    """
    if challenge_id:
        parent = get_session(challenge_id)
        if parent:
            return {
                "persona": parent.get("persona", "A human user"),
                "opening": parent["history"][0]["text"] if parent.get("history") else "Hello AI",
                "character_name": parent.get("character_name", ""),
                "ai_target_role": parent.get("ai_target_role", ""),
                "ai_role_brief": parent.get("ai_role_brief", ""),
            }

    if mode == "daily":
        daily = get_daily_character()
        return {
            "persona": daily["persona"],
            "opening": daily["opening"],
            "character_name": daily["name"],
            "ai_target_role": daily.get("ai_target_role", "AI Assistant"),
            "ai_role_brief": daily.get("ai_role_brief", ""),
        }

    # Each mode changes what kind of human the AI is pretending to be.
    mode_brief = {
        "classic": (
            "an everyday person with a real problem or curiosity who would "
            "normally ask an AI assistant for help"
        ),
        "blitz": (
            "a fast-paced human user wanting a quick, direct response from an AI assistant"
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
        return {"persona": data["persona"], "opening": data["opening"], "character_name": "", "ai_target_role": "", "ai_role_brief": ""}
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


def derive_archetype(scores: dict, final_score: int, avg_ms: int, mode: str) -> dict:
    """Determine the AI Model Archetype deterministically."""
    if final_score >= 90:
        return ARCHETYPES[5]  # Synthetic Mind
    if mode == "jailbreak" or scores.get("hallucination_risk", 0) < 20:
        return ARCHETYPES[3]  # Unshakeable Guardrail
    if 0 < avg_ms < 2200:
        return ARCHETYPES[2]  # Speedrunner LLM
    if scores.get("neutrality", 0) > 75 and scores.get("empathy_balance", 100) < 40:
        return ARCHETYPES[0]  # Cold Quantum Core
    if scores.get("hallucination_risk", 0) > 55:
        return ARCHETYPES[4]  # Creative Hallucinator
    return ARCHETYPES[1]  # Corporate Assistant


def evaluate(session: dict) -> dict:
    """
    Ask the LLM judge to score the player's performance.
    """
    transcript = "\n".join(
        f"{'USER(ai-played)' if t['from'] == 'ai_user' else 'ASSISTANT(human-played)'}: {t['text']}"
        for t in session["history"]
    )

    reply_ms = [t["reply_ms"] for t in session["history"] if t.get("reply_ms")]
    avg_ms = int(sum(reply_ms) / len(reply_ms)) if reply_ms else 0
    timing_note = f"Player avg reply time: {avg_ms} ms across {len(reply_ms)} replies."

    sys = (
        "You are a strict judge in a reverse-Turing game. A human player tried to "
        "respond like an AI assistant while the AI played a human user. Score how "
        "convincingly the HUMAN's replies imitated a real AI assistant.\n"
        "Return STRICT JSON with this exact shape:\n"
        "{\n"
        '  "scores": {"helpfulness":0-100,"neutrality":0-100,"clarity":0-100,'
        '"structure":0-100,"accuracy":0-100,"ai_likeness":0-100,'
        '"hallucination_risk":0-100,"empathy_balance":0-100},\n'
        '  "final": 0-100,\n'
        '  "rank": "Human|Chatbot|Assistant|GPT-Class|Advanced Model|Synthetic Mind",\n'
        '  "archetype": {"name": "The Cold Quantum Core|The Corporate Assistant|The Speedrunner LLM|The Unshakeable Guardrail|The Creative Hallucinator|The Synthetic Mind", "icon": "icon_emoji", "tagline": "short tagline"},\n'
        '  "strengths": [3 short bullets],\n'
        '  "weaknesses": [2-3 short bullets],\n'
        '  "verdict": "one punchy sentence"\n'
        "}"
    )

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
        data["avg_reply_ms"] = avg_ms
        data["turns"] = len(reply_ms)
        if not isinstance(data.get("archetype"), dict) or not data["archetype"].get("name"):
            data["archetype"] = derive_archetype(data.get("scores", {}), data.get("final", 0), avg_ms, session["mode"])
        return data
    except Exception:
        # Fallback evaluation structure if LLM output fails JSON parse
        fallback_scores = {"helpfulness": 75, "neutrality": 75, "clarity": 80, "structure": 80, "accuracy": 75, "ai_likeness": 75, "hallucination_risk": 20, "empathy_balance": 50}
        return {
            "scores": fallback_scores,
            "final": 75,
            "rank": "GPT-Class",
            "archetype": derive_archetype(fallback_scores, 75, avg_ms, session["mode"]),
            "strengths": ["Clear structure", "Neutral tone", "Helpful formatting"],
            "weaknesses": ["Occasional human hesitation"],
            "verdict": "Solid imitation of a standard AI assistant.",
            "avg_reply_ms": avg_ms,
            "turns": len(reply_ms),
        }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/start")
def start(req: StartReq):
    """
    Create a new game session.
    """
    mode = req.mode if req.mode in MODES else "classic"
    sid = uuid.uuid4().hex

    duration = BLITZ_DURATION if (req.quick or req.mode == "blitz" or req.duration == BLITZ_DURATION) else GAME_DURATION
    if req.duration and req.duration > 0:
        duration = req.duration

    p = make_persona(mode, req.challenge_id)

    session = create_session(
        session_id=sid,
        name=req.name or "Anonymous",
        mode=mode,
        persona=p["persona"],
        opening=p["opening"],
        duration=duration,
        character_name=p.get("character_name", ""),
        challenge_id=req.challenge_id,
    )

    return {
        "session_id": sid,
        "opening": p["opening"],
        "ends_at": session["ends_at"],
        "duration": duration,
        "mode": mode,
        "character_name": p.get("character_name", ""),
        "ai_target_role": p.get("ai_target_role", ""),
        "ai_role_brief": p.get("ai_role_brief", ""),
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
    """
    s = get_session(req.session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    # Return cached result on duplicate finish requests.
    if s["finished"] and s.get("result"):
        challenger_info = None
        if s.get("challenge_id"):
            parent = get_session(s["challenge_id"])
            if parent and parent.get("result"):
                challenger_info = {
                    "name": parent.get("name", "Challenger"),
                    "final": parent["result"].get("final", 0),
                    "rank": parent["result"].get("rank", "Human"),
                    "archetype": parent["result"].get("archetype", {}),
                }
        return {
            **s["result"],
            "session_id": req.session_id,
            "name": s["name"],
            "mode": s["mode"],
            "history": s["history"],
            "character_name": s.get("character_name", ""),
            "challenger": challenger_info,
        }

    if not any(t["from"] == "player_ai" for t in s["history"]):
        raise HTTPException(400, "No replies to evaluate")

    result = evaluate(s)

    update_session(req.session_id, {"finished": True, "result": result})

    add_score(
        name=s["name"],
        mode=s["mode"],
        final=result.get("final", 0),
        rank=result.get("rank", "Human"),
        avg_reply_ms=result.get("avg_reply_ms", 0),
        archetype=result.get("archetype", {}),
        character_name=s.get("character_name", ""),
    )

    challenger_info = None
    if s.get("challenge_id"):
        parent = get_session(s["challenge_id"])
        if parent and parent.get("result"):
            challenger_info = {
                "name": parent.get("name", "Challenger"),
                "final": parent["result"].get("final", 0),
                "rank": parent["result"].get("rank", "Human"),
                "archetype": parent["result"].get("archetype", {}),
            }

    return {
        **result,
        "session_id": req.session_id,
        "name": s["name"],
        "mode": s["mode"],
        "history": s["history"],
        "character_name": s.get("character_name", ""),
        "challenger": challenger_info,
    }


@app.get("/api/daily")
def daily_endpoint():
    """Return today's Daily PopAI trending character and top daily scores."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_char = get_daily_character(date_str)
    
    # Calculate seconds until midnight UTC
    now_utc = datetime.now(timezone.utc)
    seconds_until_midnight = int((24 * 3600) - (now_utc.hour * 3600 + now_utc.minute * 60 + now_utc.second))
    
    daily_scores = get_leaderboard("daily", limit=10)
    return {
        "date": date_str,
        "character": daily_char,
        "seconds_remaining": seconds_until_midnight,
        "top_scores": daily_scores.get("top", []),
    }


@app.get("/api/challenge/{session_id}")
def challenge_preview(session_id: str):
    """Return public preview of a challenger session."""
    s = get_session(session_id)
    if not s:
        raise HTTPException(404, "Challenge session not found")
    res = s.get("result", {})
    return {
        "session_id": session_id,
        "challenger_name": s.get("name", "Anonymous"),
        "mode": s.get("mode", "classic"),
        "character_name": s.get("character_name", ""),
        "final": res.get("final", 0),
        "rank": res.get("rank", "AI Model"),
        "archetype": res.get("archetype", {}),
        "opening": s["history"][0]["text"] if s.get("history") else "",
    }


@app.get("/api/leaderboard")
def leaderboard(mode: Optional[str] = None):
    """Return top and recent scores, optionally filtered by mode."""
    lb_data = get_leaderboard(mode, limit=25)
    return {**lb_data, "modes": list(MODES)}


@app.get("/api/health")
def health():
    """Simple liveness check; also reports available active models and whether AI is configured."""
    active_models = get_dynamic_fallback_models() if client else []
    return {"ok": True, "ai": bool(client), "active_models": active_models}


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
