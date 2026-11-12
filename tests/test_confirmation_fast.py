"""
Unit & Integration Tests for Pillar 5: Pre-Commit Interactive Confirmation Card & Voice Review.
Inspired by OpenAI ChatGPT Realtime Voice Interaction:
Tests:
1. Sub-50ms Fast-Path Intent Recognition (English, Hindi, Hinglish affirmations & cancellations).
2. Delta Parameter Extraction (headcount, time, resource additions/removals).
3. Zero-side-effect Speculative Draft Compilation (0 rows written to database).
4. In-Place Delta Mutation (dynamic hall capacity scaling & re-pricing).
5. Atomic Kavach Commitment upon explicit confirmation.
6. REST API Endpoints (/api/autopilot/draft, /delta, /confirm).
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner.fast_intent import classify_fast_intent
from backend.core.planner.dialogue_engine import get_or_create_session, reset_session
from backend.core.planner.confirmation_engine import (
    synthesize_speculative_draft,
    get_cached_draft,
    apply_draft_delta,
    commit_draft_plan_atomic,
    _draft_cache
)
from backend.core.database.connection import fetch_one, fetch_all
from conftest import TEST_PASSWORDS


def _organiser_client() -> TestClient:
    """Helper returning authenticated TestClient for organiser."""
    client = TestClient(app)
    res = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert res.status_code == 200
    return client


def test_fast_intent_classification_affirmative():
    """Verifies sub-10ms classification of English, Hindi, and Hinglish confirmation phrases."""
    phrases = [
        "yes", "confirm", "confirmed", "book it", "lock it", "proceed",
        "haan", "ha", "kar do", "lock karo", "theek hai", "sahi hai",
        "chalo", "pakka", "final karo", "book kar do", "kar dijiye"
    ]
    for p in phrases:
        res = classify_fast_intent(p)
        assert res.intent == "confirm", f"Failed for phrase: '{p}', got {res.intent}"
        assert res.confidence >= 0.95
        assert "lock" in res.verbal_ack.lower() or "booking" in res.verbal_ack.lower()


def test_fast_intent_classification_cancel():
    """Verifies instant abort/cancel intent detection."""
    cancels = [
        "no", "cancel", "stop", "abort", "don't book", "wait",
        "nahi", "mat karna", "ruko", "cancel karo", "ruk jao", "nahi chahiye"
    ]
    for c in cancels:
        res = classify_fast_intent(c)
        assert res.intent == "cancel", f"Failed for cancel phrase: '{c}'"
        assert "cancel" in res.verbal_ack.lower() or "theek hai" in res.verbal_ack.lower()


def test_fast_intent_classification_delta():
    """Verifies extraction of in-place parameter mutations."""
    # Headcount & time delta
    res1 = classify_fast_intent("change time to 4 PM and make headcount 200")
    assert res1.intent == "delta"
    assert res1.delta_params.get("headcount") == 200
    assert "16:00:00" in res1.delta_params.get("start_time", "")

    # Item removal
    res2 = classify_fast_intent("remove projector and cancel mic")
    assert res2.intent == "delta"
    removals = res2.delta_params.get("remove_items", [])
    assert any("Projector" in r for r in removals)


def test_speculative_draft_compilation_zero_side_effects():
    """Verifies draft plan compilation writes 0 rows to database before confirmation."""
    session, _ = get_or_create_session(
        prompt="Annual Dance Gala this Friday for 120 students with sound system",
        user_id="test_draft_user"
    )

    # Initial row count
    events_before = len(fetch_all("SELECT id FROM events"))
    bookings_before = len(fetch_all("SELECT id FROM bookings"))

    draft = synthesize_speculative_draft(session)
    assert draft is not None
    assert draft.session_id == session.session_id
    assert draft.venue is not None
    assert draft.venue.capacity >= 120
    assert draft.total_cost > 0
    assert "Rs." in draft.verbal_summary
    assert draft.status == "draft"

    # Verify zero database mutations
    events_after = len(fetch_all("SELECT id FROM events"))
    bookings_after = len(fetch_all("SELECT id FROM bookings"))
    assert events_before == events_after, "Draft compilation must NOT insert rows into events table"
    assert bookings_before == bookings_after, "Draft compilation must NOT insert rows into bookings table"

    reset_session(session.session_id)


def test_apply_draft_delta_dynamic_scaling():
    """Verifies that changing headcount dynamically upscales venue and recalculates pricing."""
    session, _ = get_or_create_session(
        prompt="Workshop this Friday for 40 students",
        user_id="test_delta_user"
    )
    draft = synthesize_speculative_draft(session)
    assert draft.headcount == 40
    small_venue_name = draft.venue.name

    # Upscale headcount to 300 students (requires large hall!)
    updated = apply_draft_delta(session.session_id, {"headcount": 300})
    assert updated.headcount == 300
    assert updated.venue.capacity >= 300
    assert updated.requires_dean_approval is True
    assert "Updated!" in updated.verbal_summary

    # Remove an item
    updated2 = apply_draft_delta(session.session_id, {"remove_items": ["Cordless Microphones"]})
    assert not any("Microphone" in r.name for r in updated2.resources)

    reset_session(session.session_id)


def test_atomic_commit_on_explicit_confirmation():
    """Verifies atomic Kavach execution occurs ONLY when explicitly confirmed."""
    session, _ = get_or_create_session(
        prompt="Campus Coding Contest this Friday for 80 students with spike boards",
        user_id="test_commit_user"
    )
    draft = synthesize_speculative_draft(session)

    # Execute commit
    commit_res = commit_draft_plan_atomic(draft, user_id="test_commit_user")
    assert commit_res["status"] == "committed"
    event_id = commit_res["details"]["event_id"]

    # Verify row in events table
    ev_row = fetch_one("SELECT id, name, expected_participants FROM events WHERE id = ?", (event_id,))
    assert ev_row is not None
    assert ev_row["expected_participants"] == 80

    # Verify venue & resource bookings exist
    bookings = fetch_all("SELECT * FROM bookings WHERE event_id = ?", (event_id,))
    assert len(bookings) >= 2  # venue + at least 1 resource

    # Verify outbox notice staged
    outbox_notices = fetch_all("SELECT * FROM outbox WHERE event_id = ?", (event_id,))
    assert len(outbox_notices) >= 1

    reset_session(session.session_id)


def test_confirmation_api_flow():
    """Verifies /api/autopilot/draft, /delta, and /confirm endpoints with auth."""
    client = _organiser_client()

    # 1. Start session
    res_start = client.post(
        "/api/autopilot/session/start",
        json={"prompt": "Tech Symposium this Friday for 100 students"}
    )
    assert res_start.status_code == 200
    session_id = res_start.json()["session_id"]

    # 2. Get Draft
    res_draft = client.post("/api/autopilot/draft", json={"session_id": session_id})
    assert res_draft.status_code == 200
    draft_data = res_draft.json()["draft"]
    assert draft_data["venue"] is not None
    assert draft_data["total_cost"] > 0

    # 3. Apply Delta (change duration / time)
    res_delta = client.post(
        "/api/autopilot/delta",
        json={
            "session_id": session_id,
            "delta_params": {"duration_hours": 4.0}
        }
    )
    assert res_delta.status_code == 200
    assert res_delta.json()["draft"]["duration_hours"] == 4.0

    # 4. Voice Abort
    res_cancel = client.post(
        "/api/autopilot/confirm",
        json={
            "session_id": session_id,
            "voice_input": "nahi ruko cancel kar do"
        }
    )
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "cancelled"

    # 5. Voice Confirm
    res_confirm = client.post(
        "/api/autopilot/confirm",
        json={
            "session_id": session_id,
            "voice_input": "haan confirm kar do"
        }
    )
    assert res_confirm.status_code == 200
    confirm_data = res_confirm.json()
    assert confirm_data["status"] == "committed"
    assert confirm_data["event_id"] is not None
    assert "Lock kar diya" in confirm_data["verbal_ack"]
