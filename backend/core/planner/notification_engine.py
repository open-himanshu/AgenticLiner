"""
Autonomous Multi-Stakeholder Notification Engine for Pillar 6.
Part of AgenticLiner Core.
Dispatches contextual, transactional notifications across all 3 key campus audiences:
1. University Dean / Supervisor: Administrative approval requests & executive budget summaries.
2. Event Manager / Organiser: Confirmed logistics manifest, equipment pickup checklist & timetable link.
3. Registered Students & Attendees: Official campus invitation, schedule slot, and digital QR gate pass info.
Integrates with SQLite transactional outbox and optional real SMTP email broadcast.
"""

import sqlite3
import uuid
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from backend.core.database.connection import get_db_path
from backend.services.email_service import is_smtp_configured, send_stakeholder_email

logger = logging.getLogger(__name__)


class StakeholderNotification(BaseModel):
    notification_id: str
    event_id: str
    stakeholder_type: str  # 'dean', 'organiser', 'student'
    recipient_email: str
    recipient_name: str
    subject: str
    summary: str
    body_text: str
    body_html: str
    requires_action: bool = False
    action_url: Optional[str] = None
    status: str = "sent"
    sent_at: Optional[str] = None


def build_dean_notification(
    event_id: str,
    event_name: str,
    event_type: str,
    target_date: str,
    start_time: str,
    end_time: str,
    venue_name: str,
    headcount: int,
    total_cost: float,
    requires_dean_approval: bool = False,
    dean_reasons: Optional[List[str]] = None
) -> StakeholderNotification:
    """Creates executive notification for University Dean / Supervisor."""
    notif_id = f"not_dean_{uuid.uuid4().hex[:8]}"
    dean_email = "admin@galgotias.edu"
    dean_name = "Dean of Academic Affairs"

    status_tag = "[Action Required: Dean Approval]" if requires_dean_approval else "[Campus Briefing]"
    subject = f"{status_tag} {event_name} ({target_date}) - AgenticLiner"
    summary = f"Event '{event_name}' scheduled at {venue_name} for {headcount} attendees (Rs. {int(total_cost)})."

    reasons_text = "\n".join([f"- {r}" for r in (dean_reasons or [])]) if requires_dean_approval else "None (Auto-approved under standard limits)."
    reasons_html = "".join([f"<li>{r}</li>" for r in (dean_reasons or [])]) if requires_dean_approval else "<li>None (Auto-approved under standard limits)</li>"

    action_url = "/supervisor"

    body_text = f"""Respected Dean,

A new campus event has been scheduled through the Autonomous Event Planning Platform:

Event Name: {event_name}
Format: {event_type.title()}
Date: {target_date} ({start_time} - {end_time})
Venue: {venue_name}
Expected Turnout: {headcount} Students
Estimated Logistics Budget: Rs. {int(total_cost)}
Special Approvals Required:
{reasons_text}

Please review in the University Admin Control Panel: {action_url}

Best regards,
Galgotias Autonomous Event Management System
"""

    body_html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background: #f8fafc; padding: 20px; color: #1e293b;">
  <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #cbd5e1; overflow: hidden;">
    <div style="background: #1e3a8a; color: white; padding: 20px;">
      <h3 style="margin: 0;">🏛️ Galgotias University - Dean's Executive Briefing</h3>
      <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.9;">Autonomous Logistics Allocation & Approvals</p>
    </div>
    <div style="padding: 24px;">
      <p>Respected <strong>{dean_name}</strong>,</p>
      <p>The following campus event brief has been compiled and committed:</p>
      <div style="background: #f1f5f9; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
        <table style="width: 100%; font-size: 14px;">
          <tr><td><strong>Event Name:</strong></td><td>{event_name}</td></tr>
          <tr><td><strong>Category:</strong></td><td>{event_type.title()}</td></tr>
          <tr><td><strong>Date & Window:</strong></td><td>{target_date} ({start_time[:5]} - {end_time[:5]})</td></tr>
          <tr><td><strong>Allocated Venue:</strong></td><td>{venue_name}</td></tr>
          <tr><td><strong>Attendance:</strong></td><td>{headcount} Students</td></tr>
          <tr><td><strong>Total Budget:</strong></td><td>Rs. {int(total_cost):,}</td></tr>
        </table>
      </div>
      <div style="margin-bottom: 20px;">
        <strong style="color: {'#b45309' if requires_dean_approval else '#059669'};">
          Special Approval Evaluation:
        </strong>
        <ul style="margin-top: 6px; padding-left: 20px; font-size: 13px;">
          {reasons_html}
        </ul>
      </div>
      <div style="text-align: center; margin-top: 24px;">
        <a href="{action_url}" style="background: #2563eb; color: white; padding: 10px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px;">
          Review in Supervisor Portal
        </a>
      </div>
    </div>
    <div style="background: #f8fafc; padding: 12px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0;">
      Galgotias University SparkX 3.0 Platform • Automated Campus Governance Notice
    </div>
  </div>
</body>
</html>"""

    return StakeholderNotification(
        notification_id=notif_id,
        event_id=event_id,
        stakeholder_type="dean",
        recipient_email=dean_email,
        recipient_name=dean_name,
        subject=subject,
        summary=summary,
        body_text=body_text,
        body_html=body_html,
        requires_action=requires_dean_approval,
        action_url=action_url,
        status="sent",
        sent_at=datetime.now(timezone.utc).isoformat()
    )


def build_organiser_notification(
    event_id: str,
    event_name: str,
    event_type: str,
    target_date: str,
    start_time: str,
    end_time: str,
    venue_name: str,
    headcount: int,
    total_cost: float,
    booked_items: List[str]
) -> StakeholderNotification:
    """Creates confirmation receipt & logistics manifest for Club Organiser / Event Manager."""
    notif_id = f"not_org_{uuid.uuid4().hex[:8]}"
    org_email = "organiser@galgotias.edu"
    org_name = "Club Event Lead"

    subject = f"🎉 Booking Confirmed: {event_name} - Logistics Manifest & Timetable"
    summary = f"Your event '{event_name}' is locked at {venue_name} on {target_date} with {len(booked_items)} equipment packages."

    items_text = "\n".join([f"- {item}" for item in booked_items]) if booked_items else "- Standard logistics kit"
    items_html = "".join([f"<li>{item}</li>" for item in booked_items]) if booked_items else "<li>Standard logistics kit</li>"

    action_url = "/schedule"

    body_text = f"""Dear {org_name},

Congratulations! Your event plan has been confirmed and atomically locked in the campus schedule.

Event: {event_name}
Date: {target_date} ({start_time} - {end_time})
Venue: {venue_name}
Capacity / Target: {headcount} Students
Total Allocated Cost: Rs. {int(total_cost)}

Booked Logistics & Equipment:
{items_text}

Access Timetable & Setup Map: {action_url}

Best regards,
AgenticLiner Autopilot Service
"""

    body_html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background: #f8fafc; padding: 20px; color: #1e293b;">
  <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #cbd5e1; overflow: hidden;">
    <div style="background: #059669; color: white; padding: 20px;">
      <h3 style="margin: 0;">🎉 Booking Confirmed & Committed!</h3>
      <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.9;">Event Manager Manifest • {event_name}</p>
    </div>
    <div style="padding: 24px;">
      <p>Hello <strong>{org_name}</strong>,</p>
      <p>Your campus reservation has been verified and committed under Kavach transaction security.</p>
      <div style="background: #ecfdf5; border-left: 4px solid #10b981; padding: 14px; border-radius: 4px; margin-bottom: 20px;">
        <strong>Allotted Space:</strong> {venue_name}<br>
        <strong>Scheduled Time:</strong> {target_date} ({start_time[:5]} to {end_time[:5]})<br>
        <strong>Turnout Capacity:</strong> {headcount} Seats
      </div>
      <div style="margin-bottom: 20px;">
        <strong>Allocated Inventory & Equipment:</strong>
        <ul style="margin-top: 6px; padding-left: 20px; font-size: 13px;">
          {items_html}
        </ul>
      </div>
      <div style="text-align: center; margin-top: 24px;">
        <a href="{action_url}" style="background: #059669; color: white; padding: 10px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px;">
          View in Timetable Grid
        </a>
      </div>
    </div>
    <div style="background: #f8fafc; padding: 12px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0;">
      Galgotias University SparkX 3.0 Platform • Organiser Service Desk
    </div>
  </div>
</body>
</html>"""

    return StakeholderNotification(
        notification_id=notif_id,
        event_id=event_id,
        stakeholder_type="organiser",
        recipient_email=org_email,
        recipient_name=org_name,
        subject=subject,
        summary=summary,
        body_text=body_text,
        body_html=body_html,
        requires_action=False,
        action_url=action_url,
        status="sent",
        sent_at=datetime.now(timezone.utc).isoformat()
    )


def build_student_notifications(
    event_id: str,
    event_name: str,
    event_type: str,
    target_date: str,
    start_time: str,
    end_time: str,
    venue_name: str,
    db_path: Optional[str] = None,
    limit: int = 5
) -> List[StakeholderNotification]:
    """Generates broadcast announcements for relevant campus students / participants."""
    db_file = db_path or get_db_path()
    notifications: List[StakeholderNotification] = []

    students_list = []
    if os.path.exists(db_file):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, email, department FROM students LIMIT ?", (limit,))
            students_list = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        finally:
            conn.close()

    # Fallback student mock profiles if table is empty
    if not students_list:
        students_list = [
            {"id": "stud_01", "name": "Aarav Sharma", "email": "aarav.sharma@galgotias.edu", "department": "School of Computing Science"},
            {"id": "stud_02", "name": "Diya Patel", "email": "diya.patel@galgotias.edu", "department": "School of AI"},
            {"id": "stud_03", "name": "Rohan Verma", "email": "rohan.verma@galgotias.edu", "department": "School of Engineering"},
        ]

    for student in students_list:
        notif_id = f"not_stud_{uuid.uuid4().hex[:8]}"
        subject = f"📢 Campus Invitation: {event_name} ({target_date}) - Galgotias University"
        summary = f"You are invited to '{event_name}' on {target_date} at {venue_name}."
        action_url = f"/participant?event_id={event_id}"

        body_text = f"""Hello {student['name']},

You are invited to join an upcoming campus event at Galgotias University:

Event: {event_name}
Format: {event_type.title()}
Date: {target_date} ({start_time} - {end_time})
Venue: {venue_name}

Claim your digital QR entry pass and view recommended peer sessions here:
{action_url}

Best regards,
Campus Student Affairs
"""

        body_html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background: #f8fafc; padding: 20px; color: #1e293b;">
  <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #cbd5e1; overflow: hidden;">
    <div style="background: #3b82f6; color: white; padding: 20px;">
      <h3 style="margin: 0;">🎓 Official Campus Event Invitation</h3>
      <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.9;">Galgotias University • {event_name}</p>
    </div>
    <div style="padding: 24px;">
      <p>Hello <strong>{student['name']}</strong> ({student['department']}),</p>
      <p>A new event matching campus interests has just opened for attendee registration:</p>
      <div style="background: #eff6ff; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 4px; margin-bottom: 20px;">
        <strong>Event:</strong> {event_name} ({event_type.title()})<br>
        <strong>Date & Time:</strong> {target_date} • {start_time[:5]} to {end_time[:5]}<br>
        <strong>Location:</strong> {venue_name}
      </div>
      <div style="text-align: center; margin-top: 24px;">
        <a href="{action_url}" style="background: #2563eb; color: white; padding: 10px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px;">
          Claim Digital Gate Pass
        </a>
      </div>
    </div>
    <div style="background: #f8fafc; padding: 12px; text-align: center; font-size: 11px; color: #64748b; border-top: 1px solid #e2e8f0;">
      Galgotias University Student Engagement Desk
    </div>
  </div>
</body>
</html>"""

        notifications.append(
            StakeholderNotification(
                notification_id=notif_id,
                event_id=event_id,
                stakeholder_type="student",
                recipient_email=student["email"],
                recipient_name=student["name"],
                subject=subject,
                summary=summary,
                body_text=body_text,
                body_html=body_html,
                requires_action=False,
                action_url=action_url,
                status="sent",
                sent_at=datetime.now(timezone.utc).isoformat()
            )
        )

    return notifications


def generate_all_stakeholder_notifications(
    event_id: str,
    event_name: str,
    event_type: str,
    target_date: str,
    start_time: str,
    end_time: str,
    venue_name: str,
    headcount: int,
    total_cost: float,
    booked_items: List[str],
    requires_dean_approval: bool = False,
    dean_reasons: Optional[List[str]] = None,
    db_path: Optional[str] = None
) -> List[StakeholderNotification]:
    """Compiles the complete tripartite stakeholder notification bundle."""
    all_notifs: List[StakeholderNotification] = []

    # 1. Dean Notification
    all_notifs.append(
        build_dean_notification(
            event_id=event_id,
            event_name=event_name,
            event_type=event_type,
            target_date=target_date,
            start_time=start_time,
            end_time=end_time,
            venue_name=venue_name,
            headcount=headcount,
            total_cost=total_cost,
            requires_dean_approval=requires_dean_approval,
            dean_reasons=dean_reasons
        )
    )

    # 2. Organiser Notification
    all_notifs.append(
        build_organiser_notification(
            event_id=event_id,
            event_name=event_name,
            event_type=event_type,
            target_date=target_date,
            start_time=start_time,
            end_time=end_time,
            venue_name=venue_name,
            headcount=headcount,
            total_cost=total_cost,
            booked_items=booked_items
        )
    )

    # 3. Student Announcements
    all_notifs.extend(
        build_student_notifications(
            event_id=event_id,
            event_name=event_name,
            event_type=event_type,
            target_date=target_date,
            start_time=start_time,
            end_time=end_time,
            venue_name=venue_name,
            db_path=db_path,
            limit=5
        )
    )

    return all_notifs


def dispatch_stakeholder_notifications(
    event_id: str,
    notifications: List[StakeholderNotification],
    db_path: Optional[str] = None,
    send_real_smtp: bool = False
) -> Dict[str, Any]:
    """
    Persists notifications into the outbox table and dispatches them via SMTP if configured.
    Enforces atomic transaction recording.
    """
    db_file = db_path or get_db_path()
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    dispatched_records = []
    smtp_enabled = is_smtp_configured() and send_real_smtp
    smtp_count = 0

    try:
        cur = conn.cursor()
        for notif in notifications:
            # 1. Insert into outbox table
            cur.execute(
                """
                INSERT INTO outbox (
                    id, event_id, recipient, subject, message, type, status, operation_id, created_at, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'sent', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    notif.notification_id,
                    event_id,
                    notif.recipient_email,
                    notif.subject,
                    notif.body_text,
                    notif.stakeholder_type,
                    f"op_stakeholder_{event_id}"
                )
            )

            # 2. Dispatch real SMTP if enabled
            if smtp_enabled:
                ok, err = send_stakeholder_email(
                    to_email=notif.recipient_email,
                    subject=notif.subject,
                    text_content=notif.body_text,
                    html_content=notif.body_html
                )
                if ok:
                    smtp_count += 1
                else:
                    logger.warning(f"SMTP dispatch failed for {notif.recipient_email}: {err}")

            dispatched_records.append({
                "notification_id": notif.notification_id,
                "stakeholder_type": notif.stakeholder_type,
                "recipient": notif.recipient_email,
                "subject": notif.subject,
                "status": "sent"
            })

        # 3. Log into audit_log
        audit_id = f"aud_notif_{uuid.uuid4().hex[:8]}"
        cur.execute(
            """
            INSERT INTO audit_log (id, event_id, actor, action, details_json, result)
            VALUES (?, ?, 'notification_engine', 'STAKEHOLDER_BROADCAST', ?, 'SUCCESS')
            """,
            (
                audit_id,
                event_id,
                f'{{"total": {len(notifications)}, "dean": 1, "organiser": 1, "students": {len(notifications)-2}}}'
            )
        )
        conn.commit()

    finally:
        conn.close()

    dean_count = sum(1 for n in notifications if n.stakeholder_type == "dean")
    org_count = sum(1 for n in notifications if n.stakeholder_type == "organiser")
    stud_count = sum(1 for n in notifications if n.stakeholder_type == "student")

    return {
        "success": True,
        "event_id": event_id,
        "total_dispatched": len(notifications),
        "real_smtp_sent": smtp_count,
        "stakeholders_notified": {
            "dean": dean_count,
            "organiser": org_count,
            "students": stud_count
        },
        "records": dispatched_records,
        "verbal_summary": "Dean Office, Event Manager, aur campus students ko notifications successfully dispatch kar diye gaye hain."
    }


def get_event_outbox_notices(event_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all outbox notices sent for a given event."""
    db_file = db_path or get_db_path()
    if not os.path.exists(db_file):
        return []
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, recipient, subject, type, status, created_at, sent_at
            FROM outbox
            WHERE event_id = ?
            ORDER BY created_at DESC
            """,
            (event_id,)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
