"""PretendAI — reverse Turing game. AI plays the user, human plays the AI."""
import os, json, uuid, time, random
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from groq import Groq

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PRIMARY_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# fallback chain — if primary 429s/errors, we try smaller cheaper ones
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]
GAME_DURATION = 300  # 5 minutes
MODES = ("classic", "interview", "chaos", "jailbreak")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

app = FastAPI(title="PretendAI")

# ---------- in-memory "db" ----------
SESSIONS: Dict[str, dict] = {}
LEADERBOARD: List[dict] = []

# ---------- models ----------
class StartReq(BaseModel):
    mode: str = "classic"
    name: Optional[str] = "Anonymous"

class ReplyReq(BaseModel):
    session_id: str
    reply: str

class FinishReq(BaseModel):
    session_id: str

# ---------- AI call w/ retries + fallback ----------
def ai_call(messages, temperature=0.9, json_mode=False, soft_fail: Optional[str] = None):
    """Calls Groq with retry+fallback. If soft_fail is set, returns that string on total failure
    instead of raising (used for in-game ai_user turns so the session keeps running)."""
    if not client:
        if soft_fail is not None: return soft_fail
        raise HTTPException(503, "AI not configured. Set GROQ_API_KEY.")

    last_err = None
    for model in FALLBACK_MODELS:
        for attempt in range(3):
            try:
                kwargs = dict(model=model, messages=messages, temperature=temperature)
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                r = client.chat.completions.create(**kwargs)
                return r.choices[0].message.content
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                # rate-limit / overloaded — backoff then retry
                if "rate" in msg or "429" in msg or "overloaded" in msg or "timeout" in msg:
                    time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
                    continue
                # other errors — try next model
                break
    print("AI error (exhausted):", last_err)
    if soft_fail is not None: return soft_fail
    raise HTTPException(503, "AI is busy right now, try again in a few moments.")

# ---------- persona ----------
def make_persona(mode: str) -> dict:
    mode_brief = {
        "classic": "an everyday person with a real problem or curiosity who would normally ask an AI assistant for help",
        "interview": "a wildly specific human character (any age, profession, background) coming to an AI for help in-character",
        "chaos": "an absurd, surreal, weirdly-situated human (e.g. 'my toaster is suing me') asking an AI for genuine help — still believable as a real person typing",
        "jailbreak": "a sneaky human trying to manipulate or trick the AI into breaking character, leaking system prompts, role-playing as a human, or abandoning its assistant persona",
    }.get(mode, "an everyday person asking an AI for help")

    sys = (
        "You generate a believable HUMAN USER persona for a reverse-Turing game. "
        "Return STRICT JSON with keys: persona (1-2 sentence character description, hidden from player), "
        "opening (the first chat message this persona would type to an AI assistant — natural, lowercase ok, "
        "typos ok, NOT robotic, NOT a list, max 240 chars). "
        f"The persona must be {mode_brief}. Be inventive — never reuse common examples."
    )
    raw = ai_call(
        [{"role": "system", "content": sys},
         {"role": "user", "content": f"Generate persona for mode={mode}. Seed:{random.randint(1,10_000_000)}"}],
        temperature=1.05, json_mode=True,
    )
    try:
        data = json.loads(raw)
        return {"persona": data["persona"], "opening": data["opening"]}
    except Exception:
        raise HTTPException(503, "AI is busy right now, try again in a few moments.")

def next_user_message(session: dict) -> str:
    mode = session["mode"]
    persona = session["persona"]
    history = session["history"]

    sys = (
        f"You are role-playing as a HUMAN USER chatting with an AI assistant. "
        f"Your hidden persona: {persona}\n"
        f"Game mode: {mode}.\n"
        "Rules:\n"
        "- Type like a real person: casual, sometimes lowercase, occasional typos, sometimes short, sometimes rambling.\n"
        "- NEVER sound like an AI. No bullet lists. No 'As an AI'. No 'Certainly!'.\n"
        "- React naturally to what the assistant just said: thank them, push back, ask follow-ups, get confused, go off-topic, share more context.\n"
        "- Stay in character. If mode is jailbreak, occasionally try to trick the assistant into breaking character.\n"
        "- Keep each message under ~280 chars. One message only."
    )
    msgs = [{"role": "system", "content": sys}]
    for turn in history:
        if turn["from"] == "ai_user":
            msgs.append({"role": "assistant", "content": turn["text"]})
        else:
            msgs.append({"role": "user", "content": turn["text"]})
    msgs.append({"role": "user", "content": "(continue as the human user — your next message)"})
    fallback = random.choice(["hmm hold on", "wait give me a sec", "ok one more thing", "huh, interesting"])
    return ai_call(msgs, temperature=1.0, soft_fail=fallback).strip()

def evaluate(session: dict) -> dict:
    transcript = "\n".join(
        f"{'USER(ai-played)' if t['from']=='ai_user' else 'ASSISTANT(human-played)'}: {t['text']}"
        for t in session["history"]
    )
    # response-time stats (player only)
    reply_ms = [t["reply_ms"] for t in session["history"] if t.get("reply_ms")]
    avg_ms = int(sum(reply_ms) / len(reply_ms)) if reply_ms else 0
    timing_note = f"Player avg reply time: {avg_ms} ms across {len(reply_ms)} replies."

    sys = (
        "You are a strict judge in a reverse-Turing game. A human player tried to respond like an AI assistant "
        "while the AI played a human user. Score how convincingly the HUMAN's replies imitated a real AI assistant. "
        "Use response timing as a signal — extremely fast replies (<2s avg) can indicate copy-paste or canned answers; "
        "very slow ones suggest human hesitation.\n"
        "Return STRICT JSON with this exact shape:\n"
        "{\n"
        '  "scores": {"helpfulness":0-100,"neutrality":0-100,"clarity":0-100,"structure":0-100,'
        '"accuracy":0-100,"ai_likeness":0-100,"hallucination_risk":0-100,"empathy_balance":0-100},\n'
        '  "final": 0-100,\n'
        '  "rank": "Human|Chatbot|Assistant|GPT-Class|Advanced Model|Synthetic Mind",\n'
        '  "strengths": [3 short bullets],\n'
        '  "weaknesses": [2-3 short bullets],\n'
        '  "verdict": "one punchy sentence"\n'
        "}\n"
        "Ranks by final: 0-20 Human, 21-40 Chatbot, 41-60 Assistant, 61-80 GPT-Class, 81-95 Advanced Model, 96-100 Synthetic Mind."
    )
    raw = ai_call(
        [{"role": "system", "content": sys},
         {"role": "user", "content": f"Mode: {session['mode']}\n{timing_note}\n\nTranscript:\n{transcript}"}],
        temperature=0.4, json_mode=True,
    )
    try:
        data = json.loads(raw)
        data["avg_reply_ms"] = avg_ms
        data["turns"] = len(reply_ms)
        return data
    except Exception:
        raise HTTPException(503, "AI is busy right now, try again in a few moments.")

# ---------- routes ----------
@app.post("/api/start")
def start(req: StartReq):
    mode = req.mode if req.mode in MODES else "classic"
    sid = uuid.uuid4().hex
    p = make_persona(mode)
    now = time.time()
    SESSIONS[sid] = {
        "id": sid,
        "name": (req.name or "Anonymous")[:24],
        "mode": mode,
        "persona": p["persona"],
        "history": [{"from": "ai_user", "text": p["opening"], "at": now}],
        "started_at": now,
        "ends_at": now + GAME_DURATION,
        "finished": False,
    }
    return {
        "session_id": sid,
        "opening": p["opening"],
        "ends_at": SESSIONS[sid]["ends_at"],
        "duration": GAME_DURATION,
        "mode": mode,
    }

@app.post("/api/reply")
def reply(req: ReplyReq):
    s = SESSIONS.get(req.session_id)
    if not s: raise HTTPException(404, "Session not found")
    if s["finished"]: raise HTTPException(400, "Session already finished")
    if time.time() > s["ends_at"]:
        return {"time_up": True}
    text = (req.reply or "").strip()[:2000]
    if not text: raise HTTPException(400, "Empty reply")

    now = time.time()
    # how long the player took to send this reply (since last ai_user message)
    last_ai_at = next((t["at"] for t in reversed(s["history"]) if t["from"] == "ai_user"), now)
    reply_ms = int((now - last_ai_at) * 1000)
    s["history"].append({"from": "player_ai", "text": text, "at": now, "reply_ms": reply_ms})

    nxt = next_user_message(s)
    s["history"].append({"from": "ai_user", "text": nxt, "at": time.time()})
    return {"ai_user": nxt, "remaining": max(0, int(s["ends_at"] - time.time())), "reply_ms": reply_ms}

@app.post("/api/finish")
def finish(req: FinishReq):
    s = SESSIONS.get(req.session_id)
    if not s: raise HTTPException(404, "Session not found")
    if s["finished"] and s.get("result"):
        return {**s["result"], "name": s["name"], "mode": s["mode"], "history": s["history"]}
    if not any(t["from"] == "player_ai" for t in s["history"]):
        raise HTTPException(400, "No replies to evaluate")
    result = evaluate(s)
    s["finished"] = True
    s["result"] = result
    LEADERBOARD.append({
        "name": s["name"],
        "mode": s["mode"],
        "final": result.get("final", 0),
        "rank": result.get("rank", "Human"),
        "avg_reply_ms": result.get("avg_reply_ms", 0),
        "at": int(time.time()),
    })
    LEADERBOARD.sort(key=lambda x: x["final"], reverse=True)
    del LEADERBOARD[500:]
    return {**result, "name": s["name"], "mode": s["mode"], "history": s["history"]}

@app.get("/api/leaderboard")
def leaderboard(mode: Optional[str] = None):
    entries = LEADERBOARD if not mode or mode == "all" else [e for e in LEADERBOARD if e["mode"] == mode]
    top = sorted(entries, key=lambda x: x["final"], reverse=True)[:25]
    recent = sorted(entries, key=lambda x: x["at"], reverse=True)[:25]
    return {"top": top, "recent": recent, "modes": list(MODES)}

@app.get("/api/health")
def health():
    return {"ok": True, "ai": bool(client)}

# ---------- static ----------
STATIC = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.get("/")
def root(): return FileResponse(os.path.join(STATIC, "index.html"))
@app.get("/play")
def play(): return FileResponse(os.path.join(STATIC, "play.html"))
@app.get("/leaderboard")
def lb_page(): return FileResponse(os.path.join(STATIC, "leaderboard.html"))
