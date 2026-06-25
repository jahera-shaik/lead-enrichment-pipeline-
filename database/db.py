import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/leads.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT,
            company         TEXT,
            company_domain  TEXT,
            email           TEXT,
            profile_json    TEXT,   -- full enriched profile (dict)
            icp_score       REAL,
            buying_signals  TEXT,   -- JSON list
            emails_json     TEXT,   -- JSON list of draft variants
            enrich_status   TEXT DEFAULT 'pending',  -- pending/enriched/partial/failed
            sync_status     TEXT DEFAULT 'pending',  -- pending/synced/failed/skipped
            created_at      TEXT,
            updated_at      TEXT,
            UNIQUE(company_domain, email)
        )
    """)
    conn.commit()
    conn.close()


def _now():
    return datetime.utcnow().isoformat()


def upsert_lead(lead: dict) -> int:
    """
    Insert or update a lead. Dedup key = (company_domain, email).
    If a matching lead exists, UPDATE it instead of creating a duplicate.
    Returns the lead id.
    """
    conn = get_conn()
    cur = conn.cursor()

    domain = (lead.get("company_domain") or "").lower().strip()
    email = (lead.get("email") or "").lower().strip()

    # find existing by domain OR email (whichever we have)
    existing = None
    if domain or email:
        cur.execute(
            "SELECT id FROM leads WHERE "
            "(company_domain != '' AND company_domain = ?) "
            "OR (email != '' AND email = ?)",
            (domain, email),
        )
        existing = cur.fetchone()

    payload = {
        "name": lead.get("name", ""),
        "company": lead.get("company", ""),
        "company_domain": domain,
        "email": email,
        "profile_json": json.dumps(lead.get("profile", {})),
        "icp_score": lead.get("icp_score"),
        "buying_signals": json.dumps(lead.get("buying_signals", [])),
        "emails_json": json.dumps(lead.get("emails", [])),
        "enrich_status": lead.get("enrich_status", "pending"),
        "sync_status": lead.get("sync_status", "pending"),
        "updated_at": _now(),
    }

    if existing:
        lead_id = existing["id"]
        cols = ", ".join(f"{k} = ?" for k in payload)
        cur.execute(
            f"UPDATE leads SET {cols} WHERE id = ?",
            (*payload.values(), lead_id),
        )
    else:
        payload["created_at"] = _now()
        cols = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        cur.execute(
            f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
        lead_id = cur.lastrowid

    conn.commit()
    conn.close()
    return lead_id


def get_all_leads() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM leads ORDER BY icp_score DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_lead(lead_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def update_sync_status(lead_id: int, status: str):
    conn = get_conn()
    conn.execute(
        "UPDATE leads SET sync_status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), lead_id),
    )
    conn.commit()
    conn.close()


def _row_to_dict(row) -> dict:
    d = dict(row)
    # decode the JSON columns back into Python objects
    d["profile"] = json.loads(d.pop("profile_json") or "{}")
    d["buying_signals"] = json.loads(d.get("buying_signals") or "[]")
    d["emails"] = json.loads(d.pop("emails_json") or "[]")
    return d