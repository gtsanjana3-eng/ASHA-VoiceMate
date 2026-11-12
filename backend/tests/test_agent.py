"""Extraction, correction and confirmation tests (synthetic transcripts only)."""
from datetime import date

import pytest

from backend.services.agent import (
    STATE_AWAITING, STATE_CANCELLED, STATE_COLLECTING, STATE_CONFIRMED, VisitSession, classify_reply,
    extract_fields, parse_date, words_to_numbers,
)

REF = date(2026, 11, 12)   # a Thursday


def test_english_anc_visit():
    f, unclear = extract_fields(
        "Beneficiary ID B101, ANC visit. Name Sunita Devi. ANC checkup done, IFA tablets given 30 tablets, "
        "TT injection due. Next visit on Monday.", REF)
    assert f["beneficiary_id"] == "B101"
    assert f["beneficiary_name"] == "Sunita Devi"
    assert f["visit_type"] == "ANC"
    assert f["anc_status"] == "done"
    assert f["ifa_status"] == "given"
    assert f["ifa_tablets"] == 30
    assert f["tt_status"] == "due"
    assert f["next_visit_date"] == "2026-11-16"
    assert not unclear


def test_newborn_visit_spoken_numbers():
    f, _ = extract_fields("ID B 205 newborn visit weight two point eight kilo, BCG and OPV due, next visit after 7 days", REF)
    assert f["beneficiary_id"] == "B205"
    assert f["visit_type"] == "HBNC"
    assert f["weight_kg"] == 2.8
    assert f["vaccinations_due"] == ["BCG", "OPV"]
    assert f["next_visit_date"] == "2026-11-19"


def test_hindi_code_mixed():
    f, _ = extract_fields("आईडी B101 गर्भवती महिला, ANC जांच हो गई, IFA गोली ले रही है, TT इंजेक्शन लग गया, अगली विज़िट सोमवार को", REF)
    assert f == {"beneficiary_id": "B101", "visit_type": "ANC", "anc_status": "done", "ifa_status": "taking",
                 "tt_status": "given", "next_visit_date": "2026-11-16"}


def test_hinglish_romanised():
    f, _ = extract_fields("ID B102, pregnant hai, IFA goli nahi le rahi, TT lag gaya, ANC baki hai, agli visit kal", REF)
    assert f["ifa_status"] == "not_taking"
    assert f["tt_status"] == "given"
    assert f["anc_status"] == "pending"
    assert f["next_visit_date"] == "2026-11-13"


def test_kannada_code_mixed():
    f, _ = extract_fields("ಐಡಿ B303 ಗರ್ಭಿಣಿ, ANC ತಪಾಸಣೆ ಆಗಿದೆ, IFA ಮಾತ್ರೆ ಕೊಡಲಾಗಿದೆ, TT ಲಸಿಕೆ ಬಾಕಿ, ಮುಂದಿನ ಭೇಟಿ ನಾಳೆ", REF)
    assert f["tt_status"] == "due"
    assert f["ifa_status"] == "given"
    assert f["next_visit_date"] == "2026-11-13"


def test_unclear_fields_are_not_guessed():
    f, unclear = extract_fields("weight is something, next visit sometime soon", REF)
    assert "weight_kg" not in f and "weight_kg" in unclear
    assert "next_visit_date" not in f and "next_visit_date" in unclear


def test_implausible_weight_is_unclear():
    f, unclear = extract_fields("weight 280 kg", REF)
    assert "weight_kg" not in f and "weight_kg" in unclear


@pytest.mark.parametrize("text,expected", [
    ("15 November", "2026-11-15"), ("november 20", "2026-11-20"), ("2026-12-01", "2026-12-01"),
    ("20/11", "2026-11-20"), ("5 January", "2027-01-05"), ("tomorrow", "2026-11-13"),
    ("next week", "2026-11-19"), ("सोमवार", "2026-11-16"), ("thursday", "2026-11-19"), ("3 din baad", "2026-11-15"),
])
def test_parse_date(text, expected):
    assert parse_date(text, REF) == expected


def test_words_to_numbers():
    assert words_to_numbers("two point eight kilo") == "2.8 kilo"
    assert words_to_numbers("fifty two kg") == "52 kg"


@pytest.mark.parametrize("text,expected", [
    ("yes", "yes"), ("haan sahi hai", "yes"), ("ಹೌದು", "yes"), ("हाँ", "yes"),
    ("no", "no"), ("galat hai", "no"), ("cancel", "cancel"), ("theek nahi hai", "unclear"), ("hmm", "unclear"),
])
def test_classify_reply(text, expected):
    assert classify_reply(text) == expected


# --- full session flow ------------------------------------------------------
def _ready_session():
    s = VisitSession("en-IN", REF)
    r = s.handle_utterance("Beneficiary ID B205, newborn visit, weight 2.5 kg, BCG and OPV due")
    assert r["state"] == STATE_COLLECTING
    assert r["missing_fields"] == ["next_visit_date"]
    r = s.handle_utterance("next visit on 20 November")
    assert r["state"] == STATE_AWAITING
    assert "Is this correct" in r["speak_text"]
    return s


def test_voice_corrections_and_history():
    s = _ready_session()
    r = s.handle_utterance("No, weight is 2.8 kilo.")
    assert r["record"]["weight_kg"] == 2.8
    assert r["state"] == STATE_AWAITING
    assert "2.8" in r["speak_text"]                       # read back again
    r = s.handle_utterance("Change the next visit date to Monday.")
    assert r["record"]["next_visit_date"] == "2026-11-16"
    r = s.handle_utterance("Vaccination is completed.")
    assert r["record"]["vaccination_status"] == "completed"
    assert r["record"]["vaccinations_due"] == []
    fields = [c["field"] for c in r["corrections"]]
    assert "weight_kg" in fields and "next_visit_date" in fields and "vaccinations_due" in fields
    weight_change = next(c for c in r["corrections"] if c["field"] == "weight_kg")
    assert weight_change["old"] == 2.5 and weight_change["new"] == 2.8


def test_confirmation_required_before_save():
    s = _ready_session()
    r = s.handle_utterance("hmm")
    assert r["state"] == STATE_AWAITING and r["action"] is None
    r = s.handle_utterance("no")
    assert r["state"] == STATE_AWAITING and r["action"] is None
    r = s.handle_utterance("yes")
    assert r["state"] == STATE_CONFIRMED and r["action"] == "save"
    with pytest.raises(ValueError):
        s.handle_utterance("yes")


def test_yes_with_correction_is_not_a_save():
    s = _ready_session()
    r = s.handle_utterance("yes, but weight is 3 kg")
    assert r["state"] == STATE_AWAITING
    assert r["action"] is None
    assert r["record"]["weight_kg"] == 3.0


def test_cancel():
    s = _ready_session()
    r = s.handle_utterance("cancel")
    assert r["state"] == STATE_CANCELLED


def test_danger_alert_spoken_first_and_flagged():
    s = VisitSession("hi-IN", REF)
    r = s.handle_utterance("ID B101 garbhvati, khoon aa raha hai")
    assert r["danger"]["urgent_referral"] is True
    assert "PHC" in r["alert_text"] and "तुरंत" in r["alert_text"]
    m = r["danger"]["matches"][0]
    assert m["phrase"] == "khoon" and m["reason"]


def test_danger_reply_during_confirmation_is_not_a_save():
    s = _ready_session()
    r = s.handle_utterance("yes the baby has fever")
    assert r["action"] is None
    assert r["danger"]["urgent_referral"] is True


def test_clarify_sign_read_back():
    s = VisitSession("en-IN", REF)
    s.handle_utterance("ID B101 ANC visit, ANC done, IFA given, TT given, next visit Monday")
    r = s.handle_utterance("maybe some bleeding")
    assert r["danger"]["level"] == "clarify"
    assert "Possible danger sign" in r["speak_text"]
