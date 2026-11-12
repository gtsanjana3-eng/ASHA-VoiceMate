"""Danger-sign tests. Run with:  python -m pytest -v"""
import pytest

from backend.services.danger_signs import (
    LEVEL_CLARIFY, LEVEL_DANGER, LEVEL_NEGATED, LEVEL_NONE, RULES, SOURCES, detect_danger_signs,
    merge_assessments,
)


def rules_at(text, level, visit_type=None):
    a = detect_danger_signs(text, visit_type)
    return {m.rule_id for m in a.matches if m.level == level}


# --- clear danger signs (must alert) --------------------------------------
@pytest.mark.parametrize("text,visit_type,rule", [
    ("The pregnant woman has bleeding since morning", None, "BLEEDING"),
    ("garbhvati mahila ko khoon aa raha hai", "ANC", "BLEEDING"),
    ("गर्भवती महिला को खून आ रहा है", None, "BLEEDING"),
    ("ಗರ್ಭಿಣಿಗೆ ರಕ್ತಸ್ರಾವ ಆಗುತ್ತಿದೆ", None, "BLEEDING"),
    ("khoon nahi ruk raha", "PNC", "BLEEDING"),
    ("She had fits last night", "ANC", "CONVULSIONS"),
    ("baby ko jhatke aa rahe hain", "HBNC", "CONVULSIONS"),
    ("severe headache and blurred vision", "ANC", "HEADACHE_BLURRED_VISION"),
    ("she has high fever", "ANC", "HIGH_FEVER_MOTHER"),
    ("newborn has fever", None, "NEWBORN_FEVER"),
    ("ಮಗುವಿಗೆ ಜ್ವರ ಇದೆ", None, "NEWBORN_FEVER"),
    ("baby temperature 38.2 degree", None, "NEWBORN_FEVER"),
    ("baby temperature 101 F", None, "NEWBORN_FEVER"),
    ("baby temperature 35 degree", None, "NEWBORN_LOW_TEMPERATURE"),
    ("baby is not feeding", None, "NEWBORN_NOT_FEEDING"),
    ("बच्चा दूध नहीं पी रहा", None, "NEWBORN_NOT_FEEDING"),
    ("baby breathing 65 per minute", None, "BREATHING_DIFFICULTY"),
    ("baby has chest indrawing", None, "BREATHING_DIFFICULTY"),
    ("the baby is lethargic", "HBNC", "NEWBORN_NO_MOVEMENT"),
    ("severe abdominal pain in pregnancy", None, "SEVERE_ABDOMINAL_PAIN"),
    ("pregnant woman has swelling of face", None, "SWELLING_FACE_HANDS"),
    ("pregnant, fetal movement reduced", None, "REDUCED_FETAL_MOVEMENT"),
    ("pregnant woman water is leaking", None, "LEAKING_FLUID"),
    ("after delivery foul smelling discharge", "PNC", "FOUL_DISCHARGE"),
])
def test_danger_detected(text, visit_type, rule):
    a = detect_danger_signs(text, visit_type)
    assert a.level == LEVEL_DANGER
    assert a.urgent_referral is True
    assert rule in rules_at(text, LEVEL_DANGER, visit_type)
    m = next(m for m in a.matches if m.rule_id == rule)
    assert m.phrase and m.reason and m.sources        # phrase + reason preserved


# --- uncertain speech must NOT be "none" ---------------------------------
@pytest.mark.parametrize("text,visit_type", [
    ("maybe there is bleeding", "ANC"),
    ("shayad khoon aa raha hai", "ANC"),
    ("she has fever", None),                     # whose fever? unknown -> clarify
    ("she has headache", "ANC"),                 # severity unclear
    ("pet dard hai", "ANC"),
    ("water is leaking", None),                  # pregnancy context missing
])
def test_uncertain_requires_clarification(text, visit_type):
    a = detect_danger_signs(text, visit_type)
    assert a.level == LEVEL_CLARIFY
    assert a.needs_human_review is True
    assert a.level != LEVEL_NONE


# --- explicitly absent signs are recorded, not dropped -------------------
@pytest.mark.parametrize("text,visit_type,rule", [
    ("no bleeding", "ANC", "BLEEDING"),
    ("bleeding nahi hai", "ANC", "BLEEDING"),
    ("ಜ್ವರ ಇಲ್ಲ", "HBNC", "NEWBORN_FEVER"),
])
def test_negated_is_recorded(text, visit_type, rule):
    a = detect_danger_signs(text, visit_type)
    assert rule in {m.rule_id for m in a.by_level(LEVEL_NEGATED)}
    assert a.urgent_referral is False


def test_no_bleeding_but_fever_in_newborn_still_alerts():
    a = detect_danger_signs("no bleeding, but baby has fever")
    assert a.level == LEVEL_DANGER
    assert "NEWBORN_FEVER" in {m.rule_id for m in a.by_level(LEVEL_DANGER)}


@pytest.mark.parametrize("text", [
    "khoon ki kami hai, IFA goli di",          # anaemia talk is not bleeding
    "ANC checkup done, IFA given, TT due",
    "ghar ka daura kiya",                        # 'daura' = visit, not fits
    "weight 2.8 kg, BCG due",
])
def test_routine_text_not_flagged(text):
    a = detect_danger_signs(text)
    assert a.level == LEVEL_NONE


def test_none_is_not_called_safe():
    a = detect_danger_signs("ANC done")
    assert "NOT a safety clearance" in a.to_dict()["status_text"]


def test_merge_never_downgrades():
    first = detect_danger_signs("pregnant woman bleeding")
    second = detect_danger_signs("no bleeding", "ANC")
    merged = merge_assessments(first, second)
    assert merged.level == LEVEL_DANGER


def test_clarify_upgraded_by_later_clear_statement():
    first = detect_danger_signs("maybe bleeding", "ANC")
    second = detect_danger_signs("yes there is bleeding", "ANC")
    merged = merge_assessments(first, second)
    assert merged.level == LEVEL_DANGER
    assert not merged.by_level(LEVEL_CLARIFY)


def test_every_rule_has_documented_source():
    for r in RULES:
        assert r.sources, r.rule_id
        for s in r.sources:
            assert s in SOURCES
        assert r.reason
