"""SQLite storage. Only SYNTHETIC demo data. No audio and no API keys are stored.

Tables
    beneficiaries   - synthetic demo households/beneficiaries
    visits          - CONFIRMED visit records only (drafts are never saved here)
    followups       - follow-up tasks (next visit, PHC referral check, supervisor review)
    danger_alerts   - every danger / clarify / absent sign with phrase + reason
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS beneficiaries (
    beneficiary_id TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,          -- pregnant_woman | mother | newborn | child
    village        TEXT,
    notes          TEXT,
    is_synthetic   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS visits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_request_id   TEXT NOT NULL UNIQUE,      -- prevents duplicate saves
    session_id          TEXT NOT NULL,
    beneficiary_id      TEXT NOT NULL,
    beneficiary_name    TEXT,
    visit_type          TEXT NOT NULL,
    weight_kg           REAL,
    vaccinations_due    TEXT,                       -- JSON list
    vaccinations_given  TEXT,                       -- JSON list
    vaccination_status  TEXT,
    anc_status          TEXT,
    ifa_status          TEXT,
    ifa_tablets         INTEGER,
    tt_status           TEXT,
    next_visit_date     TEXT,
    notes               TEXT,
    language            TEXT NOT NULL,
    danger_level        TEXT NOT NULL,              -- danger | clarify | none
    urgent_referral     INTEGER NOT NULL DEFAULT 0,
    needs_human_review  INTEGER NOT NULL DEFAULT 0,
    transcript          TEXT NOT NULL,              -- JSON list of utterances (text only)
    correction_history  TEXT NOT NULL,              -- JSON list
    record_status       TEXT NOT NULL DEFAULT 'confirmed',
    created_at          TEXT NOT NULL,
    confirmed_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id        INTEGER NOT NULL REFERENCES visits(id),
    beneficiary_id  TEXT NOT NULL,
    due_date        TEXT NOT NULL,
    reason          TEXT NOT NULL,
    priority        TEXT NOT NULL,                 -- urgent | high | normal
    status          TEXT NOT NULL DEFAULT 'open',  -- open | done
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS danger_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id            INTEGER NOT NULL REFERENCES visits(id),
    rule_id             TEXT NOT NULL,
    sign_name           TEXT NOT NULL,
    level               TEXT NOT NULL,             -- danger | clarify | negated
    detected_phrase     TEXT NOT NULL,
    reason              TEXT NOT NULL,
    note                TEXT,
    sources             TEXT NOT NULL,             -- JSON list
    needs_human_review  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visits_beneficiary ON visits(beneficiary_id);
CREATE INDEX IF NOT EXISTS idx_followups_status ON followups(status, due_date);
"""

# Synthetic demo beneficiaries (NOT real people).
DEMO_BENEFICIARIES = [
    ("B101", "Sunita Devi (demo)", "pregnant_woman", "Rampur (demo)", "6 months pregnant - synthetic"),
    ("B102", "Kavita Kumari (demo)", "pregnant_woman", "Rampur (demo)", "8 months pregnant - synthetic"),
    ("B201", "Baby of Meena (demo)", "newborn", "Sitapur (demo)", "Born 10 days ago - synthetic"),
    ("B205", "Baby of Lakshmi (demo)", "newborn", "Sitapur (demo)", "Born 5 days ago - synthetic"),
    ("B301", "Meena Bai (demo)", "mother", "Sitapur (demo)", "Delivered 10 days ago - synthetic"),
    ("B303", "Shobha (demo)", "pregnant_woman", "Hosahalli (demo)", "5 months pregnant - synthetic"),
    ("B401", "Ravi (demo)", "child", "Hosahalli (demo)", "9 months old - synthetic"),
]

_db_path: Path = DATABASE_PATH


def set_database_path(path: Path | str) -> None:
    """Used by tests to point at a temporary database."""
    global _db_path
    _db_path = Path(path)


@contextmanager
def connect():
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO beneficiaries (beneficiary_id, name, category, village, notes) VALUES (?,?,?,?,?)",
            DEMO_BENEFICIARIES,
        )


def health_check() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Beneficiaries
# ---------------------------------------------------------------------------
def get_beneficiary(beneficiary_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM beneficiaries WHERE beneficiary_id = ?", (beneficiary_id,)).fetchone()
        if row is None and beneficiary_id.isdigit():
            row = conn.execute("SELECT * FROM beneficiaries WHERE beneficiary_id = ?", ("B" + beneficiary_id,)).fetchone()
    return dict(row) if row else None


def list_beneficiaries() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM beneficiaries ORDER BY beneficiary_id")]


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------
class SaveError(ValueError):
    pass


def save_confirmed_visit(session: dict, client_request_id: str, confirmed: bool) -> dict:
    """Save a visit. `session` is VisitSession.snapshot().

    Refuses to save unless the worker explicitly confirmed and no required field is missing.
    Calling twice with the same client_request_id returns the first saved visit (no duplicate).
    """
    if not confirmed or session.get("state") != "confirmed":
        raise SaveError("Record not confirmed by the worker - not saved.")
    if session.get("missing_fields"):
        raise SaveError(f"Missing required fields: {session['missing_fields']}")
    if not client_request_id or len(client_request_id) > 100:
        raise SaveError("Invalid client_request_id.")

    rec = session["record"]
    danger = session["danger"]
    with connect() as conn:
        existing = conn.execute("SELECT id FROM visits WHERE client_request_id = ?", (client_request_id,)).fetchone()
        if existing:
            return {"visit_id": existing["id"], "duplicate": True}

        now = _now()
        cur = conn.execute(
            """INSERT INTO visits (client_request_id, session_id, beneficiary_id, beneficiary_name, visit_type,
                weight_kg, vaccinations_due, vaccinations_given, vaccination_status, anc_status, ifa_status,
                ifa_tablets, tt_status, next_visit_date, notes, language, danger_level, urgent_referral,
                needs_human_review, transcript, correction_history, record_status, created_at, confirmed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                client_request_id, session["session_id"], rec["beneficiary_id"], rec.get("beneficiary_name"),
                rec["visit_type"], rec.get("weight_kg"), json.dumps(rec.get("vaccinations_due") or []),
                json.dumps(rec.get("vaccinations_given") or []), rec.get("vaccination_status"),
                rec.get("anc_status"), rec.get("ifa_status"), rec.get("ifa_tablets"), rec.get("tt_status"),
                rec.get("next_visit_date"), rec.get("notes"), session["language"], danger["level"],
                int(danger["urgent_referral"]), int(danger["needs_human_review"]),
                json.dumps(session.get("transcripts", []), ensure_ascii=False),
                json.dumps(session.get("corrections", []), ensure_ascii=False),
                "urgent_referral" if danger["urgent_referral"] else "confirmed",
                session.get("created_at", now), now,
            ),
        )
        visit_id = cur.lastrowid

        for m in danger["matches"]:
            conn.execute(
                """INSERT INTO danger_alerts (visit_id, rule_id, sign_name, level, detected_phrase, reason, note,
                   sources, needs_human_review, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (visit_id, m["rule_id"], m["name"], m["level"], m["phrase"], m["reason"], m.get("note", ""),
                 json.dumps(m["sources"]), int(m["needs_human_review"]), now),
            )

        today = date.today().isoformat()
        bid = rec["beneficiary_id"]
        if danger["urgent_referral"]:
            signs = ", ".join(sorted({m["name"] for m in danger["matches"] if m["level"] == "danger"}))
            conn.execute(
                "INSERT INTO followups (visit_id, beneficiary_id, due_date, reason, priority, created_at) VALUES (?,?,?,?,?,?)",
                (visit_id, bid, today, f"URGENT PHC referral - confirm beneficiary reached PHC ({signs})", "urgent", now),
            )
        if danger["needs_human_review"]:
            conn.execute(
                "INSERT INTO followups (visit_id, beneficiary_id, due_date, reason, priority, created_at) VALUES (?,?,?,?,?,?)",
                (visit_id, bid, today, "Supervisor/ANM review of possible danger sign", "high", now),
            )
        if rec.get("next_visit_date"):
            reason = "Next scheduled visit"
            if rec.get("vaccinations_due"):
                reason += " - vaccinations due: " + ", ".join(rec["vaccinations_due"])
            conn.execute(
                "INSERT INTO followups (visit_id, beneficiary_id, due_date, reason, priority, created_at) VALUES (?,?,?,?,?,?)",
                (visit_id, bid, rec["next_visit_date"], reason, "normal", now),
            )
    return {"visit_id": visit_id, "duplicate": False}


def _visit_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("vaccinations_due", "vaccinations_given", "transcript", "correction_history"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    d["urgent_referral"] = bool(d["urgent_referral"])
    d["needs_human_review"] = bool(d["needs_human_review"])
    return d


def list_visits(search: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    sql = "SELECT * FROM visits"
    params: list = []
    if search:
        like = f"%{search.strip()}%"
        sql += " WHERE beneficiary_id LIKE ? OR beneficiary_name LIKE ? OR visit_type LIKE ? OR notes LIKE ?"
        params = [like, like, like, like]
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        return [_visit_row(r) for r in conn.execute(sql, params)]


def get_visit(visit_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if not row:
            return None
        visit = _visit_row(row)
        visit["alerts"] = [dict(a) | {"sources": json.loads(a["sources"])}
                           for a in conn.execute("SELECT * FROM danger_alerts WHERE visit_id = ?", (visit_id,))]
        visit["followups"] = [dict(f) for f in conn.execute("SELECT * FROM followups WHERE visit_id = ?", (visit_id,))]
    return visit


def list_followups(status: str = "open") -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT f.*, v.beneficiary_name, v.visit_type FROM followups f JOIN visits v ON v.id = f.visit_id
               WHERE f.status = ?
               ORDER BY CASE f.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, f.due_date""",
            (status,),
        )
        return [dict(r) for r in rows]


def complete_followup(followup_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE followups SET status = 'done', completed_at = ? WHERE id = ? AND status = 'open'",
            (_now(), followup_id),
        )
        return cur.rowcount == 1
