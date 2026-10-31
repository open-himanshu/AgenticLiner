"""Transactional checkout with audit logging and a held-notice outbox."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid


DATABASE_PATH = Path(__file__).with_name("checkout.db")
MAX_RECORDS_PER_REQUEST = 10
SAVEPOINT_NAME = "checkout_attempt"


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the tables used by checkout if they do not already exist."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS venues (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK (capacity > 0),
            price_per_hour INTEGER NOT NULL CHECK (price_per_hour >= 0)
        );
        CREATE TABLE IF NOT EXISTS equipment (
            name TEXT PRIMARY KEY,
            price INTEGER NOT NULL CHECK (price >= 0),
            stock INTEGER NOT NULL CHECK (stock >= 0)
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            venue_id TEXT NOT NULL REFERENCES venues(id),
            date TEXT NOT NULL,
            start_hour INTEGER NOT NULL,
            end_hour INTEGER NOT NULL,
            headcount INTEGER NOT NULL,
            total_cost INTEGER NOT NULL,
            equipment_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS bookings_by_venue_and_date
            ON bookings (venue_id, date);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY,
            request_id TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            status TEXT NOT NULL,
            violations_json TEXT NOT NULL,
            records_changed INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY,
            request_id TEXT NOT NULL,
            message_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('held', 'sent'))
        );
        CREATE INDEX IF NOT EXISTS outbox_by_request
            ON outbox (request_id, status);
        """
    )


def connect_database(
    database_path: str | Path = DATABASE_PATH,
) -> sqlite3.Connection:
    """Open and initialize a connection with explicit transaction control."""
    connection = sqlite3.connect(
        database_path,
        isolation_level=None,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    return connection


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _write_audit(
    connection: sqlite3.Connection,
    request_id: str,
    status: str,
    violations: list[str],
    records_changed: int,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_log
            (request_id, attempted_at, status, violations_json, records_changed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            request_id,
            datetime.now(timezone.utc).isoformat(),
            status,
            json.dumps(violations),
            records_changed,
        ),
    )


def checkout(
    request: Mapping[str, Any],
    connection: sqlite3.Connection | None = None,
    *,
    max_records_changed: int | None = None,
) -> dict[str, Any]:
    """Try a booking atomically and return committed or rolled-back status.

    A supplied connection must not already have an open transaction. The
    change limit counts the booking row, each stock row, the outbox row, and
    the audit row.
    """
    owned_connection = connection is None
    if connection is None:
        connection = connect_database()
    if connection.in_transaction:
        if owned_connection:
            connection.close()
        raise sqlite3.ProgrammingError(
            "checkout requires a connection with no active transaction"
        )

    change_limit = (
        MAX_RECORDS_PER_REQUEST
        if max_records_changed is None
        else max_records_changed
    )
    if not _is_int(change_limit) or change_limit < 1:
        if owned_connection:
            connection.close()
        raise ValueError("max_records_changed must be a positive integer")

    connection.execute("PRAGMA foreign_keys = ON")
    request_id = (
        request.get("request_id")
        if isinstance(request, Mapping)
        else None
    )
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = uuid.uuid4().hex

    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(f"SAVEPOINT {SAVEPOINT_NAME}")
        notice_cursor = connection.execute(
            "INSERT INTO outbox (request_id, message_json, status) "
            "VALUES (?, ?, 'held')",
            (
                request_id,
                json.dumps(
                    {"type": "booking_confirmation", "request_id": request_id}
                ),
            ),
        )
        notice_id = notice_cursor.lastrowid

        violations: list[str] = []
        if not isinstance(request, Mapping):
            violations.append("request must be a JSON object")

        venue_id = request.get("venue_id") if isinstance(request, Mapping) else None
        booking_date_text = request.get("date") if isinstance(request, Mapping) else None
        start_hour = request.get("start_hour") if isinstance(request, Mapping) else None
        end_hour = request.get("end_hour") if isinstance(request, Mapping) else None
        headcount = request.get("headcount") if isinstance(request, Mapping) else None
        equipment_request = request.get("equipment", {}) if isinstance(request, Mapping) else {}
        budget = request.get("budget") if isinstance(request, Mapping) else None

        if not isinstance(venue_id, str) or not venue_id:
            violations.append("venue_id must be a non-empty string")
            venue = None
        else:
            venue = connection.execute(
                "SELECT name, capacity, price_per_hour FROM venues WHERE id = ?",
                (venue_id,),
            ).fetchone()
            if venue is None:
                violations.append(f"unknown venue: {venue_id}")

        booking_date: date | None = None
        if not isinstance(booking_date_text, str):
            violations.append("date must be a valid YYYY-MM-DD date")
        else:
            try:
                booking_date = date.fromisoformat(booking_date_text)
                if booking_date.isoformat() != booking_date_text:
                    raise ValueError
                if booking_date <= date.today():
                    violations.append("booking date must be after today")
            except ValueError:
                violations.append("date must be a valid YYYY-MM-DD date")

        valid_time = (
            _is_int(start_hour)
            and _is_int(end_hour)
            and 0 <= start_hour < end_hour <= 24
        )
        if not valid_time:
            violations.append(
                "start_hour/end_hour must be a valid increasing time window"
            )

        if not _is_int(headcount) or headcount <= 0:
            violations.append("headcount must be a positive integer")
        elif venue is not None and headcount > venue[1]:
            violations.append(
                f"headcount {headcount} exceeds venue capacity {venue[1]}"
            )

        if not _is_int(budget) or budget < 0:
            violations.append("budget must be a non-negative integer")

        if not isinstance(equipment_request, Mapping):
            violations.append("equipment must be an object of item quantities")
            equipment_request = {}

        valid_stock_changes: set[str] = set()
        equipment_cost = 0
        for name, quantity in equipment_request.items():
            if not isinstance(name, str) or not name:
                violations.append("equipment names must be non-empty strings")
                continue
            item = connection.execute(
                "SELECT price, stock FROM equipment WHERE name = ?",
                (name,),
            ).fetchone()
            if item is None:
                violations.append(f"unknown equipment: {name}")
                continue
            if not _is_int(quantity) or quantity <= 0:
                violations.append(
                    f"quantity for {name} must be greater than zero and an integer"
                )
                continue
            if quantity > item[1]:
                violations.append(
                    f"requested {quantity} {name}, but only {item[1]} in stock"
                )
                continue
            valid_stock_changes.add(name)
            equipment_cost += item[0] * quantity

        total_cost = 0
        if venue is not None and valid_time:
            total_cost += venue[2] * (end_hour - start_hour)
        total_cost += equipment_cost
        if _is_int(budget) and budget >= 0 and total_cost > budget:
            violations.append(
                f"total cost {total_cost} exceeds budget {budget}"
            )

        if (
            venue is not None
            and booking_date is not None
            and valid_time
        ):
            overlap = connection.execute(
                """
                SELECT 1 FROM bookings
                WHERE venue_id = ? AND date = ?
                  AND NOT (end_hour <= ? OR start_hour >= ?)
                LIMIT 1
                """,
                (venue_id, booking_date_text, start_hour, end_hour),
            ).fetchone()
            if overlap is not None:
                violations.append("venue overlaps an existing booking")

        planned_records = 1 + len(valid_stock_changes) + 1 + 1
        if planned_records > change_limit:
            violations.append(
                f"request would change {planned_records} records, "
                f"exceeding the limit of {change_limit}"
            )

        if violations:
            connection.execute(f"ROLLBACK TO SAVEPOINT {SAVEPOINT_NAME}")
            connection.execute(f"RELEASE SAVEPOINT {SAVEPOINT_NAME}")
            connection.execute(
                "DELETE FROM outbox WHERE id = ? AND status = 'held'",
                (notice_id,),
            )
            _write_audit(
                connection,
                request_id,
                "rolled_back",
                violations,
                1,
            )
            connection.execute("COMMIT")
            return {"status": "rolled_back", "violations": violations}

        booking_id = uuid.uuid4().hex
        connection.execute(
            """
            INSERT INTO bookings
                (id, request_id, venue_id, date, start_hour, end_hour,
                 headcount, total_cost, equipment_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                request_id,
                venue_id,
                booking_date_text,
                start_hour,
                end_hour,
                headcount,
                total_cost,
                json.dumps(dict(equipment_request)),
            ),
        )
        for name, quantity in equipment_request.items():
            connection.execute(
                "UPDATE equipment SET stock = stock - ? "
                "WHERE name = ? AND stock >= ?",
                (quantity, name, quantity),
            )

        connection.execute(f"RELEASE SAVEPOINT {SAVEPOINT_NAME}")
        _write_audit(
            connection,
            request_id,
            "committed",
            [],
            planned_records,
        )
        connection.execute("COMMIT")

        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE outbox SET status = 'sent' "
                "WHERE id = ? AND status = 'held'",
                (notice_id,),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

        return {
            "status": "committed",
            "request_id": request_id,
            "booking_id": booking_id,
            "total_cost": total_cost,
        }
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if owned_connection:
            connection.close()
