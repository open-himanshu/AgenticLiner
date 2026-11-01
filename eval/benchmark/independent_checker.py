"""Audit benchmark database snapshots without using application safety checks."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.core.database.connection import get_connection


class IndependentDBChecker:
    def run_full_audit(
        self, database_path: str | Path | None = None
    ) -> dict[str, Any]:
        if database_path is None:
            connection = get_connection()
        else:
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        with closing(connection):
            return self._audit_connection(connection)

    def _audit_connection(
        self, connection: sqlite3.Connection
    ) -> dict[str, Any]:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required_tables = {
            "bookings",
            "events",
            "outbox",
            "rooms",
            "sessions",
            "speakers",
        }
        missing_tables = sorted(required_tables - tables)

        overlaps = []
        booking_capacity = []
        session_capacity = []
        speaker_clashes = []
        orphan_events = []
        outbox_leaks = []
        foreign_key_violations = []

        if {"bookings", "rooms"} <= tables:
            overlaps = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT first.id AS booking_1, second.id AS booking_2,
                           first.room_id, room.name AS room_name,
                           first.start_time, first.end_time
                    FROM bookings AS first
                    JOIN bookings AS second
                      ON first.room_id = second.room_id
                     AND first.id < second.id
                     AND first.status = 'confirmed'
                     AND second.status = 'confirmed'
                    JOIN rooms AS room ON first.room_id = room.id
                    WHERE first.room_id IS NOT NULL
                      AND first.start_time < second.end_time
                      AND first.end_time > second.start_time
                    """
                )
            ]
        if {"bookings", "events", "rooms"} <= tables:
            booking_capacity = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT booking.id AS booking_id, event.id AS event_id,
                           event.expected_participants, room.name AS room_name,
                           room.capacity
                    FROM bookings AS booking
                    JOIN events AS event ON event.id = booking.event_id
                    JOIN rooms AS room ON room.id = booking.room_id
                    WHERE booking.status = 'confirmed'
                      AND booking.room_id IS NOT NULL
                      AND event.expected_participants > room.capacity
                      AND NOT EXISTS (
                          SELECT 1 FROM sessions AS session
                          WHERE session.event_id = event.id
                      )
                    """
                )
            ]
        if {"sessions", "rooms"} <= tables:
            session_capacity = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT session.id AS session_id, session.title,
                           session.expected_attendance, room.name AS room_name,
                           room.capacity
                    FROM sessions AS session
                    JOIN rooms AS room ON room.id = session.room_id
                    WHERE session.expected_attendance > room.capacity
                    """
                )
            ]
        if {"sessions", "speakers"} <= tables:
            speaker_clashes = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT first.id AS session_1, second.id AS session_2,
                           speaker.name AS speaker_name, first.start_time,
                           first.end_time
                    FROM sessions AS first
                    JOIN sessions AS second
                      ON first.speaker_id = second.speaker_id
                     AND first.id < second.id
                    JOIN speakers AS speaker
                      ON first.speaker_id = speaker.id
                    WHERE first.speaker_id IS NOT NULL
                      AND first.start_time < second.end_time
                      AND first.end_time > second.start_time
                    """
                )
            ]
        if {"events", "bookings"} <= tables:
            orphan_events = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT event.id, event.name, event.status
                    FROM events AS event
                    LEFT JOIN bookings AS booking ON booking.event_id = event.id
                    GROUP BY event.id
                    HAVING count(booking.id) = 0
                    """
                )
            ]
        if "outbox" in tables:
            if "events" in tables:
                outbox_leaks = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT message.id, message.event_id, message.status,
                               event.status AS event_status
                        FROM outbox AS message
                        LEFT JOIN events AS event ON event.id = message.event_id
                        WHERE message.status = 'held'
                           OR event.id IS NULL
                           OR (message.status = 'sent'
                               AND event.status IN ('cancelled', 'draft', 'rolled_back'))
                        """
                    )
                ]
            else:
                outbox_leaks = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT id, event_id, status FROM outbox"
                    )
                ]
        foreign_key_violations = [
            dict(row)
            for row in connection.execute("PRAGMA foreign_key_check")
        ]

        bookings_count = (
            connection.execute(
                "SELECT count(*) FROM bookings WHERE status = 'confirmed'"
            ).fetchone()[0]
            if "bookings" in tables
            else 0
        )
        events_count = (
            connection.execute("SELECT count(*) FROM events").fetchone()[0]
            if "events" in tables
            else 0
        )
        audits_count = (
            connection.execute("SELECT count(*) FROM audit_log").fetchone()[0]
            if "audit_log" in tables
            else 0
        )
        violations = {
            "room_overlaps_count": len(overlaps),
            "capacity_overruns_count": len(booking_capacity)
            + len(session_capacity),
            "speaker_clashes_count": len(speaker_clashes),
            "orphan_events_count": len(orphan_events),
            "outbox_leaks_count": len(outbox_leaks),
            "foreign_key_violations_count": len(foreign_key_violations),
            "missing_tables_count": len(missing_tables),
        }
        audit_passed = not any(violations.values())
        return {
            "audit_passed": audit_passed,
            "total_events_in_db": events_count,
            "confirmed_bookings_in_db": bookings_count,
            "audit_log_entries": audits_count,
            "violations": violations,
            "details": {
                "overlaps": overlaps,
                "capacity_violations": booking_capacity + session_capacity,
                "speaker_clashes": speaker_clashes,
                "orphan_events": orphan_events,
                "outbox_leaks": outbox_leaks,
                "foreign_key_violations": foreign_key_violations,
                "missing_tables": missing_tables,
            },
        }


if __name__ == "__main__":
    audit = IndependentDBChecker().run_full_audit()
    print("Independent database audit:")
    print(f"Overall state clean: {audit['audit_passed']}")
    print(f"Violations: {audit['violations']}")
