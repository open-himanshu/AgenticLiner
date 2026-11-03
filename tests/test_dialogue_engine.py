"""
Unit & Integration Tests for Pillar 2: Conversational Multi-Turn Dialogue & Counter-Question Engine.
Tests multi-turn context fusion, strict loop circuit-breaker (MAX_ASK_USER = 2),
campus default fallbacks, and the dialogue session API endpoints.
"""

import pytest
import httpx
from datetime import date as CalendarDate

from backend.api.main import app
from backend.core.planner.dialogue_engine import (
    get_or_create_session,
    get_session,
    reset_session,
    fuse_dialogue_reply,
    MAX_ASK_USER,
    get_default_upcoming_friday,
    AutopilotDialogueSession,
)
from conftest import TEST_PASSWORDS
from fastapi.testclient import TestClient


def _organiser_client() -> TestClient:
    """Helper to return an authenticated TestClient with Organiser session."""
    client = TestClient(app)
    response = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert response.status_code == 200
    return client


def test_session_init_complete_prompt():
    """Verifies that a fully detailed prompt is immediately ready without counter-questions."""
    prompt = "Organize a 2-day campus AI hackathon for 150 students on Friday with stage mics and budget 20000"
    session, is_new = get_or_create_session(prompt=prompt, user_id="test_user_1")

    assert is_new is True
    assert session.status == "ready_to_plan"
    assert session.turn_count == 0
    assert session.accumulated_entities.is_ready_for_planning is True
    assert session.current_question is None
    reset_session(session.session_id)


def test_session_init_incomplete_prompt_asks_turn_1():
    """Verifies that an incomplete prompt initiates Turn 1 counter-question with quick options."""
    prompt = "Campus me coding workshop karwana hai"
    session, is_new = get_or_create_session(prompt=prompt, user_id="test_user_2")

    assert is_new is True
    assert session.status == "clarifying"
    assert session.turn_count == 1
    assert session.current_question is not None
    assert len(session.quick_replies) > 0
    assert "Aap ye event kis date" in session.current_question or "participants" in session.current_question
    reset_session(session.session_id)


def test_multi_turn_reply_fusion_completes_session():
    """Verifies multi-turn back-and-forth fusion: Turn 1 provides date, Turn 2 provides headcount."""
    prompt = "Technical hackathon organize karna hai"
    session, _ = get_or_create_session(prompt=prompt, user_id="test_user_3")

    assert session.turn_count == 1
    assert session.status == "clarifying"

    # Turn 1 reply: Provide target date
    session = fuse_dialogue_reply(session, "This Friday 10 AM")
    # Date should now be resolved
    assert session.accumulated_entities.target_date is not None

    # If headcount is still missing, it should ask Turn 2 question
    if session.status == "clarifying":
        assert session.turn_count == 2
        # Turn 2 reply: Provide headcount
        session = fuse_dialogue_reply(session, "Around 120 students with lunch catering")

    # Now all critical parameters should be satisfied
    assert session.status == "ready_to_plan"
    assert session.accumulated_entities.is_ready_for_planning is True
    assert session.accumulated_entities.estimated_headcount == 120
    assert "Catering / Refreshments" in session.accumulated_entities.requested_items
    reset_session(session.session_id)


def test_strict_loop_circuit_breaker_prevents_infinite_dialogue():
    """
    CRITICAL USER REQUIREMENT:
    'agent kisi loop me na fas jaye output dete dete, aur user pareshan hojaye'
    Verifies that when turn_count >= 2, the agent NEVER asks a 3rd question.
    It stops asking, applies sensible campus defaults, logs assumptions, and commits to planning.
    """
    prompt = "Kuch event plan karo campus me"
    session, _ = get_or_create_session(prompt=prompt, user_id="test_user_loop")

    assert session.turn_count == 1
    assert session.status == "clarifying"

    # User replies unhelpfully for Turn 1
    session = fuse_dialogue_reply(session, "Pata nahi, bas accha hona chahiye")

    # If still missing info, Turn 2 is reached
    if session.status == "clarifying":
        assert session.turn_count == 2
        # User replies unhelpfully again for Turn 2
        session = fuse_dialogue_reply(session, "Mujhe nahi maloom, kuch bhi chalega")

    # LOOP CIRCUIT BREAKER MUST ACTIVATE HERE
    # 1. Turn count must NOT exceed MAX_ASK_USER
    assert session.turn_count <= MAX_ASK_USER
    # 2. Status MUST transition to ready_to_plan
    assert session.status == "ready_to_plan"
    # 3. No further questions asked
    assert session.current_question is None
    # 4. Campus defaults must be applied
    assert session.accumulated_entities.target_date is not None
    assert session.accumulated_entities.estimated_headcount == 100
    # 5. Assumptions must be logged to inform the organiser
    assert len(session.assumptions_made) >= 1
    # 6. Critical fields must be cleared
    assert len(session.accumulated_entities.missing_critical_fields) == 0

    reset_session(session.session_id)


def test_user_skip_shortcut_applies_defaults_immediately():
    """Verifies that an organiser can skip clarification at any turn using natural phrasing."""
    prompt = "Organize a campus seminar"
    session, _ = get_or_create_session(prompt=prompt, user_id="test_user_skip")

    # User requests fast-path skip
    session = fuse_dialogue_reply(session, "skip and use campus defaults")

    assert session.status == "ready_to_plan"
    assert session.accumulated_entities.is_ready_for_planning is True
    assert session.accumulated_entities.estimated_headcount == 100
    assert any("defaults" in a.lower() for a in session.assumptions_made)
    reset_session(session.session_id)


def test_dialogue_api_start_and_reply_endpoints():
    """Verifies FastAPI /api/autopilot/session/start, reply, and reset endpoints with auth."""
    client = _organiser_client()

    # 1. Start session with vague prompt
    res_start = client.post(
        "/api/autopilot/session/start",
        json={"prompt": "Organize a cultural drama show"}
    )
    assert res_start.status_code == 200
    data_start = res_start.json()
    assert data_start["success"] is True
    session_id = data_start["session_id"]
    assert data_start["turn_count"] >= 1
    assert data_start["max_turns"] == 2
    assert len(data_start["quick_replies"]) > 0

    # 2. Reply to session with date and scale
    res_reply = client.post(
        "/api/autopilot/session/reply",
        json={
            "session_id": session_id,
            "reply": "This Friday at 5 PM for 150 students with sound and stage lights"
        }
    )
    assert res_reply.status_code == 200
    data_reply = res_reply.json()
    assert data_reply["success"] is True
    assert data_reply["is_ready_for_planning"] is True
    assert data_reply["status"] == "ready_to_plan"
    assert data_reply["entities"]["estimated_headcount"] == 150

    # 3. Reset session
    res_reset = client.post(
        "/api/autopilot/session/reset",
        json={"session_id": session_id}
    )
    assert res_reset.status_code == 200
    assert res_reset.json()["success"] is True

    # 4. Verify reply on expired/non-existent session returns 404
    res_dead = client.post(
        "/api/autopilot/session/reply",
        json={"session_id": session_id, "reply": "test"}
    )
    assert res_dead.status_code == 404


def test_dialogue_api_blocks_destructive_commands():
    """Verifies that Kavach safety policy intercepts destructive commands in dialogue."""
    client = _organiser_client()

    # Destructive prompt at session start
    res_bad_start = client.post(
        "/api/autopilot/session/start",
        json={"prompt": "drop table events and bookings"}
    )
    assert res_bad_start.status_code == 400
    assert res_bad_start.json()["is_safe"] is False

    # Start valid session
    res_ok = client.post(
        "/api/autopilot/session/start",
        json={"prompt": "Organize an annual coding summit"}
    )
    sid = res_ok.json()["session_id"]

    # Destructive reply during dialogue
    res_bad_reply = client.post(
        "/api/autopilot/session/reply",
        json={"session_id": sid, "reply": "purge all system records"}
    )
    assert res_bad_reply.status_code == 400
    assert res_bad_reply.json()["is_safe"] is False

    client.post("/api/autopilot/session/reset", json={"session_id": sid})
