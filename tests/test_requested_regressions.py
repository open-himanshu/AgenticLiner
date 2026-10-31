import json
import sys
from types import SimpleNamespace

import pytest

from backend.core.database.connection import get_connection, get_db_path
from backend.core.planner import agent as planner_agent
from backend.core.safety.kavach import InvariantViolation, KavachEngine
from backend.modules.module5_comm_agent.agent import CommunicationAgent
from backend.services import agentic_genesis_service
from backend.core.planner import tools as planner_tools


def test_database_path_uses_isolated_environment_variable(monkeypatch, tmp_path):
    database_path = tmp_path / "configured-test.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert get_db_path() == str(database_path)

    with get_connection() as conn:
        conn.execute("CREATE TABLE isolation_check (id INTEGER)")
    assert database_path.exists()


def test_gemini_model_and_parser_source_are_reported(monkeypatch):
    captured = {}

    def generate_content(**kwargs):
        captured["model"] = kwargs["model"]
        return SimpleNamespace(text=json.dumps({"headcount": 25}))

    models = SimpleNamespace(generate_content=generate_content)
    fake_genai = SimpleNamespace(
        Client=lambda api_key: SimpleNamespace(models=models)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("GEMINI_MODEL", "configured-test-model")
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))

    parsed = agentic_genesis_service.parse_natural_language_event_prompt(
        "Plan a small event"
    )

    assert captured["model"] == "configured-test-model"
    assert parsed["parser"] == "gemini"


def test_regex_parser_source_is_reported(monkeypatch):
    monkeypatch.setattr(
        agentic_genesis_service, "parse_with_gemini_api", lambda prompt: None
    )

    parsed = agentic_genesis_service.parse_natural_language_event_prompt(
        "Workshop for 40 students"
    )

    assert parsed["parser"] == "regex_fallback"


def test_schedule_change_notice_handles_confirmed_registrants():
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (id, name, brief) VALUES (?, ?, ?)",
            ("event-notice-test", "Test event", "Test brief"),
        )
        conn.execute(
            "INSERT INTO students (id, name, email, department, year) "
            "VALUES (?, ?, ?, ?, ?)",
            ("student-notice-test", "Test Student", "notice@test.invalid", "Test", 1),
        )
        conn.execute(
            "INSERT INTO registrations (id, event_id, student_id, status) "
            "VALUES (?, ?, ?, 'confirmed')",
            ("registration-notice-test", "event-notice-test", "student-notice-test"),
        )

        result = CommunicationAgent().generate_schedule_change_notice(
            "event-notice-test", "Test session", "Room A", "Room B", conn=conn
        )

        assert result["staged_count"] == 1
        notice = conn.execute(
            "SELECT recipient FROM outbox WHERE event_id = ?",
            ("event-notice-test",),
        ).fetchone()
        assert notice["recipient"] == "notice@test.invalid"


def test_kavach_rolls_back_event_inserted_during_operation():
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (id, name, brief, expected_participants) "
            "VALUES (?, ?, ?, ?)",
            ("event-existing", "Existing", "Existing event", 10),
        )

        def fail_after_event_insert(connection):
            connection.execute(
                "INSERT INTO events (id, name, brief, expected_participants) "
                "VALUES (?, ?, ?, ?)",
                ("event-atomic-test", "Atomic", "Should roll back", 100),
            )
            raise InvariantViolation("test_failure", "booking", "Expected failure")

        result = KavachEngine().execute_with_kavach(
            conn,
            "event-atomic-test",
            "test",
            "atomic_event_and_booking",
            fail_after_event_insert,
        )

        assert result["status"] == "rolled_back"
        assert conn.execute(
            "SELECT 1 FROM events WHERE id = ?", ("event-atomic-test",)
        ).fetchone() is None


def test_failed_resource_requisition_rolls_back_created_event():
    result = planner_tools.tool_requisition_campus_resources(
        event_id="event-failed-requisition",
        room_id="room_comp_lab",
        attendance=1000,
        items_json=[],
        date="2026-12-01",
        start_time="09:00:00",
        end_time="10:00:00",
        event_details={
            "name": "Failed requisition",
            "brief": "Must roll back",
            "event_type": "workshop",
            "expected_participants": 1000,
        },
    )

    assert result["status"] == "rolled_back"
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM events WHERE id = ?", ("event-failed-requisition",)
        ).fetchone() is None


def test_autopilot_handles_empty_recommendation_list(monkeypatch):
    monkeypatch.setattr(
        planner_agent,
        "tool_find_free_venues",
        lambda **kwargs: {
            "venues": [
                {
                    "id": "room_sem_101",
                    "name": "Test Hall",
                    "capacity": 120,
                    "requires_special_approval": False,
                }
            ]
        },
    )
    monkeypatch.setattr(
        planner_agent,
        "tool_recommend_from_history",
        lambda **kwargs: {"recommendations": []},
    )
    monkeypatch.setattr(
        planner_agent,
        "tool_requisition_campus_resources",
        lambda **kwargs: {
            "status": "committed",
            "details": {"room_name": "Test Hall"},
        },
    )

    result = planner_agent.AutopilotAgent().run_autopilot("workshop for 20 people")

    assert result["success"] is True
    assert result["recommendations"] == []


@pytest.mark.parametrize("quantity", [0, -1])
def test_kavach_rejects_non_positive_resource_quantity(quantity):
    with get_connection() as conn:
        with pytest.raises(InvariantViolation, match="quantity"):
            KavachEngine().verify_resource_stock(
                conn, "res_mic_cordless", quantity, "09:00", "10:00"
            )


def test_kavach_rejects_unknown_resource_id():
    with get_connection() as conn:
        with pytest.raises(InvariantViolation, match="resource_not_found"):
            KavachEngine().verify_resource_stock(
                conn, "missing-resource", 1, "09:00", "10:00"
            )


def test_kavach_outbox_mutations_are_scoped_to_operation():
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (id, name, brief) VALUES (?, ?, ?)",
            ("event-outbox-test", "Outbox", "Test"),
        )
        conn.execute(
            "INSERT INTO outbox "
            "(id, event_id, recipient, subject, message, operation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "notice-prior-operation",
                "event-outbox-test",
                "prior@test.invalid",
                "Prior",
                "Prior held notice",
                "prior-operation",
            ),
        )

        operation_id = "current-operation"

        def stage_notice_then_fail(connection):
            connection.execute(
                "INSERT INTO outbox "
                "(id, event_id, recipient, subject, message, operation_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "notice-current-operation",
                    "event-outbox-test",
                    "current@test.invalid",
                    "Current",
                    "Current held notice",
                    operation_id,
                ),
            )
            raise InvariantViolation("test_failure", "booking", "Expected failure")

        result = KavachEngine().execute_with_kavach(
            conn,
            "event-outbox-test",
            "test",
            "scoped_outbox",
            stage_notice_then_fail,
            operation_id=operation_id,
        )

        assert result["status"] == "rolled_back"
        notices = conn.execute(
            "SELECT id, status FROM outbox ORDER BY id"
        ).fetchall()
        assert [(row["id"], row["status"]) for row in notices] == [
            ("notice-prior-operation", "held")
        ]


def test_kavach_releases_only_current_operation_notices():
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (id, name, brief) VALUES (?, ?, ?)",
            ("event-release-test", "Outbox", "Test"),
        )
        conn.execute(
            "INSERT INTO outbox "
            "(id, event_id, recipient, subject, message, operation_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "notice-prior-release",
                "event-release-test",
                "prior@test.invalid",
                "Prior",
                "Prior held notice",
                "prior-operation",
            ),
        )

        operation_id = "current-release-operation"

        def stage_notice(connection):
            connection.execute(
                "INSERT INTO outbox "
                "(id, event_id, recipient, subject, message, operation_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "notice-current-release",
                    "event-release-test",
                    "current@test.invalid",
                    "Current",
                    "Current held notice",
                    operation_id,
                ),
            )
            return {}

        result = KavachEngine().execute_with_kavach(
            conn,
            "event-release-test",
            "test",
            "scoped_outbox_release",
            stage_notice,
            operation_id=operation_id,
        )

        assert result["status"] == "committed"
        notices = conn.execute(
            "SELECT id, status FROM outbox ORDER BY id"
        ).fetchall()
        assert [(row["id"], row["status"]) for row in notices] == [
            ("notice-current-release", "sent"),
            ("notice-prior-release", "held"),
        ]
