"""Visit agent: turns transcript text into a structured visit record.

It is DETERMINISTIC (rules + regular expressions, no AI guessing), so every
decision can be inspected and tested. If something is not clearly said, the
field is left empty or marked "unclear" and the worker is asked again.

Flow handled by VisitSession:
    collecting -> (all required fields known) -> awaiting_confirmation
    awaiting_confirmation + correction  -> read back again
    awaiting_confirmation + "yes"       -> confirmed  (caller saves to database)
    awaiting_confirmation + "cancel"    -> cancelled
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import language_service as L
from .danger_signs import (
    LEVEL_CLARIFY, LEVEL_DANGER, LEVEL_NEGATED, DangerAssessment, detect_danger_signs,
    merge_assessments, normalize,
)

STATE_COLLECTING = "collecting"
STATE_AWAITING = "awaiting_confirmation"
STATE_CONFIRMED = "confirmed"
STATE_CANCELLED = "cancelled"

# ---------------------------------------------------------------------------
# Spoken English numbers -> digits ("two point eight" -> "2.8")
# ---------------------------------------------------------------------------
_ONES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}


def words_to_numbers(text: str) -> str:
    tokens = text.split(" ")
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in _ONES or t in _TENS:
            value = _ONES.get(t, _TENS.get(t))
            i += 1
            if t in _TENS and i < len(tokens) and tokens[i] in _ONES and _ONES[tokens[i]] < 10:
                value += _ONES[tokens[i]]
                i += 1
            s = str(value)
            if i < len(tokens) and tokens[i] == "point":
                digits, j = "", i + 1
                while j < len(tokens) and tokens[j] in _ONES and _ONES[tokens[j]] < 10:
                    digits += str(_ONES[tokens[j]])
                    j += 1
                if digits:
                    s += "." + digits
                    i = j
            out.append(s)
        else:
            out.append(t)
            i += 1
    text = " ".join(out)
    return re.sub(r"(\d)\s+point\s+(\d)", r"\1.\2", text)


# ---------------------------------------------------------------------------
# Anchors: words that start a field. A "weak" anchor directly after another
# anchor is absorbed (e.g. "TT ಲಸಿಕೆ" is TT, not a general vaccine).
# ---------------------------------------------------------------------------
VACCINES = {
    "BCG": [r"\bbcg\b", r"\bb\s?c\s?g\b"],
    "OPV": [r"\bopv\b", r"\bpolio\b", "पोलियो", "ಪೋಲಿಯೊ"],
    "Hepatitis B": [r"\bhep(atitis)?\s?-?b\b"],
    "Pentavalent": [r"\bpenta(valent)?\b", "पेंटा", "ಪೆಂಟಾ"],
    "Rotavirus": [r"\brota(virus)?\b", "रोटा"],
    "IPV": [r"\bf?ipv\b"],
    "PCV": [r"\bpcv\b"],
    "MR": [r"\bmr\b", r"\bmeasles\b", r"\bkhasra\b", "खसरा", "ದಡಾರ"],
    "DPT": [r"\bdpt\b"],
    "JE": [r"\bje\b", r"\bjapanese\s+encephalitis\b"],
    "Vitamin A": [r"\bvitamin\s?-?a\b"],
}

ANCHORS: list[tuple[str, str, bool]] = []  # (field, regex, weak)
for _name, _pats in VACCINES.items():
    ANCHORS += [("vacc:" + _name, p, False) for p in _pats]
ANCHORS += [("vacc", p, True) for p in (
    r"\bvaccin\w*", r"\bimmuni[sz]\w*", r"\bteekakaran\b", r"\btikakaran\b", "टीकाकरण", "ಲಸಿಕೆ")]
ANCHORS += [("anc", p, False) for p in (r"\banc\b", r"\bante\s?natal\b")]
ANCHORS += [("anc", p, True) for p in (r"\bcheck\s?-?up\b", r"\bjaa?nch\b", "जांच", "जाँच", "ತಪಾಸಣೆ")]
ANCHORS += [("ifa", p, False) for p in (r"\bifa\b", r"\bi\s?f\s?a\b", r"\biron\b", "आयरन", "आईएफए", "ಐಎಫ್ಎ", "ಕಬ್ಬಿಣ")]
ANCHORS += [("tt", p, False) for p in (r"\bt\.?\s?t\.?(?=\s|$|,)", r"\btd\b", r"\btetanus\b", "टीटी", "ಟಿಟಿ")]
ANCHORS += [("weight", p, False) for p in (r"\bweight\b", r"\bw[ae]jan\b", r"\bvajan\b", "वजन", "वज़न", "ತೂಕ")]
ANCHORS += [("next", p, False) for p in (
    r"\bnext\s+(visit|date|check\s?-?up|appointment)\w*", r"\bfollow\s?-?up\b", r"\bagl[aie]\s+(visit|mulakat|bhet)",
    r"\b(visit|come)\s+again\b", "अगली विज़िट", "अगली विजिट", "अगली मुलाकात", "ಮುಂದಿನ ಭೇಟಿ", "ಮುಂದಿನ ವಿಸಿಟ್")]
ANCHORS += [("id", p, False) for p in (
    r"\bbeneficiary\s+(id|number|no)\b", r"\bid\b", r"\bi\.d\.?", r"\baidi\b", "आईडी", "ಐಡಿ")]
ANCHORS += [("name", p, False) for p in (r"\bname\b", r"\bnaam\b", "नाम", "ಹೆಸರು")]
ANCHORS += [("notes", p, False) for p in (r"\bnotes?\b", r"\bremarks?\b", "नोट", "टिप्पणी", "ಟಿಪ್ಪಣಿ")]

SENTENCE_END = re.compile(r"[.;!?\n।]")


@dataclass
class Anchor:
    field: str
    start: int
    end: int
    weak: bool

    @property
    def group(self) -> str:
        return "vacc" if self.field.startswith("vacc") else self.field


def find_anchors(text: str) -> list[Anchor]:
    found = []
    for fld, pat, weak in ANCHORS:
        for m in re.finditer(pat, text):
            found.append(Anchor(fld, m.start(), m.end(), weak))
    found.sort(key=lambda a: (a.start, -a.end))
    kept: list[Anchor] = []
    for a in found:
        if kept and a.start < kept[-1].end:          # overlapping -> keep first/longest
            continue
        if a.weak and kept and a.group != kept[-1].group and 0 <= a.start - kept[-1].end <= 12:
            continue                                  # absorbed into previous field
        kept.append(a)
    return kept


def segments(text: str) -> dict[str, list[str]]:
    """field-group -> list of text segments that follow each anchor."""
    anchors = find_anchors(text)
    out: dict[str, list[str]] = {}
    for i, a in enumerate(anchors):
        stop = len(text)
        if a.group != "notes":
            for b in anchors[i + 1:]:
                if b.group != a.group:
                    stop = b.start
                    break
        seg = text[a.end:stop]
        cut = SENTENCE_END.search(seg)
        if cut:
            seg = seg[:cut.start()]
        out.setdefault(a.group, []).append(seg)
        if a.group == "vacc" and ":" in a.field:
            out.setdefault("vacc_names", []).append(a.field.split(":", 1)[1])
    return out


# ---------------------------------------------------------------------------
# Status words
# ---------------------------------------------------------------------------
_NOT_DONE = (
    r"\bnot\s+(done|given|taken|taking|completed?|received|yet)\b", r"\bno\s+t\w+\s+yet\b",
    r"\b(nahi|nahin)\s+(hu|hui|hua|diya|di|li|le|kha|lag|lagi|lagwa)\w*",
    r"\b(hua|hui|diya|di|li|le\s+rahi|kha\s+rahi|lag[aei]?)\s+(nahi|nahin)\b",
    r"\bstopped\b", r"\bnot\s+eating\b", "नहीं", "ಲ್ಲ",
)
_MISSED = (r"\bmissed\b", r"\bskipped\b", r"\bchhoot\w*", "छूट", "ತಪ್ಪಿ")
_TAKING = (r"\btaking\b", r"\b(le|kha)\s+rahi\b", "ले रही", "खा रही", "ತೆಗೆದುಕೊಳ್ಳುತ್ತಿದ್ದಾರೆ", "ತಿನ್ನುತ್ತಿದ್ದಾರೆ")
_DUE = (r"\bdue\b", r"\bpending\b", r"\bbaa?ki\b", r"\bremaining\b", r"\bto\s+be\s+given\b", r"\blagna\s+hai\b",
        "बाकी", "बाक़ी", "ಬಾಕಿ", "ಹಾಕಬೇಕು")
_DONE = (
    r"\b(done|given|completed?|taken|received|finished|over)\b", r"\bho\s+gay[ai]\b", r"\blag\s+gay[ai]\b",
    r"\b(diya|di|de\s+di|di\s+gayi|lagwa\w*|li)\b", "हो गया", "हो गई", "हो गयी", "लग गया", "लग गई", "दिया",
    r"(^|\s)दी(\s|$)", "दे दी", "ಆಗಿದೆ", "ಕೊಡಲಾಗಿದೆ", "ಕೊಟ್ಟಿದ್ದೇನೆ", "ಕೊಟ್ಟಿದೆ", "ಹಾಕಲಾಗಿದೆ", "ಮುಗಿದಿದೆ",
)


def _has(patterns, text) -> bool:
    return any(re.search(p, text) for p in patterns)


def detect_status(seg: str) -> str | None:
    if _has(_MISSED, seg):
        return "missed"
    if _has(_NOT_DONE, seg):
        return "not_done"
    if _has(_TAKING, seg):
        return "taking"
    if _has(_DUE, seg):
        return "due"
    if _has(_DONE, seg):
        return "done"
    return None


STATUS_MAP = {
    "anc": {"done": "done", "taking": "done", "due": "pending", "not_done": "missed", "missed": "missed"},
    "ifa": {"done": "given", "taking": "taking", "due": "due", "not_done": "not_taking", "missed": "not_taking"},
    "tt": {"done": "given", "taking": "given", "due": "due", "not_done": "not_given", "missed": "not_given"},
}

# ---------------------------------------------------------------------------
# Visit type
# ---------------------------------------------------------------------------
VISIT_TYPES = {
    "HBNC": (r"\bhbnc\b", r"\bnew\s?born\b", r"\bnavjaat\b", r"\bhome\s+based\s+newborn\b", "नवजात", "ನವಜಾತ"),
    "PNC": (r"\bpnc\b", r"\bpost\s?natal\b", r"\bpost\s?partum\b", r"\bafter\s+delivery\b", r"\bdelivery\s+ke\s+baad\b",
            "प्रसव के बाद", "डिलीवरी के बाद", "ಹೆರಿಗೆ ನಂತರ", "ಹೆರಿಗೆಯ ನಂತರ"),
    "ANC": (r"\banc\b", r"\bante\s?natal\b", r"\bpregnan\w*", r"\bgarbhvati\b", r"\bgarbhini\b", "गर्भवती", "ಗರ್ಭಿಣಿ"),
    "IMMUNIZATION": (r"\bimmuni[sz]ation\s+visit\b", r"\bvaccination\s+visit\b", r"\bteekakaran\b", "टीकाकरण", "ಲಸಿಕೆ ಭೇಟಿ"),
}


def detect_visit_type(text: str) -> str | None:
    best = None
    for vt, pats in VISIT_TYPES.items():
        for p in pats:
            m = re.search(p, text)
            if m and (best is None or m.start() < best[1]):
                best = (vt, m.start())
    return best[0] if best else None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
WEEKDAYS = [
    ("monday", "somvar", "सोमवार", "ಸೋಮವಾರ"), ("tuesday", "mangalvar", "मंगलवार", "ಮಂಗಳವಾರ"),
    ("wednesday", "budhvar", "बुधवार", "ಬುಧವಾರ"), ("thursday", "guruvar", "गुरुवार", "ಗುರುವಾರ"),
    ("friday", "shukravar", "शुक्रवार", "ಶುಕ್ರವಾರ"), ("saturday", "shanivar", "शनिवार", "ಶನಿವಾರ"),
    ("sunday", "ravivar", "रविवार", "ಭಾನುವಾರ"),
]
MONTHS = [
    ("jan", "जनवरी", "ಜನವರಿ"), ("feb", "फरवरी", "ಫೆಬ್ರವರಿ"), ("mar", "मार्च", "ಮಾರ್ಚ್"), ("apr", "अप्रैल", "ಏಪ್ರಿಲ್"),
    ("may", "मई", "ಮೇ"), ("jun", "जून", "ಜೂನ್"), ("jul", "जुलाई", "ಜುಲೈ"), ("aug", "अगस्त", "ಆಗಸ್ಟ್"),
    ("sep", "सितंबर", "ಸೆಪ್ಟೆಂಬರ್"), ("oct", "अक्टूबर", "ಅಕ್ಟೋಬರ್"), ("nov", "नवंबर", "ನವೆಂಬರ್"), ("dec", "दिसंबर", "ಡಿಸೆಂಬರ್"),
]


def _month_index(word: str) -> int | None:
    word = word.replace("फ़", "फ").replace("म्ब", "मब").replace("सितम्बर", "सितंबर")
    for i, names in enumerate(MONTHS):
        if word.startswith(names[0]) or word in names[1:]:
            return i + 1
    if word in ("नवम्बर",):
        return 11
    if word in ("दिसम्बर",):
        return 12
    return None


def _future(d: date, ref: date) -> date:
    return d.replace(year=d.year + 1) if d < ref else d


def parse_date(text: str, ref: date) -> str | None:
    t = text.strip().lower()
    if not t:
        return None
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        try:
            y = int(m[3]) if m[3] else ref.year
            y = y + 2000 if y < 100 else y
            d = date(y, int(m[2]), int(m[1]))
            return (d if m[3] else _future(d, ref)).isoformat()
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([^\s\d,.]+)", t) or None
    if m and _month_index(m[2]):
        try:
            return _future(date(ref.year, _month_index(m[2]), int(m[1])), ref).isoformat()
        except ValueError:
            return None
    m = re.search(r"([a-z]{3,})\s+(\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m and _month_index(m[1]):
        try:
            return _future(date(ref.year, _month_index(m[1]), int(m[2])), ref).isoformat()
        except ValueError:
            return None
    if re.search(r"\bday\s+after\s+tomorrow\b|\bparso\w*|परसों|ನಾಡಿದ್ದು", t):
        return (ref + timedelta(days=2)).isoformat()
    if re.search(r"\btomorrow\b|\bkal\b|कल|\bnaale\b|ನಾಳೆ", t):
        return (ref + timedelta(days=1)).isoformat()
    m = re.search(r"(\d{1,3})\s*(days?|din|दिन|ದಿನ)", t)
    if m:
        return (ref + timedelta(days=int(m[1]))).isoformat()
    m = re.search(r"(\d{1,2})\s*(weeks?|hafte|हफ्ते|हफ़्ते|ವಾರ)", t)
    if m:
        return (ref + timedelta(weeks=int(m[1]))).isoformat()
    if re.search(r"\bnext\s+week\b|\bagle\s+hafte\b|अगले हफ्ते|अगले हफ़्ते|ಮುಂದಿನ ವಾರ", t):
        return (ref + timedelta(days=7)).isoformat()
    for idx, names in enumerate(WEEKDAYS):
        if any(re.search(r"\b" + n + r"\b", t) if n.isascii() else n in t for n in names):
            ahead = (idx - ref.weekday()) % 7 or 7
            return (ref + timedelta(days=ahead)).isoformat()
    return None


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------
NAME_STOP = {
    "weight", "id", "visit", "age", "and", "her", "his", "is", "hai", "aur", "beneficiary", "next", "anc",
    "ifa", "tt", "the", "of", "ka", "ki", "ke", "है", "और", "का", "की", "ಇದೆ", "ಮತ್ತು", "wajan", "vajan",
}
WEIGHT_UNIT = r"(kg|kgs|kilo\w*|किलो|ಕೆಜಿ|ಕಿಲೋ|ಕೆ\.ಜಿ)"


def extract_fields(raw_text: str, ref: date | None = None) -> tuple[dict, set]:
    """Returns (fields_found, unclear_field_names). Only fields actually heard are returned."""
    ref = ref or date.today()
    text = words_to_numbers(normalize(raw_text))
    segs = segments(text)
    f: dict = {}
    unclear: set = set()

    # Beneficiary ID
    m = re.search(r"(?:\bbeneficiary\s+(?:id|number|no)\b|\bid\b|\bi\.d\.?|\baidi\b|आईडी|ಐಡಿ)\s*(?:number|no\.?|is|hai|है|:|-)?\s*([a-z]{0,2}\s?-?\s?\d{2,6})\b", text)
    if m:
        f["beneficiary_id"] = re.sub(r"[\s-]", "", m.group(1)).upper()
    elif "id" in segs:
        unclear.add("beneficiary_id")

    # Name (synthetic demo names only)
    for seg in segs.get("name", []):
        seg = re.sub(r"^\s*(is|hai|:|-)\s*", "", seg)
        words = []
        for w in seg.split():
            w = w.strip(",:")
            if not w or w in NAME_STOP or any(c.isdigit() for c in w):
                break
            words.append(w)
            if len(words) == 3:
                break
        if words:
            f["beneficiary_name"] = " ".join(w.capitalize() if w.isascii() else w for w in words)
            break

    # Visit type
    m = re.search(r"\bvisit\s+type\s+(?:is\s+)?(\w+)", text)
    vt = detect_visit_type(m.group(1)) if m else None
    vt = vt or detect_visit_type(text)
    if vt:
        f["visit_type"] = vt

    # Weight
    m = re.search(r"(\d+(?:\.\d+)?)\s*" + WEIGHT_UNIT, text)
    weight = None
    if m:
        weight = float(m.group(1))
    else:
        m = re.search(r"(\d{3,4})\s*(g|grams?|ग्राम|ಗ್ರಾಂ)\b", text)
        if m:
            weight = int(m.group(1)) / 1000
        else:
            for seg in segs.get("weight", []):
                m = re.search(r"(\d+(?:\.\d+)?)", seg)
                if m:
                    weight = float(m.group(1))
                    break
    if weight is not None:
        if 0.5 <= weight <= 150:
            f["weight_kg"] = round(weight, 2)
        else:
            unclear.add("weight_kg")
    elif "weight" in segs:
        unclear.add("weight_kg")

    # ANC / IFA / TT
    for key, field_name in (("anc", "anc_status"), ("ifa", "ifa_status"), ("tt", "tt_status")):
        status = None
        for seg in segs.get(key, []):
            status = detect_status(seg) or status
        if status:
            f[field_name] = STATUS_MAP[key][status]
        elif key in ("ifa", "tt") and key in segs:
            unclear.add(field_name)
    m = re.search(r"(\d+)\s*(tablets?|goli|गोली|ಮಾತ್ರೆ)", text)
    if m and "ifa_status" in f:
        f["ifa_tablets"] = int(m.group(1))

    # Vaccinations
    if "vacc" in segs:
        names = list(dict.fromkeys(segs.get("vacc_names", [])))
        status = detect_status(" ".join(segs["vacc"]))
        if names:
            if status in ("done",):
                f["vaccinations_given"] = names
                f["vaccination_status"] = "completed"
            elif status in ("due", "not_done", "missed") or status is None:
                f["vaccinations_due"] = names
                f["vaccination_status"] = "due"
        elif status == "done":
            f["vaccination_status"] = "completed"
            f["vaccinations_due"] = []
        elif status in ("due", "not_done", "missed"):
            f["vaccination_status"] = "due"
            unclear.add("vaccinations_due")   # which vaccines? ask

    # Next visit date
    if "next" in segs:
        found = None
        for seg in segs["next"]:
            found = parse_date(seg, ref)
            if found:
                break
        if not found:
            # date said before the phrase, e.g. "Monday ko next visit"
            idx = min(a.start for a in find_anchors(text) if a.group == "next")
            found = parse_date(text[max(0, idx - 25):idx], ref)
        if found:
            f["next_visit_date"] = found
        else:
            unclear.add("next_visit_date")

    # Notes
    notes = [s.strip(" :-,") for s in segs.get("notes", []) if s.strip(" :-,")]
    if notes:
        f["notes"] = "; ".join(notes)

    return f, unclear


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def required_fields(record: dict) -> list[str]:
    req = ["beneficiary_id", "visit_type"]
    vt = record.get("visit_type")
    if vt == "ANC":
        req += ["anc_status", "ifa_status", "tt_status"]
    if vt in ("HBNC", "IMMUNIZATION"):
        req += ["weight_kg"]
    if vt == "IMMUNIZATION":
        req += ["vaccination_status"]
    req += ["next_visit_date"]
    return req


def missing_fields(record: dict) -> list[str]:
    return [f for f in required_fields(record) if record.get(f) in (None, "")]


# ---------------------------------------------------------------------------
# Confirmation words
# ---------------------------------------------------------------------------
_YES = (r"\b(yes|yeah|yep|correct|right|confirm\w*|save|ok|okay|haan|haa|han|haanji|hanji|sahi|theek|thik|howdu|houdu|sari)\b",
        "हाँ", "हां", "सही", "ठीक", "ಹೌದು", "ಸರಿ")
_NO = (r"\b(no|nope|wrong|incorrect|galat|nahi|nahin|illa|tappu)\b", "नहीं", "गलत", "ಇಲ್ಲ", "ತಪ್ಪು")
_CANCEL = (r"\b(cancel|discard|radd)\b", "रद्द", "ರದ್ದು")


def classify_reply(text: str) -> str:
    t = normalize(text)
    if _has(_CANCEL, t):
        return "cancel"
    yes, no = _has(_YES, t), _has(_NO, t)
    if yes and not no:
        return "yes"
    if no and not yes:
        return "no"
    return "unclear"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
class VisitSession:
    def __init__(self, language: str = L.DEFAULT_LANGUAGE, reference_date: date | None = None,
                 session_id: str | None = None, beneficiary_lookup=None):
        self.session_id = session_id or uuid.uuid4().hex
        self.beneficiary_lookup = beneficiary_lookup   # function(id) -> dict | None
        self.warnings: list[str] = []
        self.unknown_id = False
        self.language = L.normalize_language(language)
        self.reference_date = reference_date or date.today()
        self.record: dict = {}
        self.unclear: set = set()
        self.transcripts: list[dict] = []
        self.corrections: list[dict] = []
        self.danger = DangerAssessment()
        self.state = STATE_COLLECTING
        self.created_at = datetime.now().isoformat(timespec="seconds")

    # -- helpers ------------------------------------------------------------
    def _m(self, key, **kw):
        return L.msg(self.language, key, **kw)

    def _merge(self, fields: dict, unclear: set, utterance: str, as_correction: bool):
        for k, v in fields.items():
            old = self.record.get(k)
            if old == v:
                continue
            if old not in (None, "", []) or as_correction:
                self.corrections.append({
                    "field": k, "old": old, "new": v, "utterance": utterance,
                    "at": datetime.now().isoformat(timespec="seconds"),
                })
            self.record[k] = v
        self.unclear = (self.unclear - set(fields)) | (unclear - set(fields))
        if "beneficiary_id" in fields:
            self._lookup_beneficiary()

    def _lookup_beneficiary(self):
        """Fill the name from the (synthetic) register; warn if the ID is unknown."""
        self.warnings = [w for w in self.warnings if not w.startswith("Beneficiary ID")]
        self.unknown_id = False
        bid = self.record.get("beneficiary_id")
        if not bid or not self.beneficiary_lookup:
            return
        found = self.beneficiary_lookup(bid)
        if found:
            self.record["beneficiary_id"] = found["beneficiary_id"]
            if not self.record.get("beneficiary_name"):
                self.record["beneficiary_name"] = found["name"]
        else:
            self.unknown_id = True
            self.warnings.append(f"Beneficiary ID {bid} is not in the demo register - please check the ID.")

    # -- button actions (same rules as voice) -------------------------------
    def confirm(self) -> dict:
        if self.state != STATE_AWAITING or missing_fields(self.record) or self.unclear:
            raise ValueError("The record is not complete yet, so it cannot be confirmed.")
        self.state = STATE_CONFIRMED
        return self.response(speak=[], action="save")

    def cancel(self) -> dict:
        if self.state == STATE_CONFIRMED:
            raise ValueError("This record is already confirmed.")
        self.state = STATE_CANCELLED
        return self.response(speak=[self._m("cancelled")])

    def set_language(self, language: str) -> dict:
        self.language = L.normalize_language(language)
        if self.state == STATE_AWAITING:
            return self.response(speak=self._summary_prompt())
        return self.response(speak=[self._m("start")])

    def _danger_speech(self, assessment: DangerAssessment) -> tuple[str | None, list[str]]:
        """Returns (urgent alert text or None, other danger-related sentences)."""
        alert, extra = None, []
        dangers = [m.rule_id for m in assessment.by_level(LEVEL_DANGER)]
        if dangers:
            alert = self._m("referral", signs=L.sign_names(self.language, dangers))
        clar = [m.rule_id for m in assessment.by_level(LEVEL_CLARIFY)]
        if clar:
            extra.append(self._m("clarify_danger", signs=L.sign_names(self.language, clar)))
        return alert, extra

    def _summary_prompt(self) -> list[str]:
        missing = missing_fields(self.record)
        parts = []
        if self.unclear:
            parts.append(self._m("ask_unclear", fields=", ".join(L.label(self.language, f) for f in sorted(self.unclear))))
        if missing:
            parts.append(self._m("ask_missing", fields=", ".join(L.label(self.language, f) for f in missing)))
        if missing or self.unclear:
            self.state = STATE_COLLECTING
            return parts
        self.state = STATE_AWAITING
        parts.append(L.build_readback(self.language, self.record))
        if self.unknown_id:
            parts.append(self._m("unknown_id", id=self.record.get("beneficiary_id")))
        neg = [m.rule_id for m in self.danger.by_level(LEVEL_NEGATED)]
        if neg:
            parts.append(self._m("absent_signs", signs=L.sign_names(self.language, neg)))
        clar = [m.rule_id for m in self.danger.by_level(LEVEL_CLARIFY)]
        if clar:
            parts.append(self._m("clarify_danger", signs=L.sign_names(self.language, clar)))
        parts.append(self._m("confirm_question"))
        return parts

    # -- main entry ---------------------------------------------------------
    def handle_utterance(self, text: str) -> dict:
        text = (text or "").strip()
        if self.state in (STATE_CONFIRMED, STATE_CANCELLED):
            raise ValueError("This visit session is already finished. Start a new visit.")
        if not text:
            return self.response(speak=[self._m("not_understood")])

        previous = " ".join(t["text"] for t in self.transcripts)
        self.transcripts.append({"text": text, "at": datetime.now().isoformat(timespec="seconds"), "state": self.state})

        fields, unclear = extract_fields(text, self.reference_date)
        vt = fields.get("visit_type") or self.record.get("visit_type")
        new_danger = detect_danger_signs(text, visit_type=vt, extra_context=previous)
        self.danger = merge_assessments(self.danger, new_danger)
        alert, danger_extra = self._danger_speech(new_danger)
        speak: list[str] = []

        if self.state == STATE_AWAITING and not fields and not unclear and not new_danger.matches:
            kind = classify_reply(text)
            if kind == "yes":
                self.state = STATE_CONFIRMED
                return self.response(speak=[], alert=alert, action="save")
            if kind == "cancel":
                self.state = STATE_CANCELLED
                return self.response(speak=[self._m("cancelled")], alert=alert)
            if kind == "no":
                return self.response(speak=[self._m("what_to_change")], alert=alert)
            return self.response(speak=[self._m("not_understood"), self._m("confirm_question")], alert=alert)

        is_correction = self.state == STATE_AWAITING
        if not fields and not unclear and not new_danger.matches:
            return self.response(speak=[self._m("not_understood")] + self._summary_prompt(), alert=alert)

        self._merge(fields, unclear, text, as_correction=is_correction)
        if is_correction and fields:
            speak.append(self._m("correction_applied"))
        if self.state == STATE_COLLECTING:
            speak += [s for s in danger_extra]
        speak += self._summary_prompt()
        return self.response(speak=list(dict.fromkeys(speak)), alert=alert)

    def response(self, speak: list[str], alert: str | None = None, action: str | None = None) -> dict:
        return {
            "session_id": self.session_id,
            "language": self.language,
            "created_at": self.created_at,
            "state": self.state,
            "record": dict(self.record),
            "missing_fields": missing_fields(self.record),
            "unclear_fields": sorted(self.unclear),
            "danger": self.danger.to_dict(),
            "alert_text": alert,                       # speak FIRST, immediately
            "speak_text": " ".join(s for s in speak if s),
            "action": action,                          # "save" when worker confirmed
            "corrections": list(self.corrections),
            "warnings": list(self.warnings),
            "transcripts": list(self.transcripts),
        }

    def snapshot(self) -> dict:
        return self.response(speak=[])
