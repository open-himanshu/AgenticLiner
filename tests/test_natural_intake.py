"""
Unit & Integration Tests for Pillar 1 - Section 2: Natural Intake & Entity Extraction Engine.
Tests safety guard, relative calendar & time resolution, LLM/deterministic parsing,
counter-question formulation, and the /api/autopilot/parse-intent endpoint.
"""

from datetime import date as CalendarDate, timedelta
import pytest
import httpx
from backend.api.main import app
from backend.core.planner.natural_intake import (
    validate_prompt_safety,
    resolve_natural_datetime,
    _extract_entities_deterministic,
    extract_event_entities_llm,
    assess_intake_completeness,
    ExtractedEventEntities,
)

def test_validate_prompt_safety_blocks_destructive():
    """Verifies that malicious or destructive mass-deletion prompts are caught."""
    safe, err = validate_prompt_safety("cancel all bookings right now")
    assert safe is False
    assert "Destructive" in err

    safe, err = validate_prompt_safety("delete every single event")
    assert safe is False

    safe, err = validate_prompt_safety("drop table bookings")
    assert safe is False

    safe, err = validate_prompt_safety("Organise a 2-day hackathon for 150 students")
    assert safe is True
    assert err is None


def test_resolve_natural_datetime_relative_days():
    """Verifies resolution of relative date expressions like tomorrow, Friday, kal shaam."""
    ref = CalendarDate(2026, 11, 2) # A Monday
    
    # Tomorrow / Kal
    t_date, _, _, _ = resolve_natural_datetime("tomorrow", ref_date=ref)
    assert t_date == "2026-11-03"

    k_date, s_time, _, _ = resolve_natural_datetime("kal shaam", "6 baje", ref_date=ref)
    assert k_date == "2026-11-03"
    assert s_time == "18:00:00"

    # This Friday
    f_date, _, _, _ = resolve_natural_datetime("this Friday", ref_date=ref)
    assert f_date == "2026-11-06" # Friday following Monday Nov 2

    # Specific date e.g. 28 Nov
    spec_date, _, _, _ = resolve_natural_datetime("28 Nov", ref_date=ref)
    assert spec_date == "2026-11-28"


def test_resolve_natural_datetime_times():
    """Verifies start & end time resolution for morning, evening, specific hours."""
    ref = CalendarDate(2026, 11, 2)
    _, s1, e1, _ = resolve_natural_datetime("evening", "6 PM", ref_date=ref)
    assert s1 == "18:00:00"

    _, s2, e2, _ = resolve_natural_datetime("morning", "10 AM", ref_date=ref)
    assert s2 == "10:00:00"

    _, s3, e3, dur = resolve_natural_datetime("afternoon", "dopahar", ref_date=ref)
    assert s3 == "14:00:00"
    assert dur == 3.0


def test_deterministic_extractor_clean_hackathon():
    """Verifies rule-based entity extraction on standard clean brief."""
    prompt = "Organize a 2-day campus AI hackathon for 150 students on Friday with stage mics and budget 20000"
    entities = _extract_entities_deterministic(prompt)

    assert entities.event_type == "hackathon"
    assert entities.estimated_headcount == 150
    assert entities.budget_limit == 20000.0
    assert "Cordless Microphones" in entities.requested_items
    assert entities.is_ready_for_planning is True


def test_deterministic_extractor_colloquial_hinglish():
    """Verifies parsing of colloquial Hinglish prompts without exact English keywords."""
    prompt = "Kal shaam ko 4 baje 80 bacho ke liye coding workshop book kardo"
    entities = _extract_entities_deterministic(prompt)

    assert entities.event_type in ["hackathon", "workshop"]
    assert entities.estimated_headcount == 80
    assert entities.start_time == "16:00:00"
    assert entities.language_used == "hi"


def test_assess_intake_completeness_missing_fields():
    """Verifies that incomplete prompts trigger targeted clarifying questions."""
    incomplete_entities = ExtractedEventEntities(
        raw_prompt="College me ek dance festival karwana hai",
        event_name="Dance Festival",
        event_type="cultural",
        estimated_headcount=None, # Missing headcount
        target_date=None,         # Missing date
        missing_critical_fields=["target_date", "scale"],
        is_ready_for_planning=False
    )
    is_ready, questions, tts = assess_intake_completeness(incomplete_entities)
    assert is_ready is False
    assert len(questions) >= 1
    assert any("date" in q.lower() for q in questions)
    assert any("participants" in q.lower() or "venue" in q.lower() for q in questions)
    assert "date" in tts.lower()


def _organiser_client():
    from fastapi.testclient import TestClient
    from conftest import TEST_PASSWORDS
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

def test_parse_intent_api_unauthorized():
    """Verifies that /api/autopilot/parse-intent requires authentication."""
    from fastapi.testclient import TestClient
    client = TestClient(app)
    res = client.post(
        "/api/autopilot/parse-intent",
        json={"prompt": "Organise a dance show"}
    )
    assert res.status_code == 401


def test_parse_intent_api_blocks_destructive():
    """Verifies that /api/autopilot/parse-intent blocks destructive queries."""
    client = _organiser_client()
    res = client.post(
        "/api/autopilot/parse-intent",
        json={"prompt": "cancel every single booking in the campus"}
    )
    assert res.status_code == 400
    data = res.json()
    assert data["success"] is False
    assert "Destructive" in data["error"]


def test_parse_intent_api_success():
    """Verifies that /api/autopilot/parse-intent returns structured extraction and completeness."""
    client = _organiser_client()
    res = client.post(
        "/api/autopilot/parse-intent",
        json={"prompt": "Organise a dance performance for 150 students on Friday evening, budget 20,000"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["is_safe"] is True
    entities = data["entities"]
    assert entities["event_type"] == "cultural"
    assert entities["estimated_headcount"] == 150
    assert entities["budget_limit"] == 20000.0
    assert "tts_response" in data
