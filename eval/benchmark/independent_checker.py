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
            "resources",
            "rooms",
            "sessions",
            "speakers",
        }
        missing_tables = sorted(required_tables - tables)

        overlaps = []
        booking_capacity = []
        session_capacity = []
        stock_violations = []
        speaker_clashes = []
        orphan_events = []
        outbox_leaks = []
        foreign_key_violations = []

        if "bookings" in tables:
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
                    LEFT JOIN rooms AS room ON first.room_id = room.id
                    WHERE first.room_id IS NOT NULL
                      AND first.start_time < second.end_time
                      AND first.end_time > second.start_time
                    """
                )
            ]
        if {"bookings", "events", "rooms"} <= tables:
            session_exclusion = (
                """
                      AND NOT EXISTS (
                          SELECT 1 FROM sessions AS session
                          WHERE session.event_id = event.id
                      )
                """
                if "sessions" in tables
                else ""
            )
            booking_capacity = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT booking.id AS booking_id, event.id AS event_id,
                           event.expected_participants, room.name AS room_name,
                           room.capacity
                    FROM bookings AS booking
                    JOIN events AS event ON event.id = booking.event_id
                    JOIN rooms AS room ON room.id = booking.room_id
                    WHERE booking.status = 'confirmed'
                      AND booking.room_id IS NOT NULL
                      AND event.expected_participants > room.capacity
                      {session_exclusion}
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
        if "resources" in tables:
            stock_violations.extend(
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id AS resource_id, name AS resource_name,
                           stock, allocated_stock,
                           CASE
                               WHEN stock < 0 THEN 'stock_below_zero'
                               WHEN allocated_stock < 0 THEN 'allocated_below_zero'
                               ELSE 'allocated_exceeds_stock'
                           END AS violation_type
                    FROM resources
                    WHERE stock < 0
                       OR allocated_stock < 0
                       OR allocated_stock > stock
                    """
                )
            )
            if "bookings" in tables:
                stock_violations.extend(
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT resource.id AS resource_id,
                               resource.name AS resource_name,
                               resource.stock AS stock,
                               booking.id AS booking_id,
                               booking.start_time AS start_time,
                               booking.end_time AS end_time,
                               (
                                   SELECT COALESCE(SUM(other.quantity), 0)
                                   FROM bookings AS other
                                   WHERE other.resource_id = resource.id
                                     AND other.status = 'confirmed'
                                     AND (
                                         other.id = booking.id
                                         OR booking.start_time IS NULL
                                         OR booking.end_time IS NULL
                                         OR other.start_time IS NULL
                                         OR other.end_time IS NULL
                                         OR (
                                             other.start_time <= booking.start_time
                                             AND other.end_time > booking.start_time
                                         )
                                     )
                               ) AS booked_quantity,
                               'booking_exceeds_stock' AS violation_type
                        FROM bookings AS booking
                        JOIN resources AS resource ON resource.id = booking.resource_id
                        WHERE booking.resource_id IS NOT NULL
                          AND booking.status = 'confirmed'
                          AND (
                              booking.quantity < 0
                              OR (
                                  SELECT COALESCE(SUM(other.quantity), 0)
                                  FROM bookings AS other
                                  WHERE other.resource_id = resource.id
                                    AND other.status = 'confirmed'
                                    AND (
                                        other.id = booking.id
                                        OR booking.start_time IS NULL
                                        OR booking.end_time IS NULL
                                        OR other.start_time IS NULL
                                        OR other.end_time IS NULL
                                        OR (
                                            other.start_time <= booking.start_time
                                            AND other.end_time > booking.start_time
                                        )
                                    )
                              ) > resource.stock
                          )
                        """
                    )
                )
        if "sessions" in tables:
            speaker_select = (
                "COALESCE(speaker.name, first.speaker_id) AS speaker_name"
                if "speakers" in tables
                else "first.speaker_id AS speaker_name"
            )
            speaker_join = (
                """
                    LEFT JOIN speakers AS speaker
                      ON first.speaker_id = speaker.id
                """
                if "speakers" in tables
                else ""
            )
            speaker_clashes = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT first.id AS session_1, second.id AS session_2,
                           {speaker_select}, first.start_time,
                           first.end_time
                    FROM sessions AS first
                    JOIN sessions AS second
                      ON first.speaker_id = second.speaker_id
                     AND first.id < second.id
                    {speaker_join}
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
                missing_confirmed_booking_clause = (
                    """
                               OR NOT EXISTS (
                                   SELECT 1 FROM bookings AS booking
                                   WHERE booking.event_id = message.event_id
                                     AND booking.status = 'confirmed'
                               )
                    """
                    if "bookings" in tables
                    else ""
                )
                outbox_leaks = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT message.id, message.event_id, message.status,
                               event.status AS event_status
                        FROM outbox AS message
                        LEFT JOIN events AS event ON event.id = message.event_id
                        WHERE message.status = 'held'
                           OR event.id IS NULL
                           OR (message.status = 'sent'
                               AND (
                                   event.status IN ('cancelled', 'draft', 'rolled_back')
                                   {missing_confirmed_booking_clause}
                               ))
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
            "stock_violations_count": len(stock_violations),
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
                "stock_violations": stock_violations,
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
