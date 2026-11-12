"""ASHA VoiceMate web server.

Start it (from the ASHA-VoiceMate folder):
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload --port 8000
Then open http://localhost:8000
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import database as db
from .config import FRONTEND_DIR, gnani_key_present
from .models import LanguageRequest, SaveRequest, StartSessionRequest, TTSRequest, UtteranceRequest
from .services import gnani_stt, gnani_tts
from .services import language_service as L
from .services.agent import STATE_CONFIRMED, VisitSession
from .services.danger_signs import rules_table
from .services.gnani_client import GnaniError, GnaniNotConnected, health as gnani_health

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SESSIONS = 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="ASHA VoiceMate", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# In-memory visit sessions (drafts). Drafts are NEVER written to the database.
_sessions: dict[str, VisitSession] = {}
_saved: dict[str, int] = {}          # session_id -> visit_id
_lock = threading.Lock()


def _get(session_id: str) -> VisitSession:
    s = _sessions.get(session_id)
    if not s:
        raise HTTPException(404, "Visit session not found (the server may have restarted). Restore your draft or start a new visit.")
    return s


def _out(s: VisitSession, resp: dict) -> dict:
    resp["saved_visit_id"] = _saved.get(s.session_id)
    return resp


# ---------------------------------------------------------------------------
# Pages and status
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


def _service_status(module, name: str) -> dict:
    ready = module.is_ready()
    h = gnani_health[name]
    return {
        "ready": ready,                       # key configured
        "last_call_ok": h["ok"],              # None = not called yet since server start
        "last_error": h["error"],
        "reason": None if ready else module.PENDING_REASON,
        "model": module.MODEL,
    }


@app.get("/api/status")
def status():
    return {
        "database": {"ready": db.health_check()},
        "stt": _service_status(gnani_stt, "stt"),
        "tts": _service_status(gnani_tts, "tts") | {"voice": gnani_tts.VOICE},
        "gnani_key_present": gnani_key_present(),   # True/False only - the key itself is never sent
    }


@app.get("/api/languages")
def languages():
    return [
        info | {"labels": L.MESSAGES[info["code"]]["labels"], "values": L.MESSAGES[info["code"]]["values"],
                "start": L.MESSAGES[info["code"]]["start"]}
        for info in L.list_languages()
    ]


@app.get("/api/rules")
def rules():
    return rules_table()


# ---------------------------------------------------------------------------
# Visit sessions
# ---------------------------------------------------------------------------
@app.post("/api/sessions")
def start_session(body: StartSessionRequest):
    if body.language not in L.LANGUAGES:
        raise HTTPException(422, "Unsupported language.")
    s = VisitSession(body.language, beneficiary_lookup=db.get_beneficiary)
    with _lock:
        if len(_sessions) >= MAX_SESSIONS:
            oldest = next(iter(_sessions))
            _sessions.pop(oldest, None)
            _saved.pop(oldest, None)
        _sessions[s.session_id] = s
    return _out(s, s.response(speak=[L.msg(s.language, "start")]))


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    s = _get(session_id)
    return _out(s, s.snapshot())


@app.post("/api/sessions/{session_id}/utterance")
def utterance(session_id: str, body: UtteranceRequest):
    s = _get(session_id)
    with _lock:
        try:
            resp = s.handle_utterance(body.text)
        except ValueError as e:
            raise HTTPException(409, str(e))
        if s.transcripts:
            s.transcripts[-1]["source"] = body.source
            resp["transcripts"] = list(s.transcripts)
    return _out(s, resp)


@app.post("/api/sessions/{session_id}/confirm")
def confirm(session_id: str):
    s = _get(session_id)
    with _lock:
        try:
            return _out(s, s.confirm())
        except ValueError as e:
            raise HTTPException(409, str(e))


@app.post("/api/sessions/{session_id}/cancel")
def cancel(session_id: str):
    s = _get(session_id)
    with _lock:
        try:
            return _out(s, s.cancel())
        except ValueError as e:
            raise HTTPException(409, str(e))


@app.post("/api/sessions/{session_id}/language")
def change_language(session_id: str, body: LanguageRequest):
    if body.language not in L.LANGUAGES:
        raise HTTPException(422, "Unsupported language.")
    s = _get(session_id)
    with _lock:
        return _out(s, s.set_language(body.language))


@app.post("/api/sessions/{session_id}/save")
def save(session_id: str, body: SaveRequest):
    s = _get(session_id)
    if s.state != STATE_CONFIRMED:
        raise HTTPException(409, "The worker has not confirmed this record yet. Nothing was saved.")
    with _lock:
        try:
            result = db.save_confirmed_visit(s.snapshot(), body.client_request_id, confirmed=True)
        except db.SaveError as e:
            raise HTTPException(409, str(e))
        _saved[s.session_id] = result["visit_id"]
    return {**result, "speak_text": L.msg(s.language, "saved"), "urgent_referral": s.danger.urgent_referral}


# ---------------------------------------------------------------------------
# Gnani speech (Prisma v3.0 STT, Timbre v3.0 TTS) - see services/gnani_*.py
# ---------------------------------------------------------------------------
@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), language: str = Form("en-IN")):
    if language not in L.LANGUAGES:
        raise HTTPException(422, "Unsupported language.")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long. Please keep it under 30 seconds.")
    if not data:
        raise HTTPException(422, "No audio was received. Please record again.")
    try:
        # Audio is processed in memory only and never written to disk.
        return await gnani_stt.transcribe(data, audio.content_type or "", language)
    except GnaniNotConnected as e:
        raise HTTPException(501, str(e))
    except GnaniError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/tts")
async def tts(body: TTSRequest):
    if body.language not in L.LANGUAGES:
        raise HTTPException(422, "Unsupported language.")
    try:
        audio, media_type = await gnani_tts.synthesize(body.text, body.language)
    except GnaniNotConnected as e:
        raise HTTPException(501, str(e))
    except GnaniError as e:
        raise HTTPException(e.status, str(e))
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Saved records
# ---------------------------------------------------------------------------
@app.get("/api/visits")
def visits(search: str | None = Query(default=None, max_length=100), limit: int = Query(default=50, ge=1, le=200)):
    return db.list_visits(search, limit)


@app.get("/api/visits/{visit_id}")
def visit(visit_id: int):
    v = db.get_visit(visit_id)
    if not v:
        raise HTTPException(404, "Visit not found.")
    return v


@app.get("/api/followups")
def followups(status: str = Query(default="open", pattern="^(open|done)$")):
    return db.list_followups(status)


@app.post("/api/followups/{followup_id}/complete")
def complete_followup(followup_id: int):
    if not db.complete_followup(followup_id):
        raise HTTPException(404, "Follow-up not found or already done.")
    return {"ok": True}


@app.get("/api/beneficiaries")
def beneficiaries():
    return db.list_beneficiaries()
