"""Database save / retrieval tests. Uses a temporary database file."""
import uuid
from datetime import date

import pytest

from backend import database as db
from backend.services.agent import VisitSession


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    db.set_database_path(tmp_path / "test.db")
    db.init_db()
    yield


def confirmed_session(utterances):
    s = VisitSession("en-IN", date(2026, 11, 12))
    for u in utterances:
        s.handle_utterance(u)
    r = s.handle_utterance("yes")
    assert r["action"] == "save"
    return s.snapshot()


def test_demo_beneficiaries_are_synthetic():
    rows = db.list_beneficiaries()
    assert len(rows) >= 5
    assert all(r["is_synthetic"] == 1 for r in rows)
    assert db.get_beneficiary("205")["beneficiary_id"] == "B205"


def test_save_and_retrieve():
    snap = confirmed_session(["ID B205 newborn visit weight 2.8 kg BCG due next visit Monday"])
    res = db.save_confirmed_visit(snap, str(uuid.uuid4()), confirmed=True)
    visit = db.get_visit(res["visit_id"])
    assert visit["beneficiary_id"] == "B205"
    assert visit["weight_kg"] == 2.8
    assert visit["vaccinations_due"] == ["BCG"]
    assert visit["record_status"] == "confirmed"
    assert visit["confirmed_at"]
    fu = db.list_followups()
    assert any(f["due_date"] == "2026-11-16" and "BCG" in f["reason"] for f in fu)
    assert db.list_visits(search="B205")[0]["id"] == res["visit_id"]
    assert db.list_visits(search="nobody") == []


def test_unconfirmed_is_rejected():
    s = VisitSession("en-IN", date(2026, 11, 12))
    s.handle_utterance("ID B205 newborn visit weight 2.8 kg next visit Monday")
    with pytest.raises(db.SaveError):
        db.save_confirmed_visit(s.snapshot(), str(uuid.uuid4()), confirmed=True)
    assert db.list_visits() == []


def test_duplicate_submission_saved_once():
    snap = confirmed_session(["ID B205 newborn visit weight 2.8 kg next visit Monday"])
    rid = str(uuid.uuid4())
    first = db.save_confirmed_visit(snap, rid, confirmed=True)
    second = db.save_confirmed_visit(snap, rid, confirmed=True)
    assert second["duplicate"] is True and second["visit_id"] == first["visit_id"]
    assert len(db.list_visits()) == 1


def test_urgent_referral_saved_with_alert_and_followup():
    snap = confirmed_session(["ID B201 newborn visit weight 2.6 kg baby is not feeding next visit tomorrow"])
    res = db.save_confirmed_visit(snap, str(uuid.uuid4()), confirmed=True)
    visit = db.get_visit(res["visit_id"])
    assert visit["urgent_referral"] is True
    assert visit["record_status"] == "urgent_referral"
    alert = visit["alerts"][0]
    assert alert["rule_id"] == "NEWBORN_NOT_FEEDING" and alert["detected_phrase"] == "not feeding"
    fu = db.list_followups()
    assert fu[0]["priority"] == "urgent"


def test_correction_history_saved():
    snap = confirmed_session(["ID B205 newborn visit weight 2.5 kg next visit Monday", "no, weight is 2.8 kilo"])
    res = db.save_confirmed_visit(snap, str(uuid.uuid4()), confirmed=True)
    visit = db.get_visit(res["visit_id"])
    assert visit["correction_history"][0]["old"] == 2.5
    assert visit["correction_history"][0]["new"] == 2.8


def test_complete_followup():
    snap = confirmed_session(["ID B205 newborn visit weight 2.8 kg next visit Monday"])
    db.save_confirmed_visit(snap, str(uuid.uuid4()), confirmed=True)
    fid = db.list_followups()[0]["id"]
    assert db.complete_followup(fid) is True
    assert db.complete_followup(fid) is False
    assert db.list_followups() == []
