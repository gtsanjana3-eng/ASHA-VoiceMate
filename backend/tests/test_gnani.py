"""Tests for the Gnani clients WITHOUT calling the real service.

A fake transport checks that we send exactly what the official docs describe
(https://docs.gnani.ai) and that we read the documented response shapes.
These tests prove our side of the contract only; the real connection is
checked manually (see README "Test the real Gnani connection").
"""
import asyncio
import io
import json
import wave

import httpx
import pytest

from backend import config
from backend.services import gnani_client, gnani_stt, gnani_tts
from backend.services.gnani_client import GnaniError, GnaniNotConnected

FAKE_KEY = "test-key-not-real"


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setattr(config, "GNANI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(gnani_client.asyncio, "sleep", _no_sleep)
    gnani_client.health["stt"] = {"ok": None, "error": None}
    gnani_client.health["tts"] = {"ok": None, "error": None}


async def _no_sleep(_):
    return None


def make_wav(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- STT
def test_stt_request_matches_docs():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("X-API-Key-ID")
        seen["body"] = req.content
        return httpx.Response(200, json={"success": True, "request_id": "r1", "transcript": "ID B205 weight 2.8 kg",
                                         "model": "prisma-v3.0", "detected_language_code": "en-IN"})

    out = run(gnani_stt.transcribe(make_wav(), "audio/wav", "hi-IN", transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://api.vachana.ai/stt/v3"
    assert seen["key"] == FAKE_KEY
    body = seen["body"].decode("latin-1")
    assert 'name="audio_file"; filename="recording.wav"' in body
    assert 'name="model"\r\n\r\nprisma-v3.0' in body
    assert 'name="language_code"\r\n\r\nhi-IN,en-IN' in body
    assert 'name="format"\r\n\r\ntranscribe' in body
    assert out["text"] == "ID B205 weight 2.8 kg"
    assert out["detected_language"] == "en-IN"
    assert gnani_client.health["stt"]["ok"] is True


def test_stt_truncated_flag():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"success": True, "transcript": "abc", "truncated": True}))
    assert run(gnani_stt.transcribe(make_wav(), "audio/wav", "en-IN", transport=t))["truncated"] is True


def test_stt_rejects_long_or_invalid_audio_before_calling():
    called = []
    t = httpx.MockTransport(lambda r: called.append(1) or httpx.Response(200, json={}))
    with pytest.raises(GnaniError, match="30 seconds"):
        run(gnani_stt.transcribe(make_wav(31), "audio/wav", "en-IN", transport=t))
    with pytest.raises(GnaniError, match="valid WAV"):
        run(gnani_stt.transcribe(b"not audio", "audio/webm", "en-IN", transport=t))
    assert not called


@pytest.mark.parametrize("status,body,expect", [
    (401, {"detail": {"error_code": "INVALID_API_KEY", "message": "Unauthorized", "status_code": 401}}, "API key"),
    (402, {"detail": "x"}, "credit"),
    (403, {"detail": {"error_code": "SCOPE_NOT_ALLOWED", "message": "Service 'STT' not in allowed scopes"}}, "not allowed"),
    (400, {"success": False, "error": {"type": "AUDIO_CONVERSION_ERROR", "message": "Failed to convert"}}, "AUDIO_CONVERSION_ERROR"),
])
def test_stt_documented_errors(status, body, expect):
    t = httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    with pytest.raises(GnaniError, match=expect):
        run(gnani_stt.transcribe(make_wav(), "audio/wav", "en-IN", transport=t))
    assert gnani_client.health["stt"]["ok"] is False


def test_retry_once_on_rate_limit():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED", "message": "busy"}})
        return httpx.Response(200, json={"success": True, "transcript": "ok"})

    out = run(gnani_stt.transcribe(make_wav(), "audio/wav", "en-IN", transport=httpx.MockTransport(handler)))
    assert out["text"] == "ok" and len(calls) == 2


def test_network_failure_is_friendly():
    def handler(req):
        raise httpx.ConnectError("no network")
    with pytest.raises(GnaniError, match="internet"):
        run(gnani_stt.transcribe(make_wav(), "audio/wav", "en-IN", transport=httpx.MockTransport(handler)))


def test_no_key_means_not_connected(monkeypatch):
    monkeypatch.setattr(config, "GNANI_API_KEY", "replace-with-your-gnani-api-key")
    assert gnani_stt.is_ready() is False
    with pytest.raises(GnaniNotConnected):
        run(gnani_stt.transcribe(make_wav(), "audio/wav", "en-IN", transport=httpx.MockTransport(lambda r: httpx.Response(200))))


# ---------------------------------------------------------------- TTS
def test_tts_request_matches_docs():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("X-API-Key-ID")
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, content=b"ID3fake-mp3", headers={"Content-Type": "audio/mpeg"})

    audio, mt = run(gnani_tts.synthesize("खतरे का संकेत। तुरंत PHC रेफर करें।", "hi-IN", transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://api.vachana.ai/api/v1/tts/inference"
    assert seen["key"] == FAKE_KEY
    j = seen["json"]
    assert j["model"] == "timbre-v3.0" and j["voice"] == "Chetana" and j["language"] == "hi-IN"
    assert 0.85 <= j["speed"] <= 1.15
    assert j["audio_config"]["container"] == "mp3"
    assert j["audio_config"]["sample_rate"] in (8000, 16000, 22050, 24000, 44100, 48000)
    assert audio == b"ID3fake-mp3" and mt == "audio/mpeg"


def test_tts_flat_error():
    t = httpx.MockTransport(lambda r: httpx.Response(400, json={"success": False, "message": "Invalid request: voice", "status_code": 400}))
    with pytest.raises(GnaniError, match="Invalid request"):
        run(gnani_tts.synthesize("hello", "en-IN", transport=t))


def test_tts_non_audio_response_rejected():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": True}))
    with pytest.raises(GnaniError, match="unexpected"):
        run(gnani_tts.synthesize("hello", "en-IN", transport=t))


def test_readback_dates_are_spoken_form():
    from backend.services.language_service import build_readback
    assert "16 November 2026" in build_readback("en-IN", {"next_visit_date": "2026-11-16"})
    assert "16 नवंबर 2026" in build_readback("hi-IN", {"next_visit_date": "2026-11-16"})
