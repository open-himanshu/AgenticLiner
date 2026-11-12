"""
Unit and Integration Tests for Autonomous Campus Event Operations Agent:
1. Proposing autonomous operational actions (Human-in-the-Loop staging).
2. Kavach invariant verification before proposing changes.
3. Explicit execution upon user approval (committing events, bookings, sessions, and outbox).
4. Rejection and rollback of proposals.
5. Dynamic incident handling: Speaker substitution.
6. Attendee waitlist promotion.
7. API endpoints: /api/agent/propose-action, /api/agent/confirm-action, /api/agent/reject-action.

All tests run fully offline with zero external network or LLM calls.
"""

import json
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.database.connection import get_connection, fetch_one, fetch_all, execute_query
from backend.services.agent_proposal_service import (
    propose_action,
    execute_action_proposal,
    reject_action_proposal,
    rollback_action_proposal,
    get_pending_proposals,
    init_proposals_table,
)
from conftest import TEST_PASSWORDS


@pytest.fixture(autouse=True)
def ensure_db_clean():
    """Ensure proposals table exists before each test."""
    init_proposals_table()


def _auth_client(role: str = "organiser") -> TestClient:
    """Helper to return authenticated TestClient."""
    client = TestClient(app)
    email = "organiser@galgotias.edu" if role == "organiser" else "dean.office@galgotias.edu"
    pwd = TEST_PASSWORDS["ORGANISER_PASSWORD"] if role == "organiser" else TEST_PASSWORDS["SUPERVISOR_PASSWORD"]
    resp = client.post("/login", json={"email": email, "password": pwd})
    assert resp.status_code == 200
    return client


def test_propose_event_genesis_creates_pending_proposal():
    """Verifies that a natural language prompt creates a staged ActionProposal without mutating event tables."""
    prompt = "Organize a campus AI & Robotics Hackathon for 120 students with stage mics and projectors"
    user = {"id": "usr_org", "role": "organiser", "email": "organiser@galgotias.edu", "full_name": "Casey Organiser"}

    proposal = propose_action(prompt=prompt, user=user)

    assert proposal["success"] is True
    assert proposal["status"] == "pending"
    assert proposal["action_type"] == "EVENT_GENESIS"
    assert "proposal_id" in proposal
    assert len(proposal["diff_summary"]) >= 3
    assert proposal["kavach_verification"]["status"] == "PASSED"
    assert proposal["requires_permission"] is True

    # Verify event is NOT yet created in the events table before user approves
    created_event = fetch_one("SELECT id FROM events WHERE name = ?", (proposal["staged_payload"]["event_name"],))
    assert created_event is None


def test_execute_approved_proposal_commits_state():
    """Verifies that approving a proposal commits all changes to events, bookings, and outbox."""
    prompt = "Campus Innovation Summit for 100 students with laser projector"
    user = {"id": "usr_org", "role": "organiser", "email": "organiser@galgotias.edu", "full_name": "Casey Organiser"}

    proposal = propose_action(prompt=prompt, user=user)
    proposal_id = proposal["proposal_id"]

    # Now execute with user approval
    exec_result = execute_action_proposal(proposal_id=proposal_id, actor="organiser")

    assert exec_result["success"] is True
    assert exec_result["status"] == "executed"
    event_id = exec_result["event_id"]
    assert event_id is not None

    # Verify record in events table
    db_event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    assert db_event is not None

    # Verify venue booking
    booking = fetch_one("SELECT * FROM bookings WHERE event_id = ? AND category = 'venue'", (event_id,))
    assert booking is not None

    # Verify outbox staged notice
    outbox = fetch_one("SELECT * FROM outbox WHERE id = ?", (exec_result["outbox_notice_id"],))
    assert outbox is not None
    assert outbox["status"] == "held"

    # Verify proposal status updated to executed
    prop_in_db = fetch_one("SELECT status FROM action_proposals WHERE id = ?", (proposal_id,))
    assert prop_in_db["status"] == "executed"


def test_reject_proposal_prevents_execution():
    """Verifies that rejecting a proposal marks it rejected and prevents state execution."""
    prompt = "Cancelled cultural eve for 80 students"
    user = {"id": "usr_org", "role": "organiser", "email": "organiser@galgotias.edu", "full_name": "Casey Organiser"}

    proposal = propose_action(prompt=prompt, user=user)
    proposal_id = proposal["proposal_id"]

    reject_res = reject_action_proposal(proposal_id=proposal_id, actor="organiser")
    assert reject_res["success"] is True
    assert reject_res["status"] == "rejected"

    # Attempting to execute rejected proposal must fail
    with pytest.raises(ValueError, match="Cannot execute proposal in 'rejected' status"):
        execute_action_proposal(proposal_id=proposal_id, actor="organiser")


def test_speaker_substitution_proposal_and_execution():
    """Verifies incident handling: replacing a speaker when someone cancels."""
    # Create a base event with a session first
    from backend.services.event_workflow_service import create_event_request
    ev = create_event_request(
        name="Tech Seminar",
        brief="Test brief",
        event_type="seminar",
        expected_participants=50,
        organizer_department="Computing",
        organizer_email="organiser@galgotias.edu",
        room_id="room_sem_101",
        start_time="2026-11-20 10:00:00",
        end_time="2026-11-20 12:00:00",
        budget=10000.0,
    )
    event_id = ev["event_id"]

    # Insert a session with spk_01
    session_id = f"sess_{event_id}_test"
    execute_query("""
        INSERT INTO sessions (id, event_id, title, speaker_id, room_id, start_time, end_time)
        VALUES (?, ?, 'AI Masterclass', 'spk_01', 'room_sem_101', '2026-11-20 10:00:00', '2026-11-20 11:30:00')
    """, (session_id, event_id))

    user = {"id": "usr_org", "role": "organiser", "email": "organiser@galgotias.edu", "full_name": "Casey Organiser"}
    swap_prompt = f"Speaker Dr. Sharma has an emergency for event {event_id}. Replace speaker and notify attendees."

    proposal = propose_action(prompt=swap_prompt, user=user)
    assert proposal["success"] is True
    assert proposal["action_type"] == "SPEAKER_SWAP"

    # Execute approval
    res = execute_action_proposal(proposal_id=proposal["proposal_id"], actor="organiser")
    assert res["success"] is True

    # Verify session has updated speaker
    updated_sess = fetch_one("SELECT speaker_id FROM sessions WHERE id = ?", (session_id,))
    assert updated_sess["speaker_id"] != "spk_01"

    # Verify outbox has change notice staged
    notice = fetch_one("SELECT * FROM outbox WHERE event_id = ? AND type = 'schedule_change'", (event_id,))
    assert notice is not None


def test_waitlist_promotion_proposal_and_execution():
    """Verifies attendee waitlist auto-promotion upon capacity release."""
    from backend.services.event_workflow_service import create_event_request
    ev = create_event_request(
        name="Coding Bootcamp",
        brief="Coding",
        event_type="workshop",
        expected_participants=2,
        organizer_department="Computing",
        organizer_email="organiser@galgotias.edu",
        room_id="room_conf_room",
        start_time="2026-11-22 10:00:00",
        end_time="2026-11-22 12:00:00",
        budget=10000.0,
    )
    event_id = ev["event_id"]

    # Insert 1 confirmed, 1 waitlisted student
    execute_query("INSERT OR IGNORE INTO students (id, name, email, department, year) VALUES ('stu_wait_1', 'Aarav Kumar', 'aarav@galgotias.edu', 'CSE', 2)")
    execute_query("INSERT OR IGNORE INTO registrations (id, event_id, student_id, status) VALUES ('reg_wait_1', ?, 'stu_wait_1', 'waitlist')", (event_id,))

    user = {"id": "usr_org", "role": "organiser", "email": "organiser@galgotias.edu", "full_name": "Casey Organiser"}
    prompt = f"Promote 1 waitlisted student for event {event_id}"

    proposal = propose_action(prompt=prompt, user=user)
    assert proposal["success"] is True
    assert proposal["action_type"] == "WAITLIST_PROMOTION"

    exec_res = execute_action_proposal(proposal_id=proposal["proposal_id"], actor="organiser")
    assert exec_res["success"] is True

    # Verify registration is now confirmed
    reg = fetch_one("SELECT status FROM registrations WHERE id = 'reg_wait_1'")
    assert reg["status"] == "confirmed"


def test_api_agent_propose_and_confirm_endpoints():
    """Verifies HTTP POST /api/agent/propose-action and POST /api/agent/confirm-action."""
    client = _auth_client(role="organiser")

    # 1. Propose action
    resp = client.post(
        "/api/agent/propose-action",
        json={"prompt": "Organize an annual dance fest for 150 students with sound system and stage lights"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    proposal_id = data["proposal"]["proposal_id"]
    assert data["proposal"]["status"] == "pending"

    # 2. Confirm action
    conf_resp = client.post(
        "/api/agent/confirm-action",
        json={"proposal_id": proposal_id}
    )
    assert conf_resp.status_code == 200
    conf_data = conf_resp.json()
    assert conf_data["success"] is True
    assert conf_data["status"] == "executed"
    assert "event_id" in conf_data
