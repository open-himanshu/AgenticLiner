"""Database setup and seeding script for screenshot capture.
Uses a temporary SQLite database (temp_screenshots.db) to ensure
the real database is never modified.
"""

import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_SCREENSHOTS = ROOT / "docs" / "screenshots"
TEMP_DB = ROOT / "temp_screenshots.db"

# Passwords for seed users
PASSWORDS = {
    "supervisor": "TempSupervisorPass_987!",
    "organiser": "TempOrganiserPass_987!",
    "data_manager": "TempDataMgrPass_987!",
    "participant": "TempStudentPass_987!",
}

def setup():
    if TEMP_DB.exists():
        try:
            TEMP_DB.unlink()
        except Exception:
            pass

    os.environ["DATABASE_PATH"] = str(TEMP_DB)
    os.environ["PROVIDER"] = ""
    os.environ["TEST_CONSOLE"] = ""
    for role, pwd in PASSWORDS.items():
        os.environ[f"{role.upper()}_PASSWORD"] = pwd

    sys.path.insert(0, str(ROOT))

    from backend.core.database.init_db import init_database, seed_campus_data
    from backend.services.seed_users import seed_users
    from backend.modules.module2_scheduling.attendee_manager import AttendeeManager
    from backend.services.analytics_service import record_feedback, issue_verifiable_certificate
    from backend.core.database.connection import fetch_one

    print("1. Initializing schema and seeding demo campus data...")
    init_database()
    seed_campus_data(force_reseed=True)

    print("2. Seeding user accounts with process-local passwords...")
    seed_users()

    print("3. Seeding attendee registrations and gate check-ins...")
    mgr = AttendeeManager()
    part_student = fetch_one("SELECT * FROM users WHERE role = 'participant' LIMIT 1")

    # Register main participant student
    if part_student:
        reg = mgr.register_student(
            event_id="ev_001",
            name=part_student["full_name"],
            email=part_student["email"],
            department=part_student.get("department", "Computer Science"),
            year=2,
            interests=["Generative AI", "PyTorch", "Hackathons"],
            preferred_sessions=["Opening Keynote", "PyTorch Lab"]
        )
        if reg.get("registration_id"):
            mgr.check_in_attendee(reg["registration_id"])

    # Register 14 additional student attendees
    departments = ["B.Tech CSE", "B.Tech Data Science", "B.Tech Cyber Security", "BCA", "MCA", "B.Tech AIML"]
    for i in range(1, 15):
        dept = departments[i % len(departments)]
        reg = mgr.register_student(
            event_id="ev_001",
            name=f"Student {i}",
            email=f"student{i}@galgotiasuniversity.edu.in",
            department=f"{dept} (Yr {(i % 4) + 1})",
            year=(i % 4) + 1,
            interests=["Machine Learning", "Robotics"],
            preferred_sessions=["Keynote"]
        )
        if reg.get("registration_id"):
            reg_id = reg["registration_id"]
            if i <= 5:
                mgr.check_in_attendee(reg_id)
            elif i == 14:
                mgr.cancel_registration(reg_id)

    print("4. Seeding feedback for analytics...")
    feedbacks = [
        ("Hands-on PyTorch coding lab was very clear and structured. Great keynote session!", 5),
        ("Excellent organization and fast gate QR entry. Great campus atmosphere.", 5),
        ("Good workshops overall, but Audi B sound was slightly low in back rows.", 4),
        ("Snack boxes were good. Demand for more power spike extension boards.", 4),
        ("Keynote session started on time and topics were relevant.", 5),
    ]
    for comment, rating in feedbacks:
        record_feedback(event_id="ev_001", rating=rating, comment=comment, student_id=part_student["id"])

    print("5. Issuing verifiable certificate...")
    cert = issue_verifiable_certificate(
        student_name="Student Attendee",
        event_id="ev_001",
        student_id=part_student["id"],
        verify_base_url="http://127.0.0.1:8000/verify"
    )
    cert_id = cert["certificate_id"]
    print(f"Generated certificate ID: {cert_id}")

    # Seed pending event for supervisor dashboard oversight
    with sqlite3.connect(str(TEMP_DB)) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO events (
                id, name, brief, event_type, expected_participants, budget,
                organizer_department, approval_status, status, created_at
            ) VALUES (
                'ev_pending_001', 'Annual Inter-College Robotics Challenge 2026',
                'Autonomous line-follower and aerial drone obstacle arena competition.',
                'technical', 350, 0, 'School of Computing Science',
                'pending_dean_approval', 'planned', '2026-11-14 11:30:00'
            )
        """)
        # Add booking for the pending event so venue name appears
        cur.execute("""
            INSERT OR IGNORE INTO bookings (
                id, event_id, room_id, resource_id, start_time, end_time, status, created_at
            ) VALUES (
                'bk_pending_001', 'ev_pending_001', 'room_audi_b', NULL,
                '2026-12-05 10:00:00', '2026-12-05 17:00:00', 'confirmed', '2026-11-14 11:30:00'
            )
        """)
        # Seed outbox notices
        cur.execute("SELECT count(*) FROM outbox")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO outbox (id, event_id, recipient, message, type, status, channel, created_at, sent_at)
                VALUES ('nt_001', 'ev_001', 'student@galgotias.edu', 'Your registration for Campus Innovation Hackathon 2026 is confirmed.', 'confirmation', 'sent', 'email', '2026-11-14 10:00:00', '2026-11-14 10:01:00'),
                       ('nt_002', 'ev_001', 'all_attendees', 'Reminder: Opening Keynote starts at 09:30 AM in Main Auditorium A.', 'reminder', 'sent', 'email', '2026-11-14 11:00:00', '2026-11-14 11:01:00')
            """)
        conn.commit()

    print("Database setup complete.")
    return cert_id

if __name__ == "__main__":
    setup()
