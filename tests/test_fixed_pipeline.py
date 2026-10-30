from datetime import date, timedelta
import inspect
import sqlite3

import pytest

from backend.planner.fixed_pipeline import (
    next_friday,
    run_pipeline,
    seed_pipeline_database,
)
from backend.planner import test_tool_calling as mock_agent
from backend.planner.llm_doctor import ProviderConfig, gemini_generate


@pytest.fixture
def db():
    connection = sqlite3.connect(
        ":memory:",
        isolation_level=None,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    seed_pipeline_database(connection)
    yield connection
    connection.close()


def make_request(**overrides):
    request = {
        "event_type": "dance",
        "headcount": 150,
        "date": (date.today() + timedelta(days=2)).isoformat(),
        "start_hour": 18,
        "end_hour": 20,
        "budget": 20000,
        "organiser": "Himanshu",
    }
    request.update(overrides)
    return request


def business_state(connection):
    return (
        connection.execute(
            "SELECT * FROM bookings WHERE request_id != 'seeded-availability' "
            "ORDER BY id"
        ).fetchall(),
        connection.execute("SELECT * FROM equipment ORDER BY name").fetchall(),
        connection.execute("SELECT * FROM outbox ORDER BY id").fetchall(),
    )


def test_pipeline_commits_within_budget_and_releases_notice(db):
    report = run_pipeline(make_request(), db)

    assert report["status"] == "committed"
    assert (
        "Equipment quantities taken from the last similar event (past headcount 100), "
        "capped to stock and the checkout change limit; not scaled to the new headcount."
    ) in report["assumptions"]
    assert report["bookings"]
    assert report["total_cost"] <= 20000
    assert db.execute("SELECT COUNT(*) FROM bookings WHERE request_id != 'seeded-availability'").fetchone()[0] == 1
    assert db.execute("SELECT status FROM outbox").fetchone() == ("sent",)


def test_pipeline_rejects_over_budget_and_tries_one_alternative(db):
    report = run_pipeline(make_request(budget=100), db)

    assert report["status"] == "rejected"
    assert len(report["attempts"]) == 2
    assert all(attempt["status"] == "rolled_back" for attempt in report["attempts"])
    assert any("exceeds budget" in violation for violation in report["violations"])


def test_pipeline_reports_when_no_venue_is_free(db):
    event_date = make_request()["date"]
    for venue_id in mock_agent.VENUES:
        db.execute(
            """
            INSERT INTO bookings
                (id, request_id, venue_id, date, start_hour, end_hour,
                 headcount, total_cost, equipment_json)
            VALUES (?, 'blocked', ?, ?, 17, 22, 1, 0, '{}')
            """,
            (f"blocked-{venue_id}", venue_id, event_date),
        )

    report = run_pipeline(make_request(), db)

    assert report["status"] == "no_venue"
    assert "no free venue" in report["violations"][0]
    assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_pipeline_caps_requested_equipment_to_available_stock(db):
    db.execute("UPDATE equipment SET stock = 1 WHERE name = 'stage lights'")

    report = run_pipeline(make_request(), db)

    assert report["status"] == "committed"
    assert any("stage lights" in shortage for shortage in report["equipment_shortages"])
    assert report["bookings"][0]["equipment"]["stage lights"] == 1


def test_checkout_rollback_preserves_business_state(db):
    before = business_state(db)

    report = run_pipeline(make_request(budget=100), db)

    assert report["status"] == "rejected"
    assert business_state(db) == before


def test_notice_is_not_released_after_rollback(db):
    report = run_pipeline(make_request(budget=100), db)

    assert report["status"] == "rejected"
    assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM outbox WHERE status = 'sent'").fetchone()[0] == 0


def test_next_friday_resolves_to_upcoming_friday():
    assert next_friday(date(2026, 10, 30)) == date(2026, 11, 6)


def test_gemini_generate_signature_accepts_sdk_config_keyword_offline():
    provider_config = ProviderConfig("gemini", "localhost", 443, "", "model", 1)

    bound_arguments = inspect.signature(gemini_generate).bind(
        object(),
        provider_config,
        contents="Say OK",
        config=object(),
    )

    assert bound_arguments.arguments["provider_config"] is provider_config
    assert "config" in bound_arguments.arguments["kwargs"]
