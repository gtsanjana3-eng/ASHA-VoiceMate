"""End-to-end API tests (server + agent + database), using typed transcripts."""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import database as db
from backend.main import app


@pytest.fixture()
def client(tmp_path):
    db.set_database_path(tmp_path / "api.db")
    with TestClient(app) as c:
        yield c


def say(client, sid, text):
    r = client.post(f"/api/sessions/{sid}/utterance", json={"text": text, "source": "typed"})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_never_exposes_key(client, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "GNANI_API_KEY", "secret-value-123")
    r = client.get("/api/status")
    assert "secret-value-123" not in r.text
    s = r.json()
    assert s["database"]["ready"] is True
    assert s["stt"]["ready"] is True and s["stt"]["model"] == "prisma-v3.0"
    assert s["tts"]["model"] == "timbre-v3.0"
    assert set(s) == {"database", "stt", "tts", "gnani_key_present"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ASHA VoiceMate" in r.text


def test_full_visit_flow_with_correction_and_save(client):
    sid = client.post("/api/sessions", json={"language": "en-IN"}).json()["session_id"]
    r = say(client, sid, "ID B205 newborn visit weight 2.5 kg BCG due next visit Monday")
    assert r["state"] == "awaiting_confirmation"
    assert r["record"]["beneficiary_name"] == "Baby of Lakshmi (demo)"     # filled from demo register
    r = say(client, sid, "No, weight is 2.8 kilo.")
    assert r["record"]["weight_kg"] == 2.8
    # saving before confirmation is refused
    assert client.post(f"/api/sessions/{sid}/save", json={"client_request_id": str(uuid.uuid4())}).status_code == 409
    r = say(client, sid, "haan")
    assert r["action"] == "save"
    rid = str(uuid.uuid4())
    s1 = client.post(f"/api/sessions/{sid}/save", json={"client_request_id": rid}).json()
    s2 = client.post(f"/api/sessions/{sid}/save", json={"client_request_id": rid}).json()
    assert s2["duplicate"] is True and s1["visit_id"] == s2["visit_id"]
    visits = client.get("/api/visits?search=B205").json()
    assert len(visits) == 1 and visits[0]["weight_kg"] == 2.8
    detail = client.get(f"/api/visits/{s1['visit_id']}").json()
    assert detail["correction_history"][0]["new"] == 2.8
    assert client.get("/api/followups").json()


def test_danger_visit_flags_urgent(client):
    sid = client.post("/api/sessions", json={"language": "kn-IN"}).json()["session_id"]
    r = say(client, sid, "ID B201 newborn visit weight 2.6 kg baby is not feeding next visit tomorrow")
    assert r["danger"]["urgent_referral"] is True
    assert "PHC" in r["alert_text"]
    r = client.post(f"/api/sessions/{sid}/confirm").json()
    assert r["action"] == "save"
    saved = client.post(f"/api/sessions/{sid}/save", json={"client_request_id": str(uuid.uuid4())}).json()
    assert saved["urgent_referral"] is True
    assert client.get("/api/followups").json()[0]["priority"] == "urgent"


def test_confirm_incomplete_is_refused(client):
    sid = client.post("/api/sessions", json={"language": "en-IN"}).json()["session_id"]
    say(client, sid, "ID B101")
    assert client.post(f"/api/sessions/{sid}/confirm").status_code == 409


def test_unknown_beneficiary_warning(client):
    sid = client.post("/api/sessions", json={"language": "en-IN"}).json()["session_id"]
    r = say(client, sid, "ID B999 newborn visit")
    assert any("B999" in w for w in r["warnings"])
    r = say(client, sid, "weight 2.8 kg next visit Monday")
    assert "B999 is not in the register" in r["speak_text"]          # spoken, not only shown
    r = say(client, sid, "no, ID is B205")
    assert r["warnings"] == [] and "not in the register" not in r["speak_text"]


def test_input_validation(client):
    assert client.post("/api/sessions", json={"language": "xx"}).status_code == 422
    sid = client.post("/api/sessions", json={"language": "en-IN"}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/utterance", json={"text": ""}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/utterance", json={"text": "x" * 2001}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/save", json={"client_request_id": "bad id!"}).status_code == 422
    assert client.post("/api/sessions/nope/utterance", json={"text": "hi"}).status_code == 404


def test_without_key_stt_tts_say_not_connected(client, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "GNANI_API_KEY", "")          # never call the real service in tests
    r = client.post("/api/stt", files={"audio": ("a.wav", b"1234", "audio/wav")}, data={"language": "en-IN"})
    assert r.status_code in (422, 501)                       # invalid WAV is caught before any call
    r = client.post("/api/tts", json={"text": "hello", "language": "en-IN"})
    assert r.status_code == 501
    s = client.get("/api/status").json()
    assert s["stt"]["ready"] is False and s["tts"]["ready"] is False


def test_language_switch_mid_visit(client):
    sid = client.post("/api/sessions", json={"language": "en-IN"}).json()["session_id"]
    say(client, sid, "ID B205 newborn visit weight 2.8 kg next visit Monday")
    r = client.post(f"/api/sessions/{sid}/language", json={"language": "hi-IN"}).json()
    assert r["language"] == "hi-IN" and "मैंने यह दर्ज किया है" in r["speak_text"]
