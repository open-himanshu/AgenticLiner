"""
Tests for Supervisor Dashboard Complete Event Information & Monitoring.
Verifies that the Supervisor Dashboard properly displays all events (including auto_approved),
renders rich event details (venue, schedule, resources, attendees, organizers),
and provides comprehensive search, filtering, and inspection views.
"""

from __future__ import annotations

import pytest
import httpx

from backend.api.main import app
from backend.core.database.connection import execute_query, fetch_one, fetch_all
from backend.core.database.init_db import init_database, seed_campus_data
from backend.services.seed_users import seed_users
from backend.services.event_workflow_service import create_event_request, approve_event_by_supervisor
from conftest import TEST_PASSWORDS


@pytest.fixture(autouse=True)
def isolated_seeded_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_supervisor_dashboard.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    init_database()
    seed_campus_data()
    seed_users(force=True)
    return db_path


@pytest.mark.anyio
async def test_supervisor_dashboard_displays_all_events_including_auto_approved():
    # 1. We have seeded event ev_001 ('Galgotias Campus Innovation Hackathon 2026') which is auto_approved.
    # 2. Create another event requiring Dean approval in room_audi_a
    req_pending = create_event_request(
        name="Annual Leadership Summit 2026",
        brief="Mega conference in Main Audi A requiring Dean sign-off",
        event_type="seminar",
        expected_participants=250,
        organizer_department="School of Management",
        organizer_email="management@galgotias.edu",
        room_id="room_audi_a",
        start_time="2026-11-28 09:00:00",
        end_time="2026-11-28 17:00:00",
        requisitions=[{"resource_id": "res_sound_jbl", "quantity": 1, "item_name": "JBL Sound"}],
        budget=40000,
    )
    pending_id = req_pending["event_id"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as supervisor
        login = await client.post(
            "/login",
            data={
                "email": "admin@galgotias.edu",
                "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
            },
        )
        assert login.status_code in (200, 302)

        # GET /supervisor dashboard
        res = await client.get("/supervisor")
        assert res.status_code == 200
        html = res.text

        # The auto-approved event (ev_001) MUST be visible on the dashboard!
        assert "Galgotias Campus Innovation Hackathon 2026" in html
        assert "ev_001" in html

        # Active / Approved events stat MUST NOT be 0 (ev_001 is auto_approved active event)
        assert 'id="statActiveEvents">0<' not in html

        # The pending event MUST also be visible in the approval section
        assert "Annual Leadership Summit 2026" in html
        assert pending_id in html


@pytest.mark.anyio
async def test_event_details_api_returns_complete_event_information():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as supervisor
        await client.post(
            "/login",
            data={
                "email": "admin@galgotias.edu",
                "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
            },
        )

        # Fetch details for ev_001
        res = await client.get("/api/events/ev_001")
        assert res.status_code == 200
        data = res.json()

        # Must contain complete meaningful event information
        assert "event" in data
        event = data["event"]
        assert event["id"] == "ev_001"
        assert event["name"] == "Galgotias Campus Innovation Hackathon 2026"
        assert event["event_type"] == "hackathon"
        assert event["expected_participants"] >= 100

        # Venue / logistics details
        assert "venue" in data or "bookings" in data

        # Sessions / agenda details
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
        assert len(data["sessions"]) > 0
        session_0 = data["sessions"][0]
        assert "title" in session_0
        assert "start_time" in session_0
        assert "speaker_name" in session_0

        # Attendees & Outbox
        assert "confirmed_attendees" in data
        assert "outbox" in data


@pytest.mark.anyio
async def test_supervisor_dashboard_search_and_filtering():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/login",
            data={
                "email": "admin@galgotias.edu",
                "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
            },
        )

        # Filter: approved / active
        res_approved = await client.get("/supervisor?filter=approved")
        assert res_approved.status_code == 200
        assert "Galgotias Campus Innovation Hackathon 2026" in res_approved.text

        # Search: query matching Innovation
        res_search = await client.get("/supervisor?search=Innovation")
        assert res_search.status_code == 200
        assert "Galgotias Campus Innovation Hackathon 2026" in res_search.text

        # Search: non-matching query
        res_empty = await client.get("/supervisor?search=NonExistentFestXYZ")
        assert res_empty.status_code == 200
        assert "Galgotias Campus Innovation Hackathon 2026" not in res_empty.text
