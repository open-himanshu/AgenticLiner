"""
Phase 8: Tests for Google OR-Tools CP-SAT Scheduler, Dynamic Speaker Reallocation,
2D Room-Slot Grid Matrix, and CSV Export.
"""

import pytest
from fastapi.testclient import TestClient
from conftest import TEST_PASSWORDS
from backend.api.main import app
from backend.services.schedule_service import (
    solve_timetable,
    handle_hero_speaker_cancellation,
    export_schedule_csv,
    get_scheduling_rooms
)
from backend.core.database.demo_people import HERO_SPEAKER
from backend.core.database.connection import fetch_one, fetch_all
from backend.core.safety.kavach import KavachEngine, InvariantViolation

@pytest.fixture
def client():
    return TestClient(app)

def test_get_scheduling_rooms():
    rooms = get_scheduling_rooms()
    assert len(rooms) >= 2
    for r in rooms:
        assert "id" in r
        assert "name" in r
        assert "capacity" in r
        assert r["capacity"] > 0

def test_solve_timetable():
    result = solve_timetable()
    assert result["success"] is True
    assert result["status"] in ["OPTIMAL", "FEASIBLE"]
    assert len(result["schedule"]) == 4
    assert "grid_matrix" in result
    assert len(result["grid_matrix"]) == 4  # 4 slots
    assert "rooms" in result
    assert result["total_seats_used"] > 0
    assert result["seat_occupancy_rate"] > 0

    # Ensure no room has two sessions in the same slot
    seen_slots_rooms = set()
    for s in result["schedule"]:
        pair = (s["slot_index"], s["room_id"])
        assert pair not in seen_slots_rooms, f"Room clash detected at slot {s['slot_index']} room {s['room_id']}"
        seen_slots_rooms.add(pair)

def test_handle_hero_speaker_cancellation():
    result = handle_hero_speaker_cancellation()
    assert result["status"] == "re_planned"
    assert result["action"] == "SPEAKER_CANCELLATION_HANDLED"
    assert result["original_speaker"] == HERO_SPEAKER["name"]
    assert "substitute_allocated" in result
    assert result["substitute_allocated"] == (
        f"{HERO_SPEAKER['substitute_name']} "
        f"({HERO_SPEAKER['substitute_department']})"
    )
    assert len(result["new_schedule"]) == 4
    assert "grid_matrix" in result
    
    # Check that outbox entry was staged as held
    outbox_id = result["staged_outbox_notice"]["id"]
    row = fetch_one("SELECT * FROM outbox WHERE id = ?", (outbox_id,))
    assert row is not None
    assert row["status"] == "held"
    assert HERO_SPEAKER["name"] in row["message"] or "Substitute" in row["subject"]


def test_hero_schedule_change_notice_rolls_back_when_blast_radius_is_exceeded(monkeypatch):
    from backend.services import schedule_service

    before = len(fetch_all(
        "SELECT id FROM outbox WHERE event_id = 'ev_001' AND type = 'schedule_change'"
    ))
    monkeypatch.setattr(
        schedule_service, "kavach", KavachEngine(max_blast_radius=1)
    )

    with pytest.raises(InvariantViolation) as exc_info:
        handle_hero_speaker_cancellation(event_id="ev_001")

    assert exc_info.value.rule == "blast_radius_exceeded"
    after = len(fetch_all(
        "SELECT id FROM outbox WHERE event_id = 'ev_001' AND type = 'schedule_change'"
    ))
    assert after == before


def test_export_schedule_csv():
    res = solve_timetable()
    csv_str = export_schedule_csv(res["schedule"])
    assert "Slot Time,Session Title,Allocated Venue,Speaker" in csv_str
    assert "Opening Keynote" in csv_str
    assert "Generative AI Systems Masterclass" in csv_str

def test_api_schedule_endpoints(client):
    login = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert login.status_code == 200
    # 1. POST /api/schedule/solve
    res1 = client.post("/api/schedule/solve", json={})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True
    assert len(data1["schedule"]) == 4
    assert "grid_matrix" in data1

    # 2. POST /api/schedule/hero-speaker-cancel
    res2 = client.post("/api/schedule/hero-speaker-cancel")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "re_planned"
    assert data2["original_speaker"] == HERO_SPEAKER["name"]

    # 3. GET /api/schedule/export.csv
    res3 = client.get("/api/schedule/export.csv")
    assert res3.status_code == 200
    assert "text/csv" in res3.headers["content-type"]
    assert "attachment; filename=timetable_export.csv" in res3.headers["content-disposition"]
    assert "Session Title" in res3.text

def test_schedule_page_render(client):
    # 1. Unauthenticated request should be rejected / redirected
    unauth = client.get("/schedule")
    assert unauth.status_code in [401, 307]

    # 2. Login as organiser
    login_res = client.post("/login", json={
        "email": "organiser@galgotias.edu",
        "password": TEST_PASSWORDS["ORGANISER_PASSWORD"]
    })
    assert login_res.status_code in [200, 302]

    # 3. Authenticated GET /schedule HTML view
    res = client.get("/schedule")
    assert res.status_code == 200
    assert "Intelligent Timetable Scheduler & Conflict Solver" in res.text
    assert "Google OR-Tools CP-SAT" in res.text
    assert "2D Venue &times; Slot Matrix" in res.text
    assert "Hero Demo: Speaker Cancels" in res.text
    assert f"Speaker Cancelled: {HERO_SPEAKER['name']}" in res.text
    assert f"Speaker: {HERO_SPEAKER['name']} (Associate Prof)" in res.text
