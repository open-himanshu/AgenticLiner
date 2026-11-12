"""Regression tests for critical UI, JSON serialization, resource-ID, and read-query bugs."""

import json
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.database.connection import execute_query, fetch_all, fetch_one
from backend.core.planner.confirmation_engine import (
    _FALLBACK_RESOURCE_COSTS,
    commit_draft_plan_atomic,
    synthesize_speculative_draft,
)
from backend.core.planner.dialogue_engine import get_or_create_session, reset_session
from backend.modules.module2_scheduling.attendee_manager import AttendeeManager
from backend.modules.module4_participant_xp.recommender import ParticipantExperienceEngine
from backend.services.agentic_genesis_service import execute_universal_command
from backend.services.analytics_service import record_feedback
from conftest import TEST_PASSWORDS


def _login(client: TestClient, email: str, pwd_key: str) -> None:
    res = client.post(
        "/login",
        json={"email": email, "password": TEST_PASSWORDS[pwd_key]},
    )
    assert res.status_code == 200


def test_participant_feedback_modal_bound_after_dom_ready():
    client = TestClient(app)
    _login(client, "student@galgotias.edu", "PARTICIPANT_PASSWORD")
    res = client.get("/participant")
    assert res.status_code == 200
    assert 'id="feedbackModal"' in res.text
    assert 'id="btnModalSubmitFeedback"' in res.text
    assert "DOMContentLoaded" in res.text


def test_attendee_manager_stores_valid_json_and_recommender_handles_legacy_lists():
    mgr = AttendeeManager()
    reg = mgr.register_student(
        event_id="ev_001",
        name="Json Check Student",
        email="jsoncheck@example.invalid",
        department="CSE",
        year=2,
        interests=["AI", "Robotics"],
        preferred_sessions=["sess_01"],
    )
    assert reg["success"] is True

    stu = fetch_one("SELECT id, interests FROM students WHERE email = ?", ("jsoncheck@example.invalid",))
    reg_row = fetch_one("SELECT interests_snapshot, preferred_sessions FROM registrations WHERE id = ?", (reg["registration_id"],))
    assert json.loads(stu["interests"]) == ["AI", "Robotics"]
    assert json.loads(reg_row["interests_snapshot"]) == ["AI", "Robotics"]
    assert json.loads(reg_row["preferred_sessions"]) == ["sess_01"]

    # Insert a legacy Python str(list) student and ensure peer matching still works cleanly.
    execute_query(
        "INSERT INTO students (id, name, email, department, year, interests) VALUES (?, ?, ?, ?, ?, ?)",
        ("stu_legacy_str", "Legacy Student", "legacy@example.invalid", "CSE", 3, "['AI', 'Python']"),
    )
    matches = ParticipantExperienceEngine().recommend_networking("stu_legacy_str")
    assert "peer_matches" in matches
    assert "mentor_matches" in matches
    missing = ParticipantExperienceEngine().recommend_networking("no_such_student")
    assert missing["peer_matches"] == []
    assert missing["mentor_matches"] == []


def test_confirmation_fallback_resource_ids_exist_in_seeded_resources():
    db_ids = {r["id"] for r in fetch_all("SELECT id FROM resources")}
    assert db_ids
    for item_name, ref in _FALLBACK_RESOURCE_COSTS.items():
        assert ref["id"] in db_ids, f"Missing resource_id {ref['id']} for {item_name}"

    session, _ = get_or_create_session(
        prompt="Dance performance for 100 students this Friday with projector and sound system",
        user_id="audit_res_user",
    )
    draft = synthesize_speculative_draft(session)
    commit_res = commit_draft_plan_atomic(draft, user_id="audit_res_user")
    assert commit_res["status"] == "committed"
    orphans = fetch_all(
        """
        SELECT b.id, b.resource_id
        FROM bookings b
        LEFT JOIN resources r ON b.resource_id = r.id
        WHERE b.event_id = ? AND b.resource_id IS NOT NULL AND r.id IS NULL
        """,
        (commit_res["details"]["event_id"],),
    )
    assert orphans == []
    reset_session(session.session_id)


def test_analytics_honest_zero_and_negative_only_display():
    client = TestClient(app)
    _login(client, "admin@galgotias.edu", "SUPERVISOR_PASSWORD")

    empty_page = client.get("/analytics")
    assert empty_page.status_code == 200
    assert "VADER" not in empty_page.text
    assert "4.8 / 5.0" not in empty_page.text
    assert "75% Positive" not in empty_page.text

    record_feedback(
        event_id="ev_001",
        rating=1,
        comment="Terrible audio mic echo and delayed schedule.",
        student_id="stu_neg_only",
    )
    neg_page = client.get("/analytics?event_id=ev_001")
    assert neg_page.status_code == 200
    assert "0.0% Positive" in neg_page.text
    assert "100.0% Negative" in neg_page.text
    assert "75% Positive" not in neg_page.text
    assert "/api/report/pdf/ev_001" in neg_page.text


def test_autopilot_budget_input_does_not_hardcode_100000():
    client = TestClient(app)
    _login(client, "organiser@galgotias.edu", "ORGANISER_PASSWORD")
    page = client.get("/autopilot")
    assert page.status_code == 200
    assert 'id="agentBudget" value="100000"' not in page.text


def test_universal_command_read_only_room_query_creates_no_event():
    before = len(fetch_all("SELECT id FROM events"))
    res = execute_universal_command("Show all available rooms")
    after = len(fetch_all("SELECT id FROM events"))
    assert res["success"] is True
    assert res["action"] == "VENUES_LISTED"
    assert after == before
