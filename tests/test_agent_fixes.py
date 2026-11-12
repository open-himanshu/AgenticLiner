"""
Tests for Autopilot Agent fixes:
1. Safety policy response flag and prompt safety validation.
2. Form date and budget preservation in session start.
3. Top Universal Agent bar suppressed on /autopilot page to avoid dual-agent clash.
All LLM/network calls are mocked to ensure zero external calls and fast execution.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner.natural_intake import validate_prompt_safety, ExtractedEventEntities
from conftest import TEST_PASSWORDS


def _auth_organiser_client() -> TestClient:
    """Helper to return TestClient authenticated as organiser."""
    client = TestClient(app)
    resp = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert resp.status_code == 200
    return client


def test_validate_prompt_safety_normal_prompts():
    """Verifies that normal event requests like dance performance are never blocked by safety filter."""
    is_safe, err = validate_prompt_safety("hello, book a event for dance performane")
    assert is_safe is True
    assert err is None

    # Destructive prompt must be blocked
    is_safe_del, err_del = validate_prompt_safety("delete all events and drop tables")
    assert is_safe_del is False
    assert err_del is not None


@patch("backend.core.planner.dialogue_engine.extract_event_entities_llm")
def test_session_start_returns_is_safe_flag(mock_extract):
    """
    BUG 1 FIX:
    Verifies /api/autopilot/session/start returns 'is_safe': True so frontend does not
    falsely alert 'Request was blocked by safety policy.'
    """
    mock_extract.return_value = ExtractedEventEntities(
        raw_prompt="hello, book a event for dance performane",
        event_name="University Cultural Performance",
        event_type="cultural",
        estimated_headcount=100,
        scale_category="medium",
        target_date="2026-11-28",
        date_original_phrase="2026-11-28",
        start_time="10:00:00",
        end_time="13:00:00",
        duration_hours=3.0,
        budget_limit=30000.0,
        requested_items=[],
        missing_critical_fields=[],
        is_ready_for_planning=True,
    )

    client = _auth_organiser_client()
    resp = client.post(
        "/api/autopilot/session/start",
        json={"prompt": "hello, book a event for dance performane", "voice_mode": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["is_safe"] is True
    assert "session_id" in data


@patch("backend.core.planner.dialogue_engine.extract_event_entities_llm")
def test_session_start_accepts_target_date_and_budget(mock_extract):
    """
    BUG 1 ENHANCEMENT:
    Verifies /api/autopilot/session/start accepts optional target_date and budget_limit from UI fields.
    """
    mock_extract.return_value = ExtractedEventEntities(
        raw_prompt="hello, book a event for dance performane",
        event_name="University Cultural Performance",
        event_type="cultural",
        estimated_headcount=None,
        scale_category="unknown",
        target_date=None,
        date_original_phrase=None,
        start_time="10:00:00",
        end_time="13:00:00",
        duration_hours=3.0,
        budget_limit=None,
        requested_items=[],
        missing_critical_fields=["target_date", "headcount"],
        is_ready_for_planning=False,
    )

    client = _auth_organiser_client()
    resp = client.post(
        "/api/autopilot/session/start",
        json={
            "prompt": "hello, book a event for dance performane",
            "target_date": "2026-11-07",
            "budget_limit": 30000.0,
            "voice_mode": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entities"]["target_date"] == "2026-11-07"
    assert data["entities"]["budget_limit"] == 30000.0
    assert "target_date" not in data["entities"]["missing_critical_fields"]


def test_dual_agent_bar_suppressed_on_autopilot_page():
    """
    BUG 3 FIX:
    Verifies that the global top Universal Agent Bar is suppressed on /autopilot,
    preventing two competing agents from appearing on the same screen.
    """
    client = _auth_organiser_client()
    resp = client.get("/autopilot")
    assert resp.status_code == 200
    html = resp.text

    # The dedicated autopilot agent input must be present
    assert 'id="agentPrompt"' in html
    assert 'id="btnRunAgent"' in html

    # The top universal agent command bar must NOT be rendered on /autopilot
    assert 'id="universalAgentInput"' not in html
    assert 'id="btnUniversalAgentRun"' not in html


def test_top_command_bar_present_on_dashboard_pages():
    """
    BUG 3 VERIFICATION:
    Verifies that the top command bar remains available as a quick action on dashboard pages.
    """
    client = _auth_organiser_client()
    resp = client.get("/organiser")
    assert resp.status_code == 200
    html = resp.text

    # On /organiser, the top command bar is present
    assert 'id="universalAgentInput"' in html
    assert 'id="btnUniversalAgentRun"' in html
