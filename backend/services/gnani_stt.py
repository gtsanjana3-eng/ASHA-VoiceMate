"""Gnani speech-to-text: Prisma v3.0 over REST.

Source: https://docs.gnani.ai/api/STT/speech-to-text.md (read 2026-11-12)
  POST https://api.vachana.ai/stt/v3   (multipart/form-data)
  header  X-API-Key-ID
  fields  audio_file (WAV/MP3/OGG/FLAC/AAC/M4A, max 30 s), model=prisma-v3.0,
          language_code (one code, or comma-separated list of 1-4 codes as hints),
          format (verbatim | transcribe | codemix | transliterate),
          keyterms (prisma-v3.0, up to 200), topic (prisma-v3.0, up to 1600 chars)
  reply   {"success": true, "transcript": "...", "detected_language_code": "hi-IN", ...}
          "truncated": true only if the transcript was cut short.

Why REST and not the realtime WebSocket: the worker records one statement at a
time, which fits the documented REST limit of 30 seconds and is simpler and
more reliable on a weak field connection. Streaming is NOT implemented.

The browser converts its recording to 16 kHz mono WAV before upload, because
browsers record WebM, which is not in Gnani's list of supported formats.
"""
from __future__ import annotations

import io
import json
import os
import wave

import httpx

from .gnani_client import GnaniError, GnaniNotConnected, gnani_key_present, health, post  # noqa: F401

MODEL = "prisma-v3.0"
# `transcribe` writes numbers as digits (e.g. weight "2.8"), which the extractor needs.
STT_FORMAT = os.getenv("GNANI_STT_FORMAT", "transcribe")
MAX_SECONDS = 30.0
TOPIC = "ASHA health worker household visit note: pregnancy ANC checkup, newborn care, vaccination, weight, next visit date."
KEYTERMS = ["ANC", "PNC", "HBNC", "IFA", "TT injection", "PHC", "BCG", "OPV", "Pentavalent", "Rotavirus",
            "IPV", "PCV", "Measles", "Vitamin A", "beneficiary ID", "next visit", "kilo"]

# Our language -> the language_code hint we send. English is added as a second
# hint for Hindi and Kannada so code-mixed health terms ("IFA goli") are kept.
LANGUAGE_HINTS = {"en-IN": "en-IN", "hi-IN": "hi-IN,en-IN", "kn-IN": "kn-IN,en-IN"}

PENDING_REASON = "Gnani API key not set in .env"


def is_ready() -> bool:
    return gnani_key_present()


def wav_duration_seconds(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return None


async def transcribe(audio_bytes: bytes, content_type: str, language: str,
                     transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if not audio_bytes:
        raise GnaniError("No audio was received. Please record again.", 422)
    duration = wav_duration_seconds(audio_bytes)
    if duration is None:
        raise GnaniError("The recording is not a valid WAV file. Please record again.", 422)
    if duration > MAX_SECONDS:
        raise GnaniError("The recording is longer than 30 seconds. Please speak in shorter parts.", 413)
    if duration < 0.3:
        raise GnaniError("The recording is too short. Hold the button a little longer and speak.", 422)

    data = {
        "model": MODEL,
        "language_code": LANGUAGE_HINTS.get(language, language),
        "format": STT_FORMAT,
        "keyterms": json.dumps(KEYTERMS),
        "topic": TOPIC,
    }
    resp = await post("stt", "/stt/v3", transport=transport,
                      files={"audio_file": ("recording.wav", audio_bytes, "audio/wav")}, data=data)
    try:
        body = resp.json()
    except ValueError:
        raise GnaniError("Gnani STT returned an unreadable response.", 502)
    if not body.get("success", False):
        raise GnaniError("Gnani STT did not succeed. Please try again.", 502)
    transcript = body.get("transcript") or ""
    return {
        "text": transcript.strip(),
        "detected_language": body.get("detected_language_code"),
        "truncated": bool(body.get("truncated")),
        "request_id": body.get("request_id"),
        "model": body.get("model"),
        "duration_seconds": round(duration, 2),
    }
