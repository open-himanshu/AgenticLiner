"""
Unit & Integration Tests for Pillar 3: Organiser Memory & Persistent Preference Store.
Tests memory persistence, rolling preference learning, explicit fact extraction,
entity enrichment, multi-user isolation, and the memory API endpoints.
"""

import pytest
from datetime import date as CalendarDate
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner.memory_store import (
    OrganiserMemoryProfile,
    get_organiser_memory,
    save_organiser_memory,
    reset_organiser_memory,
    add_memory_note,
)
from backend.core.planner.memory_engine import (
    record_committed_event,
    extract_explicit_memory_facts,
    enrich_entities_with_organiser_memory,
    get_memory_badge_summary,
)
from backend.core.planner.natural_intake import ExtractedEventEntities
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


def test_memory_store_lifecycle():
    """Verifies retrieval, persistence, and safe reset of organiser memory profile."""
    test_user = "test_organiser_alpha@galgotias.edu"
    reset_organiser_memory(test_user)

    # 1. Fresh profile defaults
    prof = get_organiser_memory(test_user)
    assert prof.user_id == test_user
    assert prof.total_events_planned == 0
    assert prof.typical_headcount == 100
    assert prof.favourite_venues == []

    # 2. Update and save
    prof.typical_headcount = 140
    prof.favourite_venues = [{"venue": "Auditorium A", "count": 3}]
    prof.favourite_equipment = ["Cordless Microphones"]
    save_organiser_memory(prof)

    # 3. Reload from DB
    reloaded = get_organiser_memory(test_user)
    assert reloaded.typical_headcount == 140
    assert len(reloaded.favourite_venues) == 1
    assert reloaded.favourite_venues[0]["venue"] == "Auditorium A"

    # 4. Clean up
    reset_organiser_memory(test_user)
    fresh = get_organiser_memory(test_user)
    assert fresh.total_events_planned == 0
    assert fresh.favourite_venues == []


def test_record_committed_event_learning():
    """Verifies that committing events updates venue count, rolling headcount, and gear."""
    test_user = "test_learner@galgotias.edu"
    reset_organiser_memory(test_user)

    # Event 1: 150 students in Hall 1
    p1 = record_committed_event(
        user_id=test_user,
        event_name="AI Summit 2026",
        venue_name="Auditorium A",
        headcount=150,
        equipment_items=["Cordless Microphones", "Extension Power Strips"],
        target_date="2026-11-20"  # A Friday
    )
    assert p1.total_events_planned == 1
    assert p1.typical_headcount == 150
    assert p1.favourite_venues[0]["venue"] == "Auditorium A"
    assert p1.favourite_venues[0]["count"] == 1
    assert "Cordless Microphones" in p1.favourite_equipment

    # Event 2: 90 students in Auditorium A again
    p2 = record_committed_event(
        user_id=test_user,
        event_name="Robotics Workshop",
        venue_name="Auditorium A",
        headcount=90,
        equipment_items=["High-Power Sound System"],
        target_date="2026-11-27"
    )
    assert p2.total_events_planned == 2
    # Rolling headcount should adjust between 90 and 150
    assert 90 < p2.typical_headcount < 150
    assert p2.favourite_venues[0]["count"] == 2
    assert "High-Power Sound System" in p2.favourite_equipment

    reset_organiser_memory(test_user)


def test_enrich_entities_with_organiser_memory():
    """Verifies that incomplete prompt entities are enriched with organiser's past habits."""
    test_user = "test_enricher@galgotias.edu"
    reset_organiser_memory(test_user)

    # Seed past memory
    prof = get_organiser_memory(test_user)
    prof.total_events_planned = 2
    prof.typical_headcount = 135
    prof.favourite_venues = [{"venue": "Seminar Hall 1", "count": 2}]
    prof.favourite_equipment = ["Cordless Microphones", "Stage LED Lighting"]
    save_organiser_memory(prof)

    # Vague prompt missing headcount and equipment
    vague_entities = ExtractedEventEntities(
        raw_prompt="Campus workshop karwana hai",
        event_name="Campus Workshop",
        event_type="workshop",
        estimated_headcount=None,
        scale_category="unknown",
        target_date="2026-11-28",
        missing_critical_fields=["headcount", "scale"]
    )

    enriched, assumptions = enrich_entities_with_organiser_memory(vague_entities, test_user)

    # Headcount should be auto-filled from memory
    assert enriched.estimated_headcount == 135
    assert enriched.scale_category == "medium"
    assert "headcount" not in enriched.missing_critical_fields
    assert any("turnout" in a.lower() for a in assumptions)
    assert "Cordless Microphones" in enriched.requested_items

    reset_organiser_memory(test_user)


def test_extract_explicit_memory_facts():
    """Verifies that explicit statements like 'we always need microphones' are stored as notes."""
    test_user = "test_facts@galgotias.edu"
    reset_organiser_memory(test_user)

    prompt = "We always require cordless microphones and buffet lunch for our tech seminars"
    facts = extract_explicit_memory_facts(test_user, prompt)

    assert len(facts) >= 1
    prof = get_organiser_memory(test_user)
    assert len(prof.memory_notes) >= 1
    assert any("cordless microphone" in n.lower() for n in prof.memory_notes)

    reset_organiser_memory(test_user)


def test_memory_isolation_between_organisers():
    """Verifies strict isolation: Organiser A's memories cannot contaminate Organiser B."""
    user_a = "user_a@galgotias.edu"
    user_b = "user_b@galgotias.edu"
    reset_organiser_memory(user_a)
    reset_organiser_memory(user_b)

    # User A records preferences
    record_committed_event(
        user_id=user_a,
        event_name="Cultural Gala",
        venue_name="Open Air Theatre",
        headcount=450
    )

    prof_a = get_organiser_memory(user_a)
    prof_b = get_organiser_memory(user_b)

    assert prof_a.typical_headcount == 450
    assert prof_a.favourite_venues[0]["venue"] == "Open Air Theatre"

    # User B must remain at defaults
    assert prof_b.total_events_planned == 0
    assert prof_b.typical_headcount == 100
    assert prof_b.favourite_venues == []

    reset_organiser_memory(user_a)
    reset_organiser_memory(user_b)


def test_memory_api_endpoints():
    """Verifies GET /api/autopilot/memory, POST note, and POST reset endpoints with auth."""
    client = _organiser_client()

    # 1. GET memory
    res_get = client.get("/api/autopilot/memory")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["success"] is True
    assert "profile" in data_get
    assert "badge" in data_get

    # 2. POST note
    res_note = client.post(
        "/api/autopilot/memory/note",
        json={"note": "Always require high-speed WiFi for developer hackathons."}
    )
    assert res_note.status_code == 200
    data_note = res_note.json()
    assert data_note["success"] is True
    assert any("WiFi" in n for n in data_note["profile"]["memory_notes"])

    # 3. POST reset
    res_reset = client.post("/api/autopilot/memory/reset")
    assert res_reset.status_code == 200
    data_reset = res_reset.json()
    assert data_reset["success"] is True

    # Check that profile is back to clean defaults
    res_verify = client.get("/api/autopilot/memory")
    assert res_verify.json()["profile"]["memory_notes"] == []
