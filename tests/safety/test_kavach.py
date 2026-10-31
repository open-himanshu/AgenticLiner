"""
Unit tests for Kavach Safety Engine (Academic Edition: Invariant checking, Savepoint and Rollback, Outbox staging).
"""
import pytest
import sqlite3
import uuid
from datetime import date
from backend.core.database.connection import get_connection
from backend.core.database.init_db import init_database, seed_campus_data
from backend.core.safety.kavach import KavachEngine, InvariantViolation

@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_database(conn)
    seed_campus_data(conn)
    yield conn
    conn.close()

def test_kavach_successful_commit(test_db):
    kavach = KavachEngine()
    event_id = f"ev_test_{uuid.uuid4().hex[:6]}"
    
    test_db.execute(
        "INSERT INTO events (id, name, brief, expected_participants) VALUES (?, ?, ?, ?)",
        (event_id, "Test Hackathon", "A 2-day hackathon", 50)
    )

    operation_id = "op_success_test"

    def valid_booking_action(conn):
        kavach.verify_room_capacity(conn, "room_sem_101", 50)
        kavach.verify_room_overlap(conn, "room_sem_101", "2026-11-20 10:00:00", "2026-11-20 12:00:00")
        
        b_id = f"bk_{uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (b_id, event_id, "room_sem_101", "Seminar Hall 1", "venue", "2026-11-20 10:00:00", "2026-11-20 12:00:00", "confirmed")
        )
        m_id = f"msg_{uuid.uuid4().hex[:6]}"
        conn.execute(
            "INSERT INTO outbox (id, event_id, recipient, subject, message, status, operation_id) VALUES (?, ?, ?, ?, ?, 'held', ?)",
            (m_id, event_id, "student@galgotias.edu", "Booking Confirmed", "Your hall is booked.", operation_id)
        )
        return {"booking_id": b_id}

    result = kavach.execute_with_kavach(test_db, event_id, "test_user", "book_venue", valid_booking_action, operation_id)
    
    assert result["status"] == "committed"
    cur = test_db.cursor()
    cur.execute("SELECT count(*) FROM bookings WHERE event_id = ?", (event_id,))
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT status FROM outbox WHERE event_id = ?", (event_id,))
    assert cur.fetchone()[0] == "sent"

def test_kavach_capacity_overrun_rollback(test_db):
    kavach = KavachEngine()
    event_id = f"ev_overrun_{uuid.uuid4().hex[:6]}"
    
    test_db.execute(
        "INSERT INTO events (id, name, brief, expected_participants) VALUES (?, ?, ?, ?)",
        (event_id, "Mega Workshop", "Massive AI workshop", 150)
    )

    operation_id = "op_failure_test"

    def invalid_capacity_action(conn):
        kavach.verify_room_capacity(conn, "room_comp_lab", 150)
        
        conn.execute(
            "INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("bk_bad", event_id, "room_comp_lab", "Computing Lab 4", "venue", "2026-11-20 10:00:00", "2026-11-20 12:00:00", "confirmed")
        )
        conn.execute(
            "INSERT INTO outbox (id, event_id, recipient, subject, message, status, operation_id) VALUES (?, ?, ?, ?, ?, 'held', ?)",
            ("msg_bad", event_id, "student@galgotias.edu", "Bad Notice", "Wrong room booked", operation_id)
        )
        return {"status": "ok"}

    result = kavach.execute_with_kavach(test_db, event_id, "test_user", "book_oversized", invalid_capacity_action, operation_id)

    assert result["status"] == "rolled_back"
    assert result["violation"]["rule"] == "capacity_overrun"
    assert "Allocate a larger hall:" in result["violation"]["suggestion"]

    cur = test_db.cursor()
    cur.execute("SELECT count(*) FROM bookings WHERE event_id = ?", (event_id,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM outbox WHERE event_id = ?", (event_id,))
    assert cur.fetchone()[0] == 0


def test_kavach_enforces_blast_radius_and_rolls_back(test_db):
    kavach = KavachEngine(max_blast_radius=2)
    event_id = "ev_blast_radius"
    test_db.execute(
        "INSERT INTO events (id, name, brief) VALUES (?, ?, ?)",
        (event_id, "Blast Radius Test", "Test"),
    )

    def too_many_changes(conn):
        conn.executemany(
            "INSERT INTO audit_log (id, event_id, actor, action, result) VALUES (?, ?, ?, ?, ?)",
            [
                (f"blast_{index}", event_id, "test", "change", "SUCCESS")
                for index in range(3)
            ],
        )
        return {"success": True}

    result = kavach.execute_with_kavach(
        test_db, event_id, "test", "too_many_changes", too_many_changes
    )

    assert result["status"] == "rolled_back"
    assert result["violation"]["rule"] == "blast_radius_exceeded"
    assert test_db.execute(
        "SELECT count(*) FROM audit_log WHERE id LIKE 'blast_%'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("start_time", "end_time"),
    [
        ("2030-01-02 10:00:00", "2030-01-02 10:00:00"),
        ("2030-01-02 11:00:00", "2030-01-02 10:00:00"),
        (
            f"{date.today().isoformat()} 09:00:00",
            f"{date.today().isoformat()} 10:00:00",
        ),
        ("2000-01-01 09:00:00", "2000-01-01 10:00:00"),
    ],
)
def test_kavach_rejects_invalid_or_past_time_windows(test_db, start_time, end_time):
    with pytest.raises(InvariantViolation) as exc_info:
        KavachEngine().verify_time_window(start_time, end_time)
    assert exc_info.value.rule == "invalid_time_window"


def test_kavach_rejects_booking_cost_above_event_budget(test_db):
    event_id = "ev_budget_test"
    test_db.execute(
        "INSERT INTO events (id, name, brief, budget) VALUES (?, ?, ?, ?)",
        (event_id, "Budget Test", "Test", 100),
    )
    test_db.execute(
        """INSERT INTO bookings
           (id, event_id, item_name, category, estimated_cost)
           VALUES (?, ?, ?, ?, ?)""",
        ("booking_over_budget", event_id, "Projector", "equipment", 101),
    )

    with pytest.raises(InvariantViolation) as exc_info:
        KavachEngine().verify_event_budget(test_db, event_id, budget=100)
    assert exc_info.value.rule == "budget_exceeded"


def test_kavach_enforces_configurable_recipient_limit(test_db):
    kavach = KavachEngine(max_recipients=2)
    with pytest.raises(InvariantViolation) as exc_info:
        kavach.verify_recipient_limit(
            test_db,
            ["one@example.invalid", "two@example.invalid", "three@example.invalid"],
        )
    assert exc_info.value.rule == "recipient_limit_exceeded"


def test_recipient_limit_can_be_configured_from_environment(monkeypatch):
    monkeypatch.setenv("KAVACH_MAX_RECIPIENTS", "7")
    assert KavachEngine().max_recipients == 7


def test_schedule_change_notice_rolls_back_when_recipient_cap_is_exceeded(
    test_db, monkeypatch
):
    from backend.modules.module5_comm_agent import agent as communication_agent

    event_id = "ev_schedule_recipient_cap"
    test_db.execute(
        "INSERT INTO events (id, name, brief) VALUES (?, ?, ?)",
        (event_id, "Schedule Cap Event", "Test"),
    )
    for index in range(3):
        student_id = f"recipient_student_{index}"
        test_db.execute(
            """INSERT INTO students (id, name, email, department, year)
               VALUES (?, ?, ?, ?, ?)""",
            (
                student_id,
                f"Student {index}",
                f"student{index}@example.invalid",
                "Test",
                1,
            ),
        )
        test_db.execute(
            """INSERT INTO registrations (id, event_id, student_id, status)
               VALUES (?, ?, ?, 'confirmed')""",
            (f"recipient_registration_{index}", event_id, student_id),
        )

    monkeypatch.setattr(
        communication_agent, "kavach", KavachEngine(max_recipients=2)
    )
    with pytest.raises(InvariantViolation) as exc_info:
        communication_agent.CommunicationAgent().generate_schedule_change_notice(
            event_id, "Test Session", "Old Hall", "New Hall", conn=test_db
        )

    assert exc_info.value.rule == "recipient_limit_exceeded"
    assert test_db.execute(
        "SELECT count(*) FROM outbox WHERE event_id = ?", (event_id,)
    ).fetchone()[0] == 0


def test_supervisor_page_lists_pending_human_review_requests():
    from fastapi.testclient import TestClient
    from conftest import TEST_PASSWORDS
    from backend.core.database.connection import execute_query
    from backend.api.main import app

    execute_query(
        """INSERT INTO human_review_queue
           (id, actor, operation_name, request_json, attempts, last_error)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "review_api_test",
            "planner",
            "test_operation",
            '{"request":"needs review"}',
            3,
            "Safety rule failed.",
        ),
    )
    client = TestClient(app)
    client.post(
        "/login",
        data={
            "email": "admin@galgotias.edu",
            "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
        },
        follow_redirects=False,
    )
    response = client.get("/api/human-review")

    assert response.status_code == 200
    assert any(
        item["id"] == "review_api_test" for item in response.json()["requests"]
    )


def test_outbox_release_is_atomic_when_blast_radius_is_exceeded(monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import TEST_PASSWORDS
    from backend.core.database.connection import execute_query, fetch_all
    from backend.api import main

    for index in range(2):
        execute_query(
            """INSERT INTO outbox
               (id, event_id, recipient, subject, message, status)
               VALUES (?, 'ev_001', ?, ?, ?, 'held')""",
            (
                f"release_test_{index}",
                f"recipient{index}@example.invalid",
                "Test notice",
                "Test message",
            ),
        )
    monkeypatch.setattr(main, "kavach", KavachEngine(max_blast_radius=1))
    client = TestClient(main.app)
    client.post(
        "/login",
        data={
            "email": "admin@galgotias.edu",
            "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
        },
        follow_redirects=False,
    )

    response = client.post("/api/outbox/release-all")

    assert response.status_code == 400
    statuses = fetch_all(
        "SELECT status FROM outbox WHERE id LIKE 'release_test_%' ORDER BY id"
    )
    assert [row["status"] for row in statuses] == ["held", "held"]


def test_kavach_retry_queues_request_for_human_review_after_three_violations(test_db):
    kavach = KavachEngine()
    callback_errors = []

    def planner_callback(error, attempt):
        callback_errors.append((error, attempt))

        def action(conn):
            raise InvariantViolation(
                "test_failure", "planner", f"attempt {attempt} failed"
            )

        return action

    result = kavach.execute_with_retry(
        test_db,
        event_id="ev_human_review",
        actor="test_planner",
        operation_name="retry_test",
        planner_callback=planner_callback,
        request_payload={"event": "test"},
        max_retries=99,
    )

    assert result["status"] == "human_review"
    assert result["attempts"] == 4
    assert len(callback_errors) == 4
    assert callback_errors[0] == (None, 1)
    assert all(error and len(error) <= 160 for error, _ in callback_errors[1:])
    queued = test_db.execute(
        "SELECT request_json, attempts FROM human_review_queue WHERE id = ?",
        (result["review_id"],),
    ).fetchone()
    assert queued["request_json"] == '{"event": "test"}'
    assert queued["attempts"] == 4


def test_kavach_retry_succeeds_after_planner_adjusts_request(test_db):
    calls = []

    def planner_callback(error, attempt):
        calls.append((error, attempt))
        if attempt == 1:
            return lambda conn: (_ for _ in ()).throw(
                InvariantViolation("retryable", "planner", "change the request")
            )
        return lambda conn: {"planned": True}

    result = KavachEngine().execute_with_retry(
        test_db,
        event_id="ev_retry_success",
        actor="test_planner",
        operation_name="retry_success",
        planner_callback=planner_callback,
        request_payload={"event": "test"},
    )

    assert result["status"] == "committed"
    assert result["details"] == {"planned": True}
    assert len(calls) == 2
    assert calls[1][0] == "[retryable] planner: change the request"
