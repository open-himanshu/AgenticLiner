from datetime import date, timedelta
import sqlite3

import pytest

from backend.safety.checkout import checkout, initialize_database


@pytest.fixture
def db():
    connection = sqlite3.connect(
        ":memory:",
        isolation_level=None,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    connection.execute(
        "INSERT INTO venues (id, name, capacity, price_per_hour) "
        "VALUES ('STG-C', 'Open Stage C', 300, 800)"
    )
    connection.executemany(
        "INSERT INTO equipment (name, price, stock) VALUES (?, ?, ?)",
        [
            ("stage lights", 400, 8),
            ("sound system", 2500, 2),
            ("wireless mic", 300, 6),
        ],
    )
    yield connection
    connection.close()


@pytest.fixture
def valid_request():
    return {
        "request_id": "test-request",
        "venue_id": "STG-C",
        "date": (date.today() + timedelta(days=1)).isoformat(),
        "start_hour": 18,
        "end_hour": 20,
        "headcount": 150,
        "equipment": {"stage lights": 2},
        "budget": 20000,
    }


def result_violations(result):
    assert result["status"] == "rolled_back"
    return result["violations"]


def test_valid_booking_commits_booking_stock_audit_and_notice(db, valid_request):
    result = checkout(valid_request, db)

    assert result["status"] == "committed"
    assert result["total_cost"] == 2400
    assert db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
    assert db.execute(
        "SELECT stock FROM equipment WHERE name = 'stage lights'"
    ).fetchone()[0] == 6
    assert db.execute(
        "SELECT status FROM outbox WHERE request_id = 'test-request'"
    ).fetchone()[0] == "sent"
    assert db.execute(
        "SELECT status FROM audit_log WHERE request_id = 'test-request'"
    ).fetchone()[0] == "committed"


def test_venue_overlap_is_rejected(db, valid_request):
    db.execute(
        """
        INSERT INTO bookings
            (id, request_id, venue_id, date, start_hour, end_hour,
             headcount, total_cost, equipment_json)
        VALUES ('existing', 'prior', 'STG-C', ?, 19, 21, 100, 1600, '{}')
        """,
        (valid_request["date"],),
    )

    violations = result_violations(checkout(valid_request, db))

    assert "venue overlaps an existing booking" in violations


def test_headcount_above_capacity_is_rejected(db, valid_request):
    valid_request["headcount"] = 301

    violations = result_violations(checkout(valid_request, db))

    assert any("exceeds venue capacity" in item for item in violations)


def test_equipment_quantity_above_stock_is_rejected(db, valid_request):
    valid_request["equipment"] = {"stage lights": 9}

    violations = result_violations(checkout(valid_request, db))

    assert any("in stock" in item for item in violations)


def test_total_cost_above_budget_is_rejected(db, valid_request):
    valid_request["budget"] = 2000

    violations = result_violations(checkout(valid_request, db))

    assert any("exceeds budget" in item for item in violations)


def test_past_date_is_rejected(db, valid_request):
    valid_request["date"] = (date.today() - timedelta(days=1)).isoformat()

    violations = result_violations(checkout(valid_request, db))

    assert "booking date must be after today" in violations


def test_non_increasing_time_is_rejected(db, valid_request):
    valid_request["start_hour"] = valid_request["end_hour"]

    violations = result_violations(checkout(valid_request, db))

    assert any("valid increasing time window" in item for item in violations)


def test_unknown_equipment_is_rejected(db, valid_request):
    valid_request["equipment"] = {"unicorn": 1}

    violations = result_violations(checkout(valid_request, db))

    assert "unknown equipment: unicorn" in violations


def test_rollback_leaves_bookings_and_stock_unchanged(db, valid_request):
    valid_request["equipment"] = {"stage lights": 9}
    stock_before = db.execute(
        "SELECT stock FROM equipment WHERE name = 'stage lights'"
    ).fetchone()[0]

    result_violations(checkout(valid_request, db))

    assert db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    assert db.execute(
        "SELECT stock FROM equipment WHERE name = 'stage lights'"
    ).fetchone()[0] == stock_before


def test_held_notice_is_discarded_after_rollback(db, valid_request):
    valid_request["headcount"] = 301

    result_violations(checkout(valid_request, db))

    assert db.execute(
        "SELECT COUNT(*) FROM outbox WHERE request_id = 'test-request'"
    ).fetchone()[0] == 0


def test_notice_is_released_only_after_booking_commit(db, valid_request):
    result = checkout(valid_request, db)

    assert result["status"] == "committed"
    assert db.execute(
        "SELECT status FROM outbox WHERE request_id = 'test-request'"
    ).fetchone()[0] == "sent"
    assert db.execute(
        "SELECT status FROM audit_log WHERE request_id = 'test-request'"
    ).fetchone()[0] == "committed"


def test_commit_does_not_release_an_older_held_notice(db, valid_request):
    db.execute(
        "INSERT INTO outbox (request_id, message_json, status) "
        "VALUES ('test-request', '{}', 'held')"
    )

    checkout(valid_request, db)

    statuses = db.execute(
        "SELECT status FROM outbox WHERE request_id = 'test-request' ORDER BY id"
    ).fetchall()
    assert statuses == [("held",), ("sent",)]


def test_blast_radius_limit_rolls_back_changes(db, valid_request):
    result = checkout(valid_request, db, max_records_changed=3)

    violations = result_violations(result)

    assert any("exceeding the limit of 3" in item for item in violations)
    assert db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1


def test_today_date_is_rejected(db, valid_request):
    valid_request["date"] = date.today().isoformat()

    result = checkout(valid_request, db)

    assert result["status"] == "rolled_back"
    assert "booking date must be after today" in result["violations"]


def test_missing_venue_is_audited(db, valid_request):
    valid_request["venue_id"] = "missing"

    result_violations(checkout(valid_request, db))

    assert db.execute(
        "SELECT status FROM audit_log WHERE request_id = 'test-request'"
    ).fetchone()[0] == "rolled_back"
