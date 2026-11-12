"""All language-specific text lives here, separate from the business logic.

LANGUAGE SUPPORT (verified 2026-11-12 from official Gnani docs)
    STT  https://docs.gnani.ai/api/STT/languages.md      - en-IN, hi-IN, kn-IN listed
    TTS  https://docs.gnani.ai/api/TTS/tts-inference.md  - en-IN, hi-IN, kn-IN listed
    Gnani supports 10 Indian languages in total; this app ships messages and
    danger-sign phrases for these 3 only. Add a language here (with its
    messages) before offering it in the UI.

Hindi and Kannada text below was written by the developer and SHOULD be
reviewed by a native speaker before a real demo.
"""
from __future__ import annotations

DEFAULT_LANGUAGE = "en-IN"

LANGUAGES: dict[str, dict] = {
    "en-IN": {"name": "English (India)", "native": "English", "gnani_code": "en-IN", "gnani_verified": True},
    "hi-IN": {"name": "Hindi", "native": "हिन्दी", "gnani_code": "hi-IN", "gnani_verified": True},
    "kn-IN": {"name": "Kannada", "native": "ಕನ್ನಡ", "gnani_code": "kn-IN", "gnani_verified": True},
}

MONTH_NAMES = {
    "en-IN": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December"],
    "hi-IN": ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "kn-IN": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
}


def spoken_date(lang: str, iso: str) -> str:
    """'2026-11-16' -> '16 November 2026' (Gnani TTS mispronounces raw ISO dates)."""
    try:
        y, m, d = (int(p) for p in iso.split("-"))
        return f"{d} {MONTH_NAMES[normalize_language(lang)][m - 1]} {y}"
    except (ValueError, IndexError, AttributeError):
        return str(iso)

FIELD_ORDER = [
    "beneficiary_id", "beneficiary_name", "visit_type", "weight_kg", "vaccinations_due",
    "vaccination_status", "anc_status", "ifa_status", "tt_status", "next_visit_date", "notes",
]

MESSAGES: dict[str, dict] = {
    "en-IN": {
        "labels": {
            "beneficiary_id": "Beneficiary ID", "beneficiary_name": "Name", "visit_type": "Visit type",
            "weight_kg": "Weight", "vaccinations_due": "Vaccinations due", "vaccination_status": "Vaccination status",
            "anc_status": "ANC checkup", "ifa_status": "IFA tablets", "tt_status": "TT injection",
            "next_visit_date": "Next visit date", "notes": "Notes",
        },
        "values": {
            "done": "done", "pending": "pending", "missed": "missed", "given": "given", "taking": "taking",
            "not_taking": "not taking", "due": "due", "not_given": "not given", "completed": "completed",
            "ANC": "ANC (pregnancy)", "PNC": "PNC (after delivery)", "HBNC": "Newborn care (HBNC)",
            "IMMUNIZATION": "Immunization", "GENERAL": "General",
        },
        "kg": "kilograms",
        "start": "Please speak the household visit details.",
        "readback_intro": "I have recorded:",
        "confirm_question": "Is this correct? Say 'yes' to save, or say the correct information to change it.",
        "ask_missing": "Please tell me: {fields}.",
        "ask_unclear": "I could not understand clearly: {fields}. Please repeat.",
        "not_understood": "Sorry, I did not understand. Please say it again.",
        "what_to_change": "Okay. Please say what should be changed.",
        "saved": "The visit record is saved.",
        "cancelled": "The record was not saved.",
        "referral": "Danger sign: {signs}. Refer to the PHC immediately.",
        "clarify_danger": "Possible danger sign: {signs}. Please say clearly whether this is present. Do not treat it as safe until confirmed.",
        "absent_signs": "Recorded as absent: {signs}.",
        "correction_applied": "Corrected.",
        "unknown_id": "Please check: beneficiary ID {id} is not in the register. If it is wrong, say the correct ID.",
    },
    "hi-IN": {
        "labels": {
            "beneficiary_id": "लाभार्थी आईडी", "beneficiary_name": "नाम", "visit_type": "विज़िट का प्रकार",
            "weight_kg": "वज़न", "vaccinations_due": "बाकी टीके", "vaccination_status": "टीकाकरण स्थिति",
            "anc_status": "ANC जांच", "ifa_status": "IFA गोली", "tt_status": "TT इंजेक्शन",
            "next_visit_date": "अगली विज़िट की तारीख", "notes": "नोट्स",
        },
        "values": {
            "done": "हो गई", "pending": "बाकी", "missed": "छूट गई", "given": "दी गई", "taking": "ले रही हैं",
            "not_taking": "नहीं ले रही हैं", "due": "बाकी", "not_given": "नहीं दिया गया", "completed": "पूरा",
            "ANC": "ANC (गर्भावस्था)", "PNC": "PNC (प्रसव के बाद)", "HBNC": "नवजात देखभाल (HBNC)",
            "IMMUNIZATION": "टीकाकरण", "GENERAL": "सामान्य",
        },
        "kg": "किलो",
        "start": "कृपया घर की विज़िट की जानकारी बोलिए।",
        "readback_intro": "मैंने यह दर्ज किया है:",
        "confirm_question": "क्या यह सही है? सेव करने के लिए 'हाँ' बोलिए, या बदलने के लिए सही जानकारी बोलिए।",
        "ask_missing": "कृपया बताइए: {fields}।",
        "ask_unclear": "यह साफ़ समझ नहीं आया: {fields}। कृपया दोबारा बोलिए।",
        "not_understood": "माफ़ कीजिए, समझ नहीं आया। कृपया दोबारा बोलिए।",
        "what_to_change": "ठीक है। कृपया बताइए क्या बदलना है।",
        "saved": "विज़िट रिकॉर्ड सेव हो गया।",
        "cancelled": "रिकॉर्ड सेव नहीं किया गया।",
        "referral": "खतरे का संकेत: {signs}। तुरंत PHC रेफर करें।",
        "clarify_danger": "संभावित खतरे का संकेत: {signs}। कृपया साफ़ बताइए कि यह है या नहीं। पुष्टि होने तक इसे सुरक्षित न मानें।",
        "absent_signs": "नहीं है के रूप में दर्ज: {signs}।",
        "correction_applied": "सुधार कर दिया।",
        "unknown_id": "कृपया जांचें: लाभार्थी आईडी {id} रजिस्टर में नहीं है। अगर गलत है तो सही आईडी बोलिए।",
    },
    "kn-IN": {
        "labels": {
            "beneficiary_id": "ಫಲಾನುಭವಿ ಐಡಿ", "beneficiary_name": "ಹೆಸರು", "visit_type": "ಭೇಟಿಯ ಪ್ರಕಾರ",
            "weight_kg": "ತೂಕ", "vaccinations_due": "ಬಾಕಿ ಲಸಿಕೆಗಳು", "vaccination_status": "ಲಸಿಕೆ ಸ್ಥಿತಿ",
            "anc_status": "ANC ತಪಾಸಣೆ", "ifa_status": "IFA ಮಾತ್ರೆ", "tt_status": "TT ಇಂಜೆಕ್ಷನ್",
            "next_visit_date": "ಮುಂದಿನ ಭೇಟಿಯ ದಿನಾಂಕ", "notes": "ಟಿಪ್ಪಣಿ",
        },
        "values": {
            "done": "ಆಗಿದೆ", "pending": "ಬಾಕಿ", "missed": "ತಪ್ಪಿದೆ", "given": "ಕೊಡಲಾಗಿದೆ", "taking": "ತೆಗೆದುಕೊಳ್ಳುತ್ತಿದ್ದಾರೆ",
            "not_taking": "ತೆಗೆದುಕೊಳ್ಳುತ್ತಿಲ್ಲ", "due": "ಬಾಕಿ", "not_given": "ಕೊಟ್ಟಿಲ್ಲ", "completed": "ಪೂರ್ಣ",
            "ANC": "ANC (ಗರ್ಭಾವಸ್ಥೆ)", "PNC": "PNC (ಹೆರಿಗೆ ನಂತರ)", "HBNC": "ನವಜಾತ ಶಿಶು ಆರೈಕೆ (HBNC)",
            "IMMUNIZATION": "ಲಸಿಕೆ", "GENERAL": "ಸಾಮಾನ್ಯ",
        },
        "kg": "ಕಿಲೋ",
        "start": "ದಯವಿಟ್ಟು ಮನೆ ಭೇಟಿಯ ವಿವರ ಹೇಳಿ.",
        "readback_intro": "ನಾನು ದಾಖಲಿಸಿದ್ದು:",
        "confirm_question": "ಇದು ಸರಿಯೇ? ಉಳಿಸಲು 'ಹೌದು' ಎನ್ನಿ, ಅಥವಾ ಬದಲಾಯಿಸಲು ಸರಿಯಾದ ಮಾಹಿತಿ ಹೇಳಿ.",
        "ask_missing": "ದಯವಿಟ್ಟು ಹೇಳಿ: {fields}.",
        "ask_unclear": "ಇದು ಸ್ಪಷ್ಟವಾಗಿ ಅರ್ಥವಾಗಲಿಲ್ಲ: {fields}. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ.",
        "not_understood": "ಕ್ಷಮಿಸಿ, ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ.",
        "what_to_change": "ಸರಿ. ಏನು ಬದಲಾಯಿಸಬೇಕು ಎಂದು ಹೇಳಿ.",
        "saved": "ಭೇಟಿಯ ದಾಖಲೆ ಉಳಿಸಲಾಗಿದೆ.",
        "cancelled": "ದಾಖಲೆ ಉಳಿಸಲಾಗಿಲ್ಲ.",
        "referral": "ಅಪಾಯದ ಲಕ್ಷಣ: {signs}. ತಕ್ಷಣ PHC ಗೆ ರೆಫರ್ ಮಾಡಿ.",
        "clarify_danger": "ಸಂಭವನೀಯ ಅಪಾಯದ ಲಕ್ಷಣ: {signs}. ಇದು ಇದೆಯೇ ಇಲ್ಲವೇ ಎಂದು ಸ್ಪಷ್ಟವಾಗಿ ಹೇಳಿ. ದೃಢಪಡಿಸುವವರೆಗೆ ಸುರಕ್ಷಿತ ಎಂದು ಪರಿಗಣಿಸಬೇಡಿ.",
        "absent_signs": "ಇಲ್ಲ ಎಂದು ದಾಖಲಿಸಲಾಗಿದೆ: {signs}.",
        "correction_applied": "ಸರಿಪಡಿಸಲಾಗಿದೆ.",
        "unknown_id": "ದಯವಿಟ್ಟು ಪರಿಶೀಲಿಸಿ: ಫಲಾನುಭವಿ ಐಡಿ {id} ರಿಜಿಸ್ಟರ್‌ನಲ್ಲಿ ಇಲ್ಲ. ತಪ್ಪಾಗಿದ್ದರೆ ಸರಿಯಾದ ಐಡಿ ಹೇಳಿ.",
    },
}

# Short spoken names of danger signs, per language (rule_id -> text).
DANGER_SIGN_NAMES: dict[str, dict[str, str]] = {
    "en-IN": {
        "BLEEDING": "bleeding", "CONVULSIONS": "convulsions or fits",
        "HEADACHE_BLURRED_VISION": "severe headache with blurred vision", "HIGH_FEVER_MOTHER": "high fever",
        "NEWBORN_FEVER": "fever in the newborn", "NEWBORN_LOW_TEMPERATURE": "newborn is cold, low temperature",
        "NEWBORN_NOT_FEEDING": "newborn not feeding", "BREATHING_DIFFICULTY": "fast or difficult breathing",
        "NEWBORN_NO_MOVEMENT": "newborn not moving normally", "SEVERE_ABDOMINAL_PAIN": "severe abdominal pain",
        "SWELLING_FACE_HANDS": "swelling of face or hands", "REDUCED_FETAL_MOVEMENT": "reduced baby movement in the womb",
        "LEAKING_FLUID": "leaking of water", "FOUL_DISCHARGE": "foul-smelling discharge",
    },
    "hi-IN": {
        "BLEEDING": "खून आना", "CONVULSIONS": "झटके या दौरे",
        "HEADACHE_BLURRED_VISION": "तेज़ सिरदर्द और धुंधला दिखना", "HIGH_FEVER_MOTHER": "तेज़ बुखार",
        "NEWBORN_FEVER": "नवजात को बुखार", "NEWBORN_LOW_TEMPERATURE": "नवजात का शरीर ठंडा",
        "NEWBORN_NOT_FEEDING": "नवजात दूध नहीं पी रहा", "BREATHING_DIFFICULTY": "तेज़ या कठिन सांस",
        "NEWBORN_NO_MOVEMENT": "नवजात ठीक से हिल नहीं रहा", "SEVERE_ABDOMINAL_PAIN": "पेट में तेज़ दर्द",
        "SWELLING_FACE_HANDS": "चेहरे या हाथों में सूजन", "REDUCED_FETAL_MOVEMENT": "पेट में बच्चे की हलचल कम",
        "LEAKING_FLUID": "पानी आना", "FOUL_DISCHARGE": "बदबूदार स्राव",
    },
    "kn-IN": {
        "BLEEDING": "ರಕ್ತಸ್ರಾವ", "CONVULSIONS": "ಫಿಟ್ಸ್ ಅಥವಾ ಸೆಳೆತ",
        "HEADACHE_BLURRED_VISION": "ತೀವ್ರ ತಲೆನೋವು ಮತ್ತು ಮಸುಕಾದ ದೃಷ್ಟಿ", "HIGH_FEVER_MOTHER": "ತೀವ್ರ ಜ್ವರ",
        "NEWBORN_FEVER": "ಶಿಶುವಿಗೆ ಜ್ವರ", "NEWBORN_LOW_TEMPERATURE": "ಶಿಶುವಿನ ಮೈ ತಣ್ಣಗಿದೆ",
        "NEWBORN_NOT_FEEDING": "ಶಿಶು ಹಾಲು ಕುಡಿಯುತ್ತಿಲ್ಲ", "BREATHING_DIFFICULTY": "ವೇಗದ ಅಥವಾ ಕಷ್ಟದ ಉಸಿರಾಟ",
        "NEWBORN_NO_MOVEMENT": "ಶಿಶು ಸರಿಯಾಗಿ ಚಲಿಸುತ್ತಿಲ್ಲ", "SEVERE_ABDOMINAL_PAIN": "ತೀವ್ರ ಹೊಟ್ಟೆ ನೋವು",
        "SWELLING_FACE_HANDS": "ಮುಖ ಅಥವಾ ಕೈ ಊತ", "REDUCED_FETAL_MOVEMENT": "ಹೊಟ್ಟೆಯಲ್ಲಿ ಮಗುವಿನ ಚಲನೆ ಕಡಿಮೆ",
        "LEAKING_FLUID": "ನೀರು ಸೋರುವಿಕೆ", "FOUL_DISCHARGE": "ದುರ್ವಾಸನೆಯ ಸ್ರಾವ",
    },
}


def normalize_language(code: str | None) -> str:
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def list_languages() -> list[dict]:
    return [{"code": c, **info} for c, info in LANGUAGES.items()]


def msg(lang: str, key: str, **kwargs) -> str:
    lang = normalize_language(lang)
    text = MESSAGES[lang].get(key) or MESSAGES[DEFAULT_LANGUAGE][key]
    return text.format(**kwargs) if kwargs else text


def label(lang: str, field_name: str) -> str:
    lang = normalize_language(lang)
    return MESSAGES[lang]["labels"].get(field_name, field_name)


def value_text(lang: str, value) -> str:
    lang = normalize_language(lang)
    if isinstance(value, list):
        return ", ".join(value_text(lang, v) for v in value) if value else "-"
    return MESSAGES[lang]["values"].get(str(value), str(value))


def sign_names(lang: str, rule_ids: list[str]) -> str:
    lang = normalize_language(lang)
    names = DANGER_SIGN_NAMES[lang]
    seen, out = set(), []
    for r in rule_ids:
        if r not in seen:
            seen.add(r)
            out.append(names.get(r, DANGER_SIGN_NAMES[DEFAULT_LANGUAGE].get(r, r)))
    return ", ".join(out)


def build_readback(lang: str, record: dict) -> str:
    """Builds the sentence that is read aloud (via Gnani TTS) for confirmation."""
    lang = normalize_language(lang)
    parts = [msg(lang, "readback_intro")]
    for f in FIELD_ORDER:
        v = record.get(f)
        if v in (None, "", []):
            continue
        if f == "weight_kg":
            parts.append(f"{label(lang, f)}: {v} {MESSAGES[lang]['kg']}.")
        elif f == "next_visit_date":
            parts.append(f"{label(lang, f)}: {spoken_date(lang, v)}.")
        elif f in ("beneficiary_id", "beneficiary_name", "notes"):
            parts.append(f"{label(lang, f)}: {v}.")
        else:
            parts.append(f"{label(lang, f)}: {value_text(lang, v)}.")
    return " ".join(parts)
