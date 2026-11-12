"""Gnani text-to-speech: Timbre v3.0 over REST.

Source: https://docs.gnani.ai/api/TTS/tts-inference.md and
        https://docs.gnani.ai/api/TTS/available-voices.md (read 2026-11-12)
  POST https://api.vachana.ai/api/v1/tts/inference   (application/json)
  header X-API-Key-ID
  body   text, model ("timbre-v3.0"), voice, language, speed (0.85-1.15),
         audio_config {sample_rate, container, bitrate, ...}
  reply  200 with raw audio bytes; container "mp3" -> Content-Type audio/mpeg

Voice: "Chetana" - a Timbre v3.0 voice described in the catalog as a
"gentle, empathetic voice for healthcare". Every Timbre v3.0 voice speaks all
10 supported languages, so one voice covers English, Hindi and Kannada.
Change it with GNANI_TTS_VOICE in .env (must be a Timbre v3.0 voice).
"""
from __future__ import annotations

import os

import httpx

from .gnani_client import GnaniError, GnaniNotConnected, gnani_key_present, health, post  # noqa: F401

MODEL = "timbre-v3.0"
VOICE = os.getenv("GNANI_TTS_VOICE", "Chetana")
TIMBRE_V3_VOICES = {"Avinash", "Shivani", "Lakshmi", "Kalpana", "Shubham", "Prakash", "Devansh",
                    "Yashraj", "Chetana", "Vasudha", "Riyaa", "Tarika", "Harshad"}
SPEED = 0.95   # slightly slower than normal for field use; documented range 0.85-1.15
AUDIO_CONFIG = {"sample_rate": 24000, "container": "mp3", "bitrate": "64k"}   # small files on weak networks
SUPPORTED = {"en-IN", "hi-IN", "kn-IN"}

PENDING_REASON = "Gnani API key not set in .env"


def is_ready() -> bool:
    return gnani_key_present()


async def synthesize(text: str, language: str, transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, str]:
    if VOICE not in TIMBRE_V3_VOICES:
        raise GnaniError(f"GNANI_TTS_VOICE '{VOICE}' is not a Timbre v3.0 voice.", 500)
    text = (text or "").strip()
    if not text:
        raise GnaniError("Nothing to speak.", 422)
    body = {
        "text": text,
        "model": MODEL,
        "voice": VOICE,
        "language": language if language in SUPPORTED else "auto",
        "speed": SPEED,
        "audio_config": AUDIO_CONFIG,
    }
    resp = await post("tts", "/api/v1/tts/inference", transport=transport, json=body)
    audio = resp.content
    if not audio:
        raise GnaniError("Gnani TTS returned no audio.", 502)
    media_type = resp.headers.get("content-type", "audio/mpeg").split(";")[0]
    if not media_type.startswith("audio/"):
        raise GnaniError("Gnani TTS returned an unexpected response instead of audio.", 502)
    return audio, media_type
