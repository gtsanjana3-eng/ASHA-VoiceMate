"""Deterministic danger-sign rules engine.

WHAT THIS DOES
    Looks for a FIXED, documented list of danger signs in the transcript.
    It never diagnoses, never suggests medicine, and never says a case is "safe".
    The only instruction it produces is: "refer to the PHC immediately".

FOUR POSSIBLE RESULTS FOR EACH MENTION
    danger   -> clear danger sign. Show red alert, speak PHC referral, flag record.
    clarify  -> possible danger sign, but speech was uncertain ("maybe", "shayad")
                or important context is missing (e.g. "fever" but we don't know
                if it is the newborn). Ask the worker to clarify + human review.
    negated  -> the worker said it is ABSENT ("no bleeding"). It is NOT silently
                dropped: it is read back aloud ("Recorded as absent: bleeding")
                so the worker confirms it.
    (nothing found) -> "No predefined danger sign detected". This is NOT "safe".

SOURCES
    Every rule has a `source` field. The full reference list is in README.md
    (section "Danger-sign rules and official references").

HOW TO ADD A RULE
    Add a DangerRule(...) to RULES below and a test in tests/test_danger_signs.py.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

LEVEL_DANGER = "danger"
LEVEL_CLARIFY = "clarify"
LEVEL_NEGATED = "negated"
LEVEL_NONE = "none"

# ---------------------------------------------------------------------------
# Source documents (short keys used by rules; full citations in README.md)
# ---------------------------------------------------------------------------
SOURCES = {
    "WHO_UNICEF_2009": (
        "WHO/UNICEF Joint Statement: Home visits for the newborn child - a strategy "
        "to improve survival (2009), list of newborn danger signs requiring referral."
    ),
    "WHO_PCPNC_2015": (
        "WHO: Pregnancy, Childbirth, Postpartum and Newborn Care - A guide for "
        "essential practice, 3rd edition (2015), danger signs for the woman."
    ),
    "MOHFW_MCP_CARD": (
        "MoHFW (Govt. of India) Mother and Child Protection (MCP) Card - danger "
        "signs during pregnancy / after delivery."
    ),
    "MOHFW_HBNC_2014": (
        "MoHFW (Govt. of India) Home Based Newborn Care (HBNC) Operational "
        "Guidelines (2014) - newborn danger signs for ASHA referral."
    ),
}


@dataclass(frozen=True)
class DangerRule:
    rule_id: str
    category: str                      # "pregnancy" | "postpartum" | "newborn" | "mother_or_newborn"
    name: str                          # English display name
    patterns: tuple[str, ...]          # regexes that indicate the sign
    reason: str                        # why it is a danger sign (from the source)
    sources: tuple[str, ...]           # keys into SOURCES
    requires_context: str | None = None  # "pregnancy" | "newborn" | None
    uncertain_patterns: tuple[str, ...] = ()  # weaker mentions -> always "clarify"


# ---------------------------------------------------------------------------
# THE RULES (patterns cover English, Hindi (Devanagari + romanised), Kannada)
# ---------------------------------------------------------------------------
RULES: tuple[DangerRule, ...] = (
    DangerRule(
        rule_id="BLEEDING",
        category="mother_or_newborn",
        name="Bleeding (during pregnancy or after delivery)",
        patterns=(
            r"\bbleed\w*", r"\bblood\s+(is\s+)?(coming|loss|discharge|flow\w*)",
            # "khoon ki kami" (low blood / anaemia) and "khoon jaanch" (blood test) are NOT bleeding.
            r"\bkhoo?n\b(?!\s*(ki|ka|ke)?\s*(kami|jaanch|janch|test))", r"\brakt\s?srav", r"\braktasrava\b",
            r"खून(?!\s*(की|का|के)?\s*(कमी|जांच|जाँच|टेस्ट))", "रक्तस्राव", "ब्लीडिंग", "ರಕ್ತಸ್ರಾವ", "ರಕ್ತ ಹೋಗ", "ಬ್ಲೀಡಿಂಗ್",
        ),
        reason="Vaginal bleeding in pregnancy or heavy bleeding after delivery is a danger sign requiring immediate referral.",
        sources=("WHO_PCPNC_2015", "MOHFW_MCP_CARD"),
    ),
    DangerRule(
        rule_id="CONVULSIONS",
        category="mother_or_newborn",
        name="Convulsions / fits",
        patterns=(
            r"\bconvuls\w*", r"\bfits?\b", r"\bseizures?\b", r"\bjhatk[ae]\b",
            # plain "daura" also means "visit", so only "daure pad(na)" counts.
            r"\bdaur[ae]\s+pa[dr]", r"\bmirgi\b", "झटके", "दौरे पड़", "दौरा पड़", "मिर्गी", "ಫಿಟ್ಸ್", "ಸೆಳೆತ",
        ),
        reason="Convulsions in a pregnant/postpartum woman or a newborn are a danger sign requiring immediate referral.",
        sources=("WHO_PCPNC_2015", "WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
    ),
    DangerRule(
        rule_id="HEADACHE_BLURRED_VISION",
        category="pregnancy",
        name="Severe headache with blurred vision",
        patterns=(
            r"(headache|head\s?ache|sar\s?dard|सिर\s?दर्द|ತಲೆ\s?ನೋವು).{0,60}(blur\w*|vision|dhundh\w*|धुंधला|धुँधला|ಮಸುಕು)",
            r"(blur\w*|dhundh\w*|धुंधला|धुँधला|ಮಸುಕು).{0,60}(headache|head\s?ache|sar\s?dard|सिर\s?दर्द|ತಲೆ\s?ನೋವು)",
        ),
        uncertain_patterns=(r"\bheadache\b", r"\bsar\s?dard\b", "सिर दर्द", "सिरदर्द", "ತಲೆನೋವು", "ತಲೆ ನೋವು"),
        reason="Severe headache with blurred vision in pregnancy is a danger sign requiring immediate referral.",
        sources=("WHO_PCPNC_2015", "MOHFW_MCP_CARD"),
    ),
    DangerRule(
        rule_id="HIGH_FEVER_MOTHER",
        category="pregnancy",
        name="High fever (pregnant / postpartum woman)",
        patterns=(
            r"\bhigh\s+(grade\s+)?fever\b", r"\bsevere\s+fever\b", r"\btez\s+bukhar\b",
            r"\bbahut\s+bukhar\b", "तेज़ बुखार", "तेज बुखार", "बहुत बुखार",
            "ಹೆಚ್ಚು ಜ್ವರ", "ತೀವ್ರ ಜ್ವರ", "ತುಂಬಾ ಜ್ವರ",
        ),
        reason="High fever in pregnancy or after delivery is a danger sign requiring referral.",
        sources=("WHO_PCPNC_2015", "MOHFW_MCP_CARD"),
    ),
    DangerRule(
        rule_id="NEWBORN_FEVER",
        category="newborn",
        name="Fever in newborn (temperature 37.5 C or more)",
        patterns=(
            r"\bfever\b", r"\bbukhar\b", r"\bjwara\b", r"\bjvara\b",
            "बुखार", "ज्वर", "ಜ್ವರ",
        ),
        reason="Fever (temperature >= 37.5 C) in a newborn is a danger sign requiring referral.",
        sources=("WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
        requires_context="newborn",
    ),
    DangerRule(
        rule_id="NEWBORN_LOW_TEMPERATURE",
        category="newborn",
        name="Low body temperature in newborn (below 35.5 C)",
        patterns=(
            r"\bcold\s+to\s+(the\s+)?touch\b", r"\bbody\s+(is\s+)?(very\s+)?cold\b",
            r"\bhypotherm\w*", r"\bthanda\s+(pad|ho)", "ठंडा पड़", "ठंडा हो", "ಮೈ ತಣ್ಣಗ", "ತಣ್ಣಗಾಗಿ",
        ),
        reason="Low body temperature (< 35.5 C) in a newborn is a danger sign requiring referral.",
        sources=("WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
        requires_context="newborn",
    ),
    DangerRule(
        rule_id="NEWBORN_NOT_FEEDING",
        category="newborn",
        name="Newborn not feeding well / stopped feeding",
        patterns=(
            r"\bnot\s+(feeding|sucking|breast\s?feeding|drinking\s+milk|taking\s+(feeds?|milk))\b",
            r"\b(stopped|unable\s+to|cannot|can't)\s+(feed\w*|suck\w*|breast\s?feed\w*)",
            r"\bdoodh\s+(nahi|nahin|nai)\s+pee", r"\bdoodh\s+(peena\s+)?(band|chhod)",
            "दूध नहीं पी", "दूध पीना बंद", "दूध नहीं ले",
            "ಹಾಲು ಕುಡಿಯುತ್ತಿಲ್ಲ", "ಹಾಲು ಕುಡಿಯಲ್ಲ", "ಹಾಲು ಕುಡಿಯುವುದಿಲ್ಲ", r"\bhaalu\s+kudiyuttilla\b", r"\bhalu\s+kudiyuttilla\b",
        ),
        reason="Not feeding well / unable to feed is a newborn danger sign requiring referral.",
        sources=("WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
    ),
    DangerRule(
        rule_id="BREATHING_DIFFICULTY",
        category="mother_or_newborn",
        name="Fast or difficult breathing / chest indrawing",
        patterns=(
            r"\b(difficult\w*|trouble|problem)\s+(in\s+|with\s+)?breath\w*", r"\bbreathless\w*",
            r"\bfast\s+breath\w*", r"\brapid\s+breath\w*", r"\bchest\s+in\s?-?\s?drawing\b",
            r"\bsaa?ns\s+(lene\s+)?(me|mein)\s+(taklif|takleef|dikkat|pareshani)",
            r"\bsaa?ns\s+(tez|phool)", r"\bpasli\s+chal", "सांस लेने में", "साँस लेने में",
            "सांस तेज", "साँस तेज", "पसली चल", "ಉಸಿರಾಟದ ತೊಂದರೆ", "ಉಸಿರು ಕಟ್ಟು", "ವೇಗವಾಗಿ ಉಸಿರಾಡ",
        ),
        reason="Fast/difficult breathing (newborn: 60 or more breaths per minute) or severe chest indrawing is a danger sign requiring referral.",
        sources=("WHO_PCPNC_2015", "WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
    ),
    DangerRule(
        rule_id="NEWBORN_NO_MOVEMENT",
        category="newborn",
        name="Newborn moves only when stimulated / no movement",
        patterns=(
            r"\b(not|no)\s+mov(ing|ement)\b", r"\bonly\s+(moves|moving)\s+when\b", r"\blethargic\b",
            r"\bunconscious\b", r"\bbehosh\b", r"\bsust\b", r"\bhil(ta|na|\s)?\s*(nahi|nahin)\b",
            "हिल नहीं", "हिलता नहीं", "सुस्त", "बेहोश", "ಚಲಿಸುತ್ತಿಲ್ಲ", "ಚಲನೆ ಇಲ್ಲ", "ಪ್ರಜ್ಞೆ ಇಲ್ಲ",
        ),
        reason="Movement only when stimulated or no movement at all is a newborn danger sign requiring referral.",
        sources=("WHO_UNICEF_2009", "MOHFW_HBNC_2014"),
        requires_context="newborn",
    ),
    DangerRule(
        rule_id="SEVERE_ABDOMINAL_PAIN",
        category="pregnancy",
        name="Severe abdominal pain",
        patterns=(
            r"\b(severe|bad|intense|a\s+lot\s+of)\s+(abdominal|stomach|tummy|belly)\s+pain\b",
            r"\b(abdominal|stomach)\s+pain\s+is\s+(severe|very\s+bad)",
            r"\b(tez|bahut)\s+pet\s+(me|mein)?\s*dard\b", r"\bpet\s+(me|mein)\s+(tez|bahut)\s+dard\b",
            "पेट में तेज़ दर्द", "पेट में तेज दर्द", "पेट में बहुत दर्द", "तेज़ पेट दर्द",
            "ತೀವ್ರ ಹೊಟ್ಟೆ ನೋವು", "ತುಂಬಾ ಹೊಟ್ಟೆ ನೋವು",
        ),
        uncertain_patterns=(
            r"\b(abdominal|stomach|tummy|belly)\s+pain\b", r"\bpet\s+(me\s+|mein\s+)?dard\b", "पेट दर्द", "पेट में दर्द", "ಹೊಟ್ಟೆ ನೋವು",
        ),
        reason="Severe abdominal pain in pregnancy is a danger sign requiring immediate referral.",
        sources=("WHO_PCPNC_2015", "MOHFW_MCP_CARD"),
    ),
    DangerRule(
        rule_id="SWELLING_FACE_HANDS",
        category="pregnancy",
        name="Swelling of face or hands in pregnancy",
        patterns=(
            r"\bswell\w*\s+(of\s+|on\s+|in\s+)?(the\s+)?(face|hands?|fingers)\b",
            r"\b(face|hands?|fingers)\s+(is\s+|are\s+)?swell\w*",
            r"\b(chehre|haath|hath)\s+(par|pe|me|mein)?\s*soojan\b", "चेहरे पर सूजन", "हाथ में सूजन", "हाथों में सूजन",
            "ಮುಖ ಊದ", "ಕೈ ಊದ",
        ),
        reason="Swelling of face/hands in pregnancy is listed as a danger sign needing referral.",
        sources=("MOHFW_MCP_CARD", "WHO_PCPNC_2015"),
        requires_context="pregnancy",
    ),
    DangerRule(
        rule_id="REDUCED_FETAL_MOVEMENT",
        category="pregnancy",
        name="Reduced or absent fetal movements",
        patterns=(
            r"\b(fetal|foetal|baby'?s?)\s+movements?\s+(is\s+|are\s+)?(less|reduced|decreased|absent|stopped|not\s+felt)",
            r"\b(less|reduced|decreased|no)\s+(fetal|foetal)\s+movements?",
            r"\bbaby\s+(is\s+)?not\s+moving\s+(in\s+(the\s+)?(womb|stomach|tummy))",
            r"\bpet\s+(me|mein)\s+bach\w*\s+(hil|hal)\w*\s+(nahi|kam)",
            "पेट में बच्चा हिल नहीं", "बच्चे की हलचल कम", "हलचल कम", "हलचल नहीं",
            "ಮಗುವಿನ ಚಲನೆ ಕಡಿಮೆ", "ಹೊಟ್ಟೆಯಲ್ಲಿ ಮಗು ಚಲಿಸುತ್ತಿಲ್ಲ",
        ),
        reason="Reduced or absent fetal movement is a danger sign in pregnancy requiring referral.",
        sources=("MOHFW_MCP_CARD",),
        requires_context="pregnancy",
    ),
    DangerRule(
        rule_id="LEAKING_FLUID",
        category="pregnancy",
        name="Leaking of water / fluid from vagina in pregnancy",
        patterns=(
            r"\b(water|fluid)\s+(is\s+)?(leak\w*|coming\s+out)", r"\bleak\w*\s+(of\s+)?(water|fluid)\b",
            r"\bwater\s+broke\b", r"\bpaani\s+(aa\s+raha|nikal|gir|leak)", "पानी आ रहा", "पानी निकल", "पानी गिर",
            "ನೀರು ಸೋರು", "ನೀರು ಹೋಗು",
        ),
        reason="Leaking of watery fluid in pregnancy is listed as a danger sign requiring referral.",
        sources=("MOHFW_MCP_CARD",),
        requires_context="pregnancy",
    ),
    DangerRule(
        rule_id="FOUL_DISCHARGE",
        category="postpartum",
        name="Foul-smelling vaginal discharge after delivery",
        patterns=(
            r"\bfoul\s?-?\s?smell\w*", r"\bbad\s+smell\w*\s+discharge\b", r"\bsmelly\s+discharge\b",
            r"\bbadbu\w*", "बदबू", "बदबूदार", "ದುರ್ವಾಸನೆ",
        ),
        reason="Foul-smelling vaginal discharge after delivery is a danger sign requiring referral.",
        sources=("WHO_PCPNC_2015", "MOHFW_MCP_CARD"),
    ),
)

RULES_BY_ID = {r.rule_id: r for r in RULES}

# ---------------------------------------------------------------------------
# Context, negation and uncertainty word lists
# ---------------------------------------------------------------------------
NEWBORN_CONTEXT = (
    r"\bbaby\b", r"\bnew\s?born\b", r"\binfant\b", r"\bshishu\b", r"\bbach+[aei]\b", r"\bnavjaat\b",
    r"\bhbnc\b", r"\bmagu\w*", "बच्चा", "बच्चे", "बच्ची", "शिशु", "नवजात", "ಮಗು", "ಮಗುವ", "ಶಿಶು",
)
PREGNANCY_CONTEXT = (
    r"\bpregnan\w*", r"\banc\b", r"\bgarbh\w*", r"\bbasari\b", r"\bwomb\b", r"\bpet\s+(me|mein)\s+bach",
    "गर्भ", "गर्भवती", "ಗರ್ಭಿಣಿ", "ಬಸುರಿ", "ಗರ್ಭ",
)
VISIT_TYPE_CONTEXT = {
    "ANC": {"pregnancy"},
    "PNC": {"newborn", "postpartum"},
    "HBNC": {"newborn"},
    "IMMUNIZATION": {"newborn"},
}

# Negation BEFORE the sign (English style: "no bleeding").
NEG_BEFORE = {"no", "not", "without", "never", "nil", "none", "denies", "bina", "बिना"}
# Negation AFTER the sign (Hindi/Kannada style: "bleeding nahi hai", "ಜ್ವರ ಇಲ್ಲ").
NEG_AFTER = {"nahi", "nahin", "nai", "नहीं", "नही", "illa", "ಇಲ್ಲ", "ಇಲ್ಲಾ"}
# Phrases that mean the sign is CONTINUING, so they must NOT count as negation.
PERSISTENCE = (
    r"\b(band|ruk|kam|utar|utra|utri|stop)\w*\s+(nahi|nahin|nai)\b",
    r"\b(nahi|nahin|nai)\s+(ruk|band|utar|utr|kam)\w*",
    r"\bnot\s+(stopp\w*|reduc\w*|decreas\w*|going\s+down|com\w*\s+down)",
    "बंद नहीं", "रुक नहीं", "कम नहीं", "उतर नहीं", "नहीं रुक", "नहीं उतर", "ನಿಲ್ಲುತ್ತಿಲ್ಲ", "ಕಡಿಮೆ ಆಗಿಲ್ಲ", "ಕಡಿಮೆಯಾಗಿಲ್ಲ",
)
HEDGES = (
    r"\bmaybe\b", r"\bperhaps\b", r"\bmight\b", r"\bnot\s+sure\b", r"\bi\s+think\b", r"\bseems?\b",
    r"\bpossibly\b", r"\bshayad\b", r"\blagta\b", r"\bpata\s+nahi\b", "शायद", "लगता", "पता नहीं",
    "ಬಹುಶಃ", "ಅನಿಸುತ್ತೆ", "ಗೊತ್ತಿಲ್ಲ",
)
CLAUSE_SPLIT = re.compile(r"[.;!?\n।|]+|\bbut\b|\blekin\b|\bmagar\b|लेकिन|मगर|ಆದರೆ")


def _any(patterns, text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass
class DangerMatch:
    rule_id: str
    name: str
    category: str
    level: str
    phrase: str
    reason: str
    sources: list[str]
    needs_human_review: bool = False
    note: str = ""
    start: int = 0
    end: int = 0


@dataclass
class DangerAssessment:
    level: str = LEVEL_NONE
    matches: list[DangerMatch] = field(default_factory=list)

    @property
    def urgent_referral(self) -> bool:
        return self.level == LEVEL_DANGER

    @property
    def needs_human_review(self) -> bool:
        return any(m.needs_human_review for m in self.matches)

    def by_level(self, level: str) -> list[DangerMatch]:
        return [m for m in self.matches if m.level == level]

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "urgent_referral": self.urgent_referral,
            "needs_human_review": self.needs_human_review,
            "matches": [asdict(m) for m in self.matches],
            "status_text": STATUS_TEXT[self.level],
        }


STATUS_TEXT = {
    LEVEL_DANGER: "DANGER SIGN DETECTED - refer to PHC immediately",
    LEVEL_CLARIFY: "Possible danger sign - clarification and human review required",
    LEVEL_NONE: "No predefined danger sign detected (this is NOT a safety clearance)",
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detect_context(text: str, visit_type: str | None = None) -> set[str]:
    ctx: set[str] = set(VISIT_TYPE_CONTEXT.get((visit_type or "").upper(), set()))
    if _any(NEWBORN_CONTEXT, text):
        ctx.add("newborn")
    if _any(PREGNANCY_CONTEXT, text):
        ctx.add("pregnancy")
    return ctx


def _clauses(text: str) -> list[tuple[int, str]]:
    """Split into clauses, returning (offset, clause_text)."""
    out, pos = [], 0
    for m in CLAUSE_SPLIT.finditer(text):
        out.append((pos, text[pos:m.start()]))
        pos = m.end()
    out.append((pos, text[pos:]))
    return [(o, c) for o, c in out if c.strip()]


def _is_negated(clause: str, start: int, end: int) -> bool:
    if _any(PERSISTENCE, clause):
        return False
    before = clause[:start].split()[-2:]
    after = clause[end:].split()[:2]
    if any(w.strip(",'") in NEG_BEFORE for w in before):
        return True
    for w in after:
        w = w.strip(",'")
        if w in NEG_AFTER or (w.endswith("ಲ್ಲ") and len(w) > 2):
            return True
    return False


def _numeric_checks(text: str, ctx: set[str]) -> list[DangerMatch]:
    """Temperature and breathing-rate thresholds from WHO/UNICEF 2009 + HBNC."""
    found: list[DangerMatch] = []
    newborn = "newborn" in ctx

    temp_re = re.compile(
        r"(temperature|temp|tapman|तापमान|ತಾಪಮಾನ|fever|bukhar|बुखार|ಜ್ವರ)\D{0,15}?(\d{2,3}(?:\.\d+)?)\s*(°|degrees?|deg)?\s*(c|f|celsius|fahrenheit)?\b"
    )
    for m in temp_re.finditer(text):
        value = float(m.group(2))
        unit = (m.group(4) or "").lower()
        celsius = (value - 32) * 5 / 9 if (unit.startswith("f") or value > 45) else value
        if not 25 <= celsius <= 45:
            continue
        phrase = m.group(0)
        if newborn and celsius >= 37.5:
            r = RULES_BY_ID["NEWBORN_FEVER"]
            found.append(_match(r, LEVEL_DANGER, phrase, m, note=f"Temperature {celsius:.1f} C >= 37.5 C"))
        elif newborn and celsius < 35.5:
            r = RULES_BY_ID["NEWBORN_LOW_TEMPERATURE"]
            found.append(_match(r, LEVEL_DANGER, phrase, m, note=f"Temperature {celsius:.1f} C < 35.5 C"))
        elif not newborn and celsius >= 37.5:
            r = RULES_BY_ID["HIGH_FEVER_MOTHER"]
            found.append(_match(r, LEVEL_CLARIFY, phrase, m, review=True,
                                note=f"Raised temperature {celsius:.1f} C - confirm whether this is the newborn or the mother"))

    breath_re = re.compile(r"(breath\w*|respirat\w*|saa?ns|सांस|साँस|ಉಸಿರು|ಉಸಿರಾಟ)\D{0,20}?(\d{2,3})\s*(per|/|a|times|breaths|प्रति|ಪ್ರತಿ)")
    for m in breath_re.finditer(text):
        rate = int(m.group(2))
        if rate >= 60:
            r = RULES_BY_ID["BREATHING_DIFFICULTY"]
            level = LEVEL_DANGER if newborn else LEVEL_CLARIFY
            found.append(_match(r, level, m.group(0), m, review=not newborn,
                                note=f"Breathing rate {rate}/min >= 60" + ("" if newborn else " - confirm it is the newborn")))
    return found


def _match(rule: DangerRule, level: str, phrase: str, m, review: bool = False, note: str = "", offset: int = 0) -> DangerMatch:
    return DangerMatch(
        rule_id=rule.rule_id, name=rule.name, category=rule.category, level=level,
        phrase=phrase.strip(), reason=rule.reason, sources=list(rule.sources),
        needs_human_review=review or level == LEVEL_CLARIFY, note=note,
        start=offset + m.start(), end=offset + m.end(),
    )


def detect_danger_signs(text: str, visit_type: str | None = None, extra_context: str = "") -> DangerAssessment:
    """Main entry point. `extra_context` = earlier transcript of the same visit."""
    norm = normalize(text)
    if not norm:
        return DangerAssessment()
    ctx = detect_context(norm + " " + normalize(extra_context), visit_type)
    matches: list[DangerMatch] = []

    for offset, clause in _clauses(norm):
        hedged = _any(HEDGES, clause)
        for rule in RULES:
            # In a newborn-only visit, "high fever" is handled by NEWBORN_FEVER.
            if rule.rule_id == "HIGH_FEVER_MOTHER" and "newborn" in ctx and "pregnancy" not in ctx and "postpartum" not in ctx:
                continue
            hit = None
            for p in rule.patterns:
                hit = re.search(p, clause)
                if hit:
                    break
            weak = False
            if not hit:
                for p in rule.uncertain_patterns:
                    hit = re.search(p, clause)
                    if hit:
                        weak = True
                        break
            if not hit:
                continue

            phrase = hit.group(0)
            if _is_negated(clause, hit.start(), hit.end()):
                matches.append(_match(rule, LEVEL_NEGATED, phrase, hit, offset=offset,
                                      note="Worker said this sign is ABSENT - read back for confirmation"))
                matches[-1].needs_human_review = False
                continue
            if weak:
                matches.append(_match(rule, LEVEL_CLARIFY, phrase, hit, offset=offset,
                                      note="Symptom mentioned but severity unclear - please clarify"))
            elif rule.requires_context and rule.requires_context not in ctx:
                matches.append(_match(rule, LEVEL_CLARIFY, phrase, hit, offset=offset,
                                      note=f"Possible danger sign - confirm whether this is about the {rule.requires_context.replace('newborn', 'newborn baby').replace('pregnancy', 'pregnant woman')}"))
            elif hedged:
                matches.append(_match(rule, LEVEL_CLARIFY, phrase, hit, offset=offset,
                                      note="Speech was uncertain (e.g. 'maybe') - please confirm"))
            else:
                matches.append(_match(rule, LEVEL_DANGER, phrase, hit, offset=offset))

    matches.extend(_numeric_checks(norm, ctx))
    matches = _dedupe(matches)

    if any(m.level == LEVEL_DANGER for m in matches):
        level = LEVEL_DANGER
    elif any(m.level == LEVEL_CLARIFY for m in matches):
        level = LEVEL_CLARIFY
    else:
        level = LEVEL_NONE
    return DangerAssessment(level=level, matches=matches)


def _dedupe(matches: list[DangerMatch]) -> list[DangerMatch]:
    """Remove a 'clarify' match if a 'danger' match covers the same words or same rule."""
    dangers = [m for m in matches if m.level == LEVEL_DANGER]
    out, seen = [], set()
    for m in matches:
        if m.level == LEVEL_CLARIFY and any(
            d.rule_id == m.rule_id or (d.start < m.end and m.start < d.end) for d in dangers
        ):
            continue
        key = (m.rule_id, m.level, m.phrase)
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def merge_assessments(a: DangerAssessment, b: DangerAssessment) -> DangerAssessment:
    """Combine results from several utterances of the same visit (never downgrades)."""
    combined = _dedupe(a.matches + b.matches)
    # A later clear danger for the same rule supersedes an earlier 'clarify' or 'negated'.
    danger_rules = {m.rule_id for m in combined if m.level == LEVEL_DANGER}
    combined = [m for m in combined if m.level == LEVEL_DANGER or m.rule_id not in danger_rules]
    order = [LEVEL_DANGER, LEVEL_CLARIFY]
    level = next((lv for lv in order if any(m.level == lv for m in combined)), LEVEL_NONE)
    return DangerAssessment(level=level, matches=combined)


def rules_table() -> list[dict]:
    """For the README / UI: every rule with its sources."""
    return [
        {
            "rule_id": r.rule_id, "name": r.name, "category": r.category, "reason": r.reason,
            "requires_context": r.requires_context, "sources": [SOURCES[s] for s in r.sources],
        }
        for r in RULES
    ]
