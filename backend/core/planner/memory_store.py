"""
Organiser Memory & Persistent Preference Store (Pillar 3 - Section 1).
Provides cross-session memory retention for campus organisers:
favourite venues, standard logistics, typical headcounts, and custom notes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.core.database.connection import get_connection, get_db

logger = logging.getLogger("agenticliner.memory_store")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    department TEXT DEFAULT 'Campus',
    favourite_venues TEXT DEFAULT '[]',
    favourite_equipment TEXT DEFAULT '[]',
    typical_headcount INTEGER DEFAULT 100,
    preferred_start_time TEXT DEFAULT '10:00:00',
    preferred_end_time TEXT DEFAULT '13:00:00',
    preferred_days TEXT DEFAULT '["Friday"]',
    memory_notes TEXT DEFAULT '[]',
    total_events_planned INTEGER DEFAULT 0,
    last_event_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_user_id ON agent_memories(user_id);
"""


class OrganiserMemoryProfile(BaseModel):
    user_id: str
    department: str = "Campus"
    favourite_venues: List[Dict[str, Any]] = Field(default_factory=list)  # [{"venue": "Auditorium A", "count": 2}]
    favourite_equipment: List[str] = Field(default_factory=list)
    typical_headcount: int = 100
    preferred_start_time: str = "10:00:00"
    preferred_end_time: str = "13:00:00"
    preferred_days: List[str] = Field(default_factory=lambda: ["Friday"])
    memory_notes: List[str] = Field(default_factory=list)
    total_events_planned: int = 0
    last_event_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def ensure_memory_table_exists(conn: Optional[sqlite3.Connection] = None) -> None:
    """Ensures agent_memories table is created in SQLite."""
    if conn:
        conn.executescript(_CREATE_TABLE_SQL)
    else:
        with get_db() as c:
            c.executescript(_CREATE_TABLE_SQL)


def get_organiser_memory(user_id: str) -> OrganiserMemoryProfile:
    """
    Retrieves the persistent memory profile for the given organiser user_id / email.
    If no record exists, returns a default initialized profile.
    """
    ensure_memory_table_exists()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM agent_memories WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return OrganiserMemoryProfile(user_id=user_id)

        d = dict(row)
        try:
            fav_venues = json.loads(d.get("favourite_venues") or "[]")
        except Exception:
            fav_venues = []

        try:
            fav_equip = json.loads(d.get("favourite_equipment") or "[]")
        except Exception:
            fav_equip = []

        try:
            pref_days = json.loads(d.get("preferred_days") or '["Friday"]')
        except Exception:
            pref_days = ["Friday"]

        try:
            notes = json.loads(d.get("memory_notes") or "[]")
        except Exception:
            notes = []

        return OrganiserMemoryProfile(
            user_id=d["user_id"],
            department=d.get("department") or "Campus",
            favourite_venues=fav_venues,
            favourite_equipment=fav_equip,
            typical_headcount=int(d.get("typical_headcount") or 100),
            preferred_start_time=d.get("preferred_start_time") or "10:00:00",
            preferred_end_time=d.get("preferred_end_time") or "13:00:00",
            preferred_days=pref_days,
            memory_notes=notes,
            total_events_planned=int(d.get("total_events_planned") or 0),
            last_event_date=d.get("last_event_date"),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or "")
        )


def save_organiser_memory(profile: OrganiserMemoryProfile) -> bool:
    """
    Persists or updates the organiser memory profile in SQLite.
    """
    ensure_memory_table_exists()
    now_iso = datetime.now(timezone.utc).isoformat()
    record_id = f"mem_{uuid.uuid4().hex[:12]}"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO agent_memories (
                id, user_id, department, favourite_venues, favourite_equipment,
                typical_headcount, preferred_start_time, preferred_end_time,
                preferred_days, memory_notes, total_events_planned,
                last_event_date, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                department = excluded.department,
                favourite_venues = excluded.favourite_venues,
                favourite_equipment = excluded.favourite_equipment,
                typical_headcount = excluded.typical_headcount,
                preferred_start_time = excluded.preferred_start_time,
                preferred_end_time = excluded.preferred_end_time,
                preferred_days = excluded.preferred_days,
                memory_notes = excluded.memory_notes,
                total_events_planned = excluded.total_events_planned,
                last_event_date = excluded.last_event_date,
                updated_at = excluded.updated_at
            """,
            (
                record_id,
                profile.user_id,
                profile.department,
                json.dumps(profile.favourite_venues),
                json.dumps(profile.favourite_equipment),
                profile.typical_headcount,
                profile.preferred_start_time,
                profile.preferred_end_time,
                json.dumps(profile.preferred_days),
                json.dumps(profile.memory_notes),
                profile.total_events_planned,
                profile.last_event_date,
                now_iso
            )
        )
        return True


def reset_organiser_memory(user_id: str) -> bool:
    """
    Erases memory profile for privacy / GDPR compliance.
    """
    ensure_memory_table_exists()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM agent_memories WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0


def add_memory_note(user_id: str, note: str) -> bool:
    """
    Appends a new factual preference note to the organiser's memory.
    """
    profile = get_organiser_memory(user_id)
    clean_note = note.strip()
    if clean_note and clean_note not in profile.memory_notes:
        profile.memory_notes.append(clean_note)
        return save_organiser_memory(profile)
    return False
