"""
Tests for Event Unbooking/Cancellation and Deletion workflows.
Verifies that organisers can cancel or permanently delete accidental bookings,
freeing the venue, returning stock, cancelling held notices, and logging audit entries.
"""

from __future__ import annotations

import pytest
import httpx

from backend.api.main import app
from backend.core.database.connection import fetch_one, fetch_all, execute_query
from backend.core.database.init_db import init_database, seed_campus_data
from backend.services.seed_users import seed_users
from backend.services.event_workflow_service import (
    create_event_request,
    approve_event_by_supervisor,
    cancel_event,
    delete_event,
)
from backend.core.planner.tools import tool_find_free_venues
from conftest import TEST_PASSWORDS


@pytest.fixture(autouse=True)
def isolated_seeded_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test_cancel_delete.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    init_database()
    seed_campus_data()
    seed_users(force=True)
    return db_path


def test_cancel_event_frees_venue_and_restores_resource_stock():
    # 1. Create and approve an event in room_audi_b with 2 LED lights
    req = create_event_request(
        name="Mistaken Dance Rehearsal",
        brief="Test event booked by mistake",
        event_type="cultural",
        expected_participants=80,
        organizer_department="Cultural Club",
        organizer_email="organiser@galgotias.edu",
        room_id="room_audi_b",
        start_time="2026-11-20 14:00:00",
        end_time="2026-11-20 17:00:00",
        requisitions=[{"resource_id": "res_led_lights", "quantity": 2, "item_name": "LED Lights"}],
        budget=15000,
    )
    event_id = req["event_id"]

    # Approve to allocate stock
    approve_event_by_supervisor(event_id, supervisor_email="admin@galgotias.edu")

    # Verify venue is currently NOT free
    free_venues_before = tool_find_free_venues(50, "2026-11-20", "14:00:00", "17:00:00")
    room_ids_before = [v["id"] for v in free_venues_before["venues"]]
    assert "room_audi_b" not in room_ids_before

    # Verify resource allocated_stock
    res_stock_before = fetch_one("SELECT allocated_stock FROM resources WHERE id = 'res_led_lights'")["allocated_stock"]
    assert res_stock_before >= 2

    # 2. Organiser cancels the event
    cancel_res = cancel_event(event_id, actor_email="organiser@galgotias.edu", reason="Accidental booking")
    assert cancel_res["success"] is True

    # 3. Verify event and bookings flipped to cancelled
    ev = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    assert ev["status"] == "cancelled"
    assert ev["approval_status"] == "cancelled"

    bookings = fetch_all("SELECT * FROM bookings WHERE event_id = ?", (event_id,))
    for b in bookings:
        assert b["status"] == "cancelled"

    # 4. Verify venue is immediately free again
    free_venues_after = tool_find_free_venues(50, "2026-11-20", "14:00:00", "17:00:00")
    room_ids_after = [v["id"] for v in free_venues_after["venues"]]
    assert "room_audi_b" in room_ids_after

    # 5. Verify allocated_stock is restored
    res_stock_after = fetch_one("SELECT allocated_stock FROM resources WHERE id = 'res_led_lights'")["allocated_stock"]
    assert res_stock_after == res_stock_before - 2

    # 6. Verify audit log
    audit = fetch_one("SELECT * FROM audit_log WHERE event_id = ? AND action = 'EVENT_CANCELLED'", (event_id,))
    assert audit is not None
    assert audit["actor"] == "organiser@galgotias.edu"


def test_delete_event_purges_accidental_booking_completely():
    # 1. Create an event
    req = create_event_request(
        name="Wrong Club Meet",
        brief="Created in error",
        event_type="workshop",
        expected_participants=50,
        organizer_department="Robotics Club",
        organizer_email="organiser@galgotias.edu",
        room_id="room_audi_b",
        start_time="2026-11-21 10:00:00",
        end_time="2026-11-21 12:00:00",
        requisitions=[],
        budget=5000,
    )
    event_id = req["event_id"]

    # 2. Delete the event completely
    del_res = delete_event(event_id, actor_email="organiser@galgotias.edu")
    assert del_res["success"] is True

    # 3. Verify event and associated rows are purged
    assert fetch_one("SELECT * FROM events WHERE id = ?", (event_id,)) is None
    assert len(fetch_all("SELECT * FROM bookings WHERE event_id = ?", (event_id,))) == 0
    assert len(fetch_all("SELECT * FROM outbox WHERE event_id = ?", (event_id,))) == 0

    # 4. Verify room is free
    free_venues = tool_find_free_venues(50, "2026-11-21", "10:00:00", "12:00:00")
    assert "room_audi_b" in [v["id"] for v in free_venues["venues"]]

    # 5. Verify audit log
    audit = fetch_one("SELECT * FROM audit_log WHERE event_id = ? AND action = 'EVENT_DELETED'", (event_id,))
    assert audit is not None


@pytest.mark.anyio
async def test_api_cancel_and_delete_endpoints():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as organiser
        login = await client.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        assert login.status_code in (200, 302)

        # Create event via API
        create_resp = await client.post(
            "/api/events/plan",
            json={
                "name": "API Created Event",
                "brief": "Will be cancelled then deleted",
                "event_type": "cultural",
                "expected_participants": 50,
                "room_id": "room_audi_b",
                "start_time": "2026-11-22 10:00:00",
                "end_time": "2026-11-22 12:00:00",
                "budget": 10000,
            },
        )
        assert create_resp.status_code == 200
        event_id = create_resp.json()["event_id"]

        # Cancel event via API
        cancel_resp = await client.post(
            f"/api/events/{event_id}/cancel",
            json={"reason": "Testing cancellation"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["success"] is True

        # Delete event via API
        delete_resp = await client.post(
            f"/api/events/{event_id}/delete",
        )
        assert delete_resp.status_code == 200
        assert delete_resp.json()["success"] is True

        # Verify event is gone
        assert fetch_one("SELECT * FROM events WHERE id = ?", (event_id,)) is None

        # Verify organiser dashboard loads cleanly with Cancel and Delete buttons
        dash_resp = await client.get("/organiser")
        assert dash_resp.status_code == 200
        assert "Unbook / Cancel Event" in dash_resp.text or "Cancel" in dash_resp.text
        assert "Delete Accidental Booking" in dash_resp.text or "Delete" in dash_resp.text
