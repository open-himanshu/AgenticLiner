"""
Unit & Integration Tests for Pillar 6: Autonomous Multi-Stakeholder Notification & Real SMTP Broadcast.
Tests:
1. Executive Dean / Supervisor notification generation (normal vs approval required).
2. Event Manager / Organiser booking confirmation & logistics manifest.
3. Registered student invitation & digital gate pass linking.
4. Tripartite notification bundle synthesis.
5. Transactional outbox persistence and status='sent' recording.
6. Audit log entry generation.
7. REST API endpoint GET /api/autopilot/outbox/{event_id}.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner.notification_engine import (
    build_dean_notification,
    build_organiser_notification,
    build_student_notifications,
    generate_all_stakeholder_notifications,
    dispatch_stakeholder_notifications,
    get_event_outbox_notices,
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


def test_dean_notification_auto_approved():
    """Verifies executive Dean briefing for standard auto-approved campus events."""
    notif = build_dean_notification(
        event_id="ev_test_01",
        event_name="Galgotias AI Workshop",
        event_type="workshop",
        target_date="2026-11-20",
        start_time="10:00:00",
        end_time="13:00:00",
        venue_name="Seminar Hall 1",
        headcount=100,
        total_cost=8500.0,
        requires_dean_approval=False
    )
    assert notif.stakeholder_type == "dean"
    assert notif.recipient_email == "admin@galgotias.edu"
    assert "[Campus Briefing]" in notif.subject
    assert notif.requires_action is False
    assert "Seminar Hall 1" in notif.summary
    assert "/supervisor" in notif.action_url
    assert "Rs. 8,500" in notif.body_html or "8500" in notif.body_html


def test_dean_notification_approval_required():
    """Verifies Dean notification flags approval requirement for high-impact venues."""
    notif = build_dean_notification(
        event_id="ev_test_02",
        event_name="Technojam Annual Gala",
        event_type="cultural",
        target_date="2026-11-28",
        start_time="14:00:00",
        end_time="18:00:00",
        venue_name="Main Auditorium A",
        headcount=450,
        total_cost=25000.0,
        requires_dean_approval=True,
        dean_reasons=["Venue 'Main Auditorium A' requires special Dean sign-off."]
    )
    assert notif.stakeholder_type == "dean"
    assert "[Action Required: Dean Approval]" in notif.subject
    assert notif.requires_action is True
    assert "Main Auditorium A" in notif.body_text
    assert "special Dean sign-off" in notif.body_text


def test_organiser_notification_receipt():
    """Verifies detailed logistics manifest and timetable link for Event Manager."""
    notif = build_organiser_notification(
        event_id="ev_test_03",
        event_name="RoboWars Hackathon",
        event_type="hackathon",
        target_date="2026-11-25",
        start_time="09:00:00",
        end_time="17:00:00",
        venue_name="Seminar Hall 2",
        headcount=120,
        total_cost=14200.0,
        booked_items=[
            "Heavy Duty Extension Spike Boards",
            "Ultra HD 4K Laser Projector",
            "Wireless Handheld Mic Set (Pair)"
        ]
    )
    assert notif.stakeholder_type == "organiser"
    assert notif.recipient_email == "organiser@galgotias.edu"
    assert "Booking Confirmed" in notif.subject
    assert "RoboWars Hackathon" in notif.subject
    assert "/schedule" in notif.action_url
    assert "Extension Spike Boards" in notif.body_text
    assert "Laser Projector" in notif.body_html


def test_student_notifications_pass_link():
    """Verifies campus student invitations with digital QR pass claim link."""
    notifs = build_student_notifications(
        event_id="ev_test_04",
        event_name="Cloud AI Bootcamp",
        event_type="workshop",
        target_date="2026-11-22",
        start_time="11:00:00",
        end_time="14:00:00",
        venue_name="Executive Conference Room B",
        limit=3
    )
    assert len(notifs) >= 1
    for n in notifs:
        assert n.stakeholder_type == "student"
        assert "@" in n.recipient_email and ("galgotias" in n.recipient_email.lower())
        assert "Campus Invitation: Cloud AI Bootcamp" in n.subject
        assert "/participant?event_id=ev_test_04" in n.action_url


def test_generate_all_and_dispatch_outbox():
    """Verifies full multi-stakeholder dispatch persists in outbox and audit_log."""
    event_id = "ev_test_05"
    all_notifs = generate_all_stakeholder_notifications(
        event_id=event_id,
        event_name="Grand Campus Fest",
        event_type="cultural",
        target_date="2026-11-29",
        start_time="15:00:00",
        end_time="20:00:00",
        venue_name="Main Auditorium A",
        headcount=300,
        total_cost=18000.0,
        booked_items=["JBL High-Power Sound & PA System", "Stage LED Lighting"],
        requires_dean_approval=True,
        dean_reasons=["Auditorium A special approval"]
    )
    # Tripartite check: 1 dean, 1 organiser, >= 1 student
    types = [n.stakeholder_type for n in all_notifs]
    assert types.count("dean") == 1
    assert types.count("organiser") == 1
    assert types.count("student") >= 1

    # Dispatch to outbox table
    dispatch_res = dispatch_stakeholder_notifications(
        event_id=event_id,
        notifications=all_notifs,
        send_real_smtp=False
    )
    assert dispatch_res["success"] is True
    assert dispatch_res["total_dispatched"] == len(all_notifs)
    assert dispatch_res["stakeholders_notified"]["dean"] == 1
    assert dispatch_res["stakeholders_notified"]["organiser"] == 1
    assert dispatch_res["stakeholders_notified"]["students"] >= 1

    # Verify rows in SQLite outbox table
    outbox_rows = fetch_all("SELECT * FROM outbox WHERE event_id = ?", (event_id,))
    assert len(outbox_rows) == len(all_notifs)
    for r in outbox_rows:
        assert r["status"] == "sent"

    # Verify audit_log entry
    audit_row = fetch_one(
        "SELECT * FROM audit_log WHERE event_id = ? AND action = 'STAKEHOLDER_BROADCAST'",
        (event_id,)
    )
    assert audit_row is not None
    assert audit_row["result"] == "SUCCESS"


def test_outbox_api_endpoint():
    """Verifies GET /api/autopilot/outbox/{event_id} returns all dispatched notices."""
    client = _organiser_client()

    event_id = "ev_test_06"
    notifs = generate_all_stakeholder_notifications(
        event_id=event_id,
        event_name="Research Paper Presentation",
        event_type="seminar",
        target_date="2026-11-30",
        start_time="10:00:00",
        end_time="12:00:00",
        venue_name="Seminar Hall 1",
        headcount=60,
        total_cost=3000.0,
        booked_items=["Ultra HD 4K Laser Projector"]
    )
    dispatch_stakeholder_notifications(event_id=event_id, notifications=notifs, send_real_smtp=False)

    res = client.get(f"/api/autopilot/outbox/{event_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["event_id"] == event_id
    assert len(data["outbox"]) >= 3
    recipients = [o["recipient"] for o in data["outbox"]]
    assert "admin@galgotias.edu" in recipients
    assert "organiser@galgotias.edu" in recipients
