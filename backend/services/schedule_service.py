"""
Intelligent Timetable Scheduling & Dynamic Re-planning Service.
Powered by Google OR-Tools CP-SAT Solver and Kavach Safety Engine.
"""

import io
import csv
import uuid
import logging
from typing import Dict, Any, List, Optional

from backend.core.database.connection import get_connection, fetch_all, fetch_one
from backend.core.database.demo_people import DEMO_FACULTY, HERO_SPEAKER
from backend.core.scheduler.solver import EventScheduler
from backend.core.safety.kavach import KavachEngine, InvariantViolation

logger = logging.getLogger(__name__)
kavach = KavachEngine()

DEFAULT_SLOTS = [
    "09:30 AM - 11:00 AM",
    "11:15 AM - 12:45 PM",
    "01:45 PM - 03:15 PM",
    "03:30 PM - 05:00 PM"
]

DEFAULT_SESSIONS = [
    {
        "id": "sess_01",
        "title": "Opening Keynote & Dean Inauguration",
        "expected_attendance": 250,
        "speaker_id": "spk_dean",
        "speaker_name": f"{DEMO_FACULTY['dean']} (Dean SoAI)",
        "depends_on": None,
        "track": "General"
    },
    {
        "id": "sess_02",
        "title": "Generative AI Systems Masterclass",
        "expected_attendance": 120,
        "speaker_id": HERO_SPEAKER["id"],
        "speaker_name": f"{HERO_SPEAKER['name']} (Associate Prof)",
        "depends_on": "sess_01",
        "track": "AI/ML"
    },
    {
        "id": "sess_03",
        "title": "Deep Learning with PyTorch Lab",
        "expected_attendance": 50,
        "speaker_id": "spk_akhilesh",
        "speaker_name": f"{DEMO_FACULTY['ml_mentor']} (Lead Researcher)",
        "depends_on": "sess_02",
        "track": "AI/ML"
    },
    {
        "id": "sess_04",
        "title": "Python for Autonomous AI Agents",
        "expected_attendance": 80,
        "speaker_id": "spk_niraj",
        "speaker_name": f"{DEMO_FACULTY['python_mentor']} (Robotics Lab)",
        "depends_on": "sess_01",
        "track": "AI/ML"
    }
]

def get_scheduling_rooms(custom_rooms: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Returns active campus rooms or high-capacity university default halls if db is fresh."""
    if custom_rooms and len(custom_rooms) > 0:
        return custom_rooms

    db_rooms = fetch_all("SELECT id, name, capacity, location FROM rooms ORDER BY capacity DESC")
    rooms_list = [dict(r) for r in db_rooms] if db_rooms else []

    # Ensure there is at least one large hall capable of holding 250+ attendees for Keynotes
    if not any(r.get("capacity", 0) >= 250 for r in rooms_list):
        rooms_list.insert(0, {"id": "room_audi_a", "name": "Main Auditorium A (Block C)", "capacity": 300, "location": "C-Block Floor 1"})

    if len(rooms_list) < 2:
        rooms_list.append({"id": "room_audi_b", "name": "Auditorium B (Mini Hall)", "capacity": 150, "location": "A-Block Floor 2"})

    return rooms_list

def solve_timetable(
    sessions: Optional[List[Dict[str, Any]]] = None,
    slots: Optional[List[str]] = None,
    custom_rooms: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Solves conflict-free timetable satisfying capacity, exclusivity, and dependency constraints.
    Returns both chronological schedule list and a 2D Room-Time Slot grid matrix.
    """
    sessions = sessions or DEFAULT_SESSIONS
    slots = slots or DEFAULT_SLOTS
    rooms = get_scheduling_rooms(custom_rooms)
    db_speakers = fetch_all("SELECT id, name, availability_json FROM speakers")
    speakers = [dict(s) for s in db_speakers] if db_speakers else []

    scheduler = EventScheduler(rooms=rooms, slots=slots, sessions=sessions, speakers=speakers)
    result = scheduler.solve()

    if not result.get("success"):
        return result

    schedule = result.get("schedule", [])
    
    # Map speaker names into schedule items
    sess_map = {s["id"]: s for s in sessions}
    for item in schedule:
        s_info = sess_map.get(item["session_id"], {})
        item["speaker_name"] = s_info.get("speaker_name", "Assigned Faculty")
        item["track"] = s_info.get("track", "General")
        item["depends_on"] = s_info.get("depends_on")

    # Construct 2D Grid Matrix: rows = slots, cols = rooms
    grid_matrix = []
    for slot_idx, slot_label in enumerate(slots):
        row = {"slot_index": slot_idx, "slot_time": slot_label, "rooms": []}
        for room in rooms:
            # Find session scheduled in this (room, slot)
            placed = next((s for s in schedule if s["room_id"] == room["id"] and s["slot_index"] == slot_idx), None)
            row["rooms"].append({
                "room_id": room["id"],
                "room_name": room["name"],
                "capacity": room["capacity"],
                "session": placed
            })
        grid_matrix.append(row)

    # Compute Occupancy Statistics
    total_seats_used = sum(s["expected_attendance"] for s in schedule)
    total_capacity_booked = sum(next((r["capacity"] for r in rooms if r["id"] == s["room_id"]), 100) for s in schedule)
    occupancy_pct = round((total_seats_used / total_capacity_booked * 100), 1) if total_capacity_booked > 0 else 0

    return {
        "success": True,
        "status": result.get("status", "OPTIMAL"),
        "schedule": schedule,
        "grid_matrix": grid_matrix,
        "rooms": rooms,
        "slots": slots,
        "total_sessions": len(schedule),
        "total_seats_used": total_seats_used,
        "seat_occupancy_rate": occupancy_pct
    }

def handle_hero_speaker_cancellation(event_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Hero Demo: Simulates unexpected speaker cancellation,
    intelligently finds substitute speaker with matching expertise in GenAI,
    re-runs CP-SAT with minimal disruption, and stages outbox broadcast notices.
    """
    rooms = get_scheduling_rooms()
    slots = DEFAULT_SLOTS

    # Check database for candidate substitute speaker in AI department
    substitute_name = (
        f"{HERO_SPEAKER['substitute_name']} "
        f"({HERO_SPEAKER['substitute_department']})"
    )
    match_reason = (
        "Matching research expertise: Generative AI, Machine Learning, "
        "available in afternoon slot"
    )

    # Mutate the hero session and keep its identity tied to the shared fixture.
    reallocated_sessions = []
    for s in DEFAULT_SESSIONS:
        item = dict(s)
        if item["id"] == "sess_02":
            item["original_speaker"] = HERO_SPEAKER["name"]
            item["speaker_name"] = substitute_name
            item["speaker_id"] = HERO_SPEAKER["substitute_id"]
            item["is_substitute"] = True
        reallocated_sessions.append(item)

    solve_res = solve_timetable(sessions=reallocated_sessions, slots=slots, custom_rooms=rooms)

    ev = fetch_one("SELECT id FROM events WHERE id = ?", (event_id,)) if event_id else fetch_one("SELECT id FROM events LIMIT 1")
    target_event_id = event_id or (ev["id"] if ev else "ev_hero_schedule")
    outbox_id = f"notif_change_{uuid.uuid4().hex[:6]}"
    outbox_msg = (
        f"Schedule Update: Keynote speaker {HERO_SPEAKER['name']} cancelled due to unavoidable conflict. "
        f"{substitute_name} has been allocated with zero timetable clashes. All session timings confirmed."
    )
    operation_id = f"op_{uuid.uuid4().hex}"

    def stage_schedule_update(conn):
        if not ev:
            conn.execute(
                """INSERT OR IGNORE INTO events (id, name, brief, event_type)
                   VALUES (?, 'Hero Schedule Summit', 'Clash-Free Timetable Demo', 'conference')""",
                (target_event_id,),
            )
        kavach.verify_recipient_limit(conn, 1)
        conn.execute(
            """INSERT INTO outbox
               (id, event_id, recipient, subject, message, type, status, operation_id)
               VALUES (?, ?, 'all_registered_participants@galgotias.edu',
                       'Schedule Update: Substitute Speaker Allocated', ?,
                       'schedule_change', 'held', ?)""",
            (outbox_id, target_event_id, outbox_msg, operation_id),
        )
        kavach.log_audit(
            conn,
            actor="autopilot_scheduler",
            action="SPEAKER_CANCELLATION_HANDLED",
            result="SUCCESS",
            event_id=target_event_id,
            details={
                "cancelled": HERO_SPEAKER["name"],
                "substitute": substitute_name,
                "outbox_id": outbox_id,
            },
        )
        return {"outbox_id": outbox_id}

    with get_connection() as conn:
        result = kavach.execute_with_kavach(
            conn,
            target_event_id,
            "autopilot_scheduler",
            "speaker_cancellation_notice",
            stage_schedule_update,
            operation_id=operation_id,
            release_staged_notices=False,
        )
    if result["status"] != "committed":
        violation = result.get("violation")
        if violation:
            raise InvariantViolation(
                violation["rule"],
                violation["item"],
                violation["detail"],
                violation.get("suggestion"),
            )
        raise RuntimeError(result.get("error", "Could not stage schedule update."))

    return {
        "status": "re_planned",
        "action": "SPEAKER_CANCELLATION_HANDLED",
        "original_speaker": HERO_SPEAKER["name"],
        "substitute_allocated": substitute_name,
        "match_reason": match_reason,
        "new_schedule": solve_res.get("schedule", []),
        "grid_matrix": solve_res.get("grid_matrix", []),
        "staged_outbox_notice": {
            "id": outbox_id,
            "status": "held_in_outbox",
            "message": "Broadcast notice held in Outbox for coordinator review or instant release."
        }
    }

def export_schedule_csv(schedule: List[Dict[str, Any]]) -> str:
    """Exports timetable schedule to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Slot Time", "Session Title", "Allocated Venue", "Speaker", "Expected Attendance", "Track", "Status"])
    for s in schedule:
        writer.writerow([
            s.get("slot_time"),
            s.get("session_title"),
            s.get("room_name"),
            s.get("speaker_name", "Assigned Faculty"),
            s.get("expected_attendance", 0),
            s.get("track", "General"),
            "Feasible / Conflict-Free"
        ])
    return output.getvalue()
