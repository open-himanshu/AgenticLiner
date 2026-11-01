"""
Event Lifecycle & Safety Workflow Service.
Manages event requests, Dean/Supervisor approval workflow, Kavach invariant checks,
resource allocations, and transactional Outbox release.
"""

import uuid
from typing import Dict, Any, List, Optional

from backend.core.database.connection import get_connection, fetch_one, fetch_all
from backend.core.safety.kavach import KavachEngine, InvariantViolation

kavach = KavachEngine()

def create_event_request(
    name: str,
    brief: str,
    event_type: str,
    expected_participants: int,
    organizer_department: str,
    organizer_email: str,
    room_id: Optional[str] = None,
    start_time: str = "2026-11-15 10:00:00",
    end_time: str = "2026-11-15 13:00:00",
    requisitions: Optional[List[Dict[str, Any]]] = None,
    image_url: Optional[str] = None,
    budget: float = 0,
) -> Dict[str, Any]:
    """
    Submits an event plan. Enforces Kavach invariants (room capacity, room overlap, equipment stock).
    Determines if Dean approval is mandatory (special venue, requested stock with Dean policy, or large headcount).
    Stages event, initial bookings, and held notices in outbox.
    """
    requisitions = requisitions or []
    event_id = f"ev_{uuid.uuid4().hex[:8]}"
    operation_id = f"op_{uuid.uuid4().hex}"

    with get_connection() as conn:
        def create_event_and_bookings(transaction):
            requires_dean = False
            room_name = "Campus Ground"
            kavach.verify_time_window(start_time, end_time)

            if room_id:
                cur = transaction.cursor()
                cur.execute(
                    "SELECT name, capacity, requires_special_approval FROM rooms WHERE id = ?",
                    (room_id,),
                )
                room = cur.fetchone()
                if not room:
                    raise InvariantViolation(
                        "room_not_found", room_id, f"Room {room_id} not found on campus."
                    )

                room_name = room["name"]
                requires_dean = bool(room["requires_special_approval"])
                kavach.verify_room_capacity(
                    transaction, room_id, expected_participants
                )
                kavach.verify_room_overlap(
                    transaction, room_id, start_time, end_time
                )

            cost_by_requisition = []
            for req in requisitions:
                res_id = req.get("resource_id") or req.get("id")
                qty = int(req.get("quantity") or req.get("qty") or 1)
                cost = float(req.get("cost", req.get("estimated_cost", 0)))
                if cost < 0:
                    raise InvariantViolation(
                        "invalid_booking_cost",
                        str(res_id or "resource"),
                        "Booking cost cannot be negative.",
                    )
                cost_by_requisition.append((req, res_id, qty, cost))
                if res_id:
                    cur = transaction.cursor()
                    cur.execute(
                        "SELECT requires_approval FROM resources WHERE id = ?",
                        (res_id,),
                    )
                    res_row = cur.fetchone()
                    if not res_row:
                        raise InvariantViolation(
                            "resource_not_found",
                            res_id,
                            f"Resource ID '{res_id}' does not exist in campus inventory.",
                        )
                    requires_dean = requires_dean or bool(res_row["requires_approval"])
                    kavach.verify_resource_stock(
                        transaction, res_id, qty, start_time, end_time
                    )

            kavach.verify_event_budget(
                transaction,
                event_id,
                budget,
                sum(cost for _, _, _, cost in cost_by_requisition),
            )

            if expected_participants > 150:
                requires_dean = True

            approval_status = (
                "pending_dean_approval" if requires_dean else "auto_approved"
            )
            event_status = "planned" if requires_dean else "allocated"
            transaction.execute(
                """INSERT INTO events
                   (id, name, brief, event_type, expected_participants, budget,
                    organizer_department, approval_status, status, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    name.strip(),
                    brief.strip(),
                    event_type.lower(),
                    expected_participants,
                    budget,
                    organizer_department.strip(),
                    approval_status,
                    event_status,
                    image_url,
                ),
            )

            if room_id:
                booking_id = f"bk_room_{uuid.uuid4().hex[:6]}"
                transaction.execute(
                    """INSERT INTO bookings
                       (id, event_id, room_id, item_name, category, start_time,
                        end_time, quantity, estimated_cost, approval_status, status)
                       VALUES (?, ?, ?, ?, 'venue', ?, ?, 1, 0, ?, ?)""",
                    (
                        booking_id,
                        event_id,
                        room_id,
                        room_name,
                        start_time,
                        end_time,
                        approval_status,
                        "confirmed" if not requires_dean else "pending",
                    ),
                )

            for req, res_id, qty, cost in cost_by_requisition:
                item_name = req.get("name") or req.get("item_name") or "Equipment"
                category = req.get("category") or "equipment"
                booking_id = f"bk_res_{uuid.uuid4().hex[:6]}"
                transaction.execute(
                    """INSERT INTO bookings
                       (id, event_id, resource_id, item_name, category, start_time,
                        end_time, quantity, estimated_cost, approval_status, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        booking_id,
                        event_id,
                        res_id,
                        item_name,
                        category,
                        start_time,
                        end_time,
                        qty,
                        cost,
                        approval_status,
                        "confirmed" if not requires_dean else "pending",
                    ),
                )
                if not requires_dean and res_id:
                    transaction.execute(
                        "UPDATE resources SET allocated_stock = allocated_stock + ? WHERE id = ?",
                        (qty, res_id),
                    )

            outbox_id = f"notif_{uuid.uuid4().hex[:8]}"
            if requires_dean:
                subject = f"Dean Approval Request: {name} ({organizer_department})"
                message = (
                    f"An event request requiring Dean approval has been submitted:\n"
                    f"Event: {name}\nOrganized by: {organizer_department} ({organizer_email})\n"
                    f"Venue: {room_name}\nExpected Headcount: {expected_participants}\n"
                    f"Requisitions: {len(requisitions)} items."
                )
                recipient = "admin@galgotias.edu"
                notification_type = "dean_approval_request"
                status = "held"
                sent_at_sql = "NULL"
            else:
                subject = f"Event Confirmed: {name}"
                message = f"Your event '{name}' has been auto-approved and allocated campus resources."
                recipient = organizer_email
                notification_type = "confirmation"
                status = "sent"
                sent_at_sql = "CURRENT_TIMESTAMP"

            transaction.execute(
                f"""INSERT INTO outbox
                   (id, event_id, recipient, subject, message, type, status,
                    sent_at, operation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, {sent_at_sql}, ?)""",
                (
                    outbox_id,
                    event_id,
                    recipient,
                    subject,
                    message,
                    notification_type,
                    status,
                    operation_id,
                ),
            )
            kavach.log_audit(
                transaction,
                actor=organizer_email,
                action="CREATE_EVENT_REQUEST",
                result="SUCCESS",
                event_id=event_id,
                details={
                    "name": name,
                    "approval_status": approval_status,
                    "requires_dean": requires_dean,
                },
            )
            return {
                "success": True,
                "event_id": event_id,
                "name": name,
                "approval_status": approval_status,
                "status": event_status,
                "requires_dean_approval": requires_dean,
            }

        result = kavach.execute_with_kavach(
            conn,
            event_id,
            organizer_email,
            "create_event_request",
            create_event_and_bookings,
            operation_id=operation_id,
            release_staged_notices=False,
        )
        if result["status"] == "committed":
            return result["details"]
        violation = result.get("violation")
        if violation:
            raise InvariantViolation(
                violation["rule"],
                violation["item"],
                violation["detail"],
                violation.get("suggestion"),
            )
        raise RuntimeError(result.get("error", "Event request failed."))

def _run_supervisor_transition(
    event_id: str,
    supervisor_email: str,
    operation_name: str,
    action,
) -> Dict[str, Any]:
    with get_connection() as conn:
        result = kavach.execute_with_kavach(
            conn,
            event_id,
            supervisor_email,
            operation_name,
            action,
            release_staged_notices=False,
        )
    if result["status"] == "committed":
        return result["details"]
    violation = result.get("violation")
    if violation:
        raise InvariantViolation(
            violation["rule"],
            violation["item"],
            violation["detail"],
            violation.get("suggestion"),
        )
    raise RuntimeError(result.get("error", "Supervisor transition failed."))


def approve_event_by_supervisor(event_id: str, supervisor_email: str = "admin@galgotias.edu", remarks: str = "") -> Dict[str, Any]:
    """Approve an event and release its held notices atomically through Kavach."""
    def approve_event(conn):
        event = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event:
            raise InvariantViolation(
                "event_not_found", event_id, f"Event {event_id} not found."
            )

        pending_bookings = conn.execute(
            """SELECT id, room_id, resource_id, quantity, start_time, end_time
               FROM bookings
               WHERE event_id = ? AND status = 'pending'""",
            (event_id,),
        ).fetchall()
        for booking in pending_bookings:
            kavach.verify_time_window(booking["start_time"], booking["end_time"])
            if booking["room_id"]:
                kavach.verify_room_capacity(
                    conn, booking["room_id"], event["expected_participants"]
                )
                kavach.verify_room_overlap(
                    conn,
                    booking["room_id"],
                    booking["start_time"],
                    booking["end_time"],
                )
            if booking["resource_id"]:
                overlapping_allocations = conn.execute(
                    """SELECT COALESCE(SUM(quantity), 0) AS quantity
                       FROM bookings
                       WHERE event_id = ?
                         AND resource_id = ?
                         AND status = 'pending'
                         AND start_time < ?
                         AND end_time > ?""",
                    (
                        event_id,
                        booking["resource_id"],
                        booking["end_time"],
                        booking["start_time"],
                    ),
                ).fetchone()["quantity"]
                kavach.verify_resource_stock(
                    conn,
                    booking["resource_id"],
                    overlapping_allocations,
                    booking["start_time"],
                    booking["end_time"],
                )

        conn.execute(
            """UPDATE events
               SET approval_status = 'approved', status = 'allocated', updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (event_id,),
        )
        conn.execute(
            """UPDATE bookings
               SET status = 'confirmed', approval_status = 'approved'
               WHERE event_id = ?""",
            (event_id,),
        )
        allocations = conn.execute(
            """SELECT resource_id, quantity FROM bookings
               WHERE event_id = ? AND resource_id IS NOT NULL""",
            (event_id,),
        ).fetchall()
        for allocation in allocations:
            conn.execute(
                "UPDATE resources SET allocated_stock = allocated_stock + ? WHERE id = ?",
                (allocation["quantity"], allocation["resource_id"]),
            )

        held_count = conn.execute(
            "SELECT count(*) AS count FROM outbox WHERE event_id = ? AND status = 'held'",
            (event_id,),
        ).fetchone()["count"]
        kavach.verify_recipient_limit(conn, held_count)
        conn.execute(
            """UPDATE outbox
               SET status = 'sent', sent_at = CURRENT_TIMESTAMP
               WHERE event_id = ? AND status = 'held'""",
            (event_id,),
        )

        notification_id = f"notif_appr_{uuid.uuid4().hex[:8]}"
        subject = f"Official Dean Approval: {event['name']}"
        message = (
            f"Dear Organiser,\n\n"
            f"Your event '{event['name']}' has been officially APPROVED by the University Dean Office.\n"
            f"Remarks: {remarks or 'All campus resources and venue bookings have been confirmed.'}\n\n"
            f"You may now publish the schedule and accept student registrations."
        )
        kavach.verify_recipient_limit(conn, 1)
        conn.execute(
            """INSERT INTO outbox (id, event_id, recipient, subject, message, type, status, sent_at)
               VALUES (?, ?, 'organiser@galgotias.edu', ?, ?, 'approval_notice', 'sent', CURRENT_TIMESTAMP)""",
            (notification_id, event_id, subject, message),
        )
        kavach.log_audit(
            conn,
            actor=supervisor_email,
            action="DEAN_APPROVAL_GRANTED",
            result="SUCCESS",
            event_id=event_id,
            details={"remarks": remarks, "event_name": event["name"]},
        )
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Event '{event['name']}' successfully approved and bookings confirmed.",
        }

    try:
        return _run_supervisor_transition(
            event_id, supervisor_email, "approve_event_by_supervisor", approve_event
        )
    except InvariantViolation as violation:
        if violation.rule not in {
            "invalid_time_window",
            "room_not_found",
            "capacity_overrun",
            "room_overlap",
            "invalid_resource_quantity",
            "resource_not_found",
            "resource_exhaustion",
        }:
            raise
        return {
            "success": False,
            "event_id": event_id,
            "violation": {
                "rule": violation.rule,
                "item": violation.item,
                "detail": violation.detail,
                "suggestion": violation.suggestion,
            },
        }


def reject_event_by_supervisor(event_id: str, supervisor_email: str = "admin@galgotias.edu", reason: str = "") -> Dict[str, Any]:
    """Reject an event and cancel its held notices atomically through Kavach."""
    def reject_event(conn):
        event = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event:
            raise InvariantViolation(
                "event_not_found", event_id, f"Event {event_id} not found."
            )

        conn.execute(
            """UPDATE events
               SET approval_status = 'rejected', status = 'cancelled', updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (event_id,),
        )
        conn.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE event_id = ?",
            (event_id,),
        )
        conn.execute(
            """UPDATE outbox SET status = 'cancelled', error_message = ?
               WHERE event_id = ? AND status = 'held'""",
            (f"Event request rejected: {reason}", event_id),
        )

        notification_id = f"notif_rej_{uuid.uuid4().hex[:8]}"
        subject = f"Event Request Update: {event['name']}"
        message = (
            f"Dear Organiser,\n\n"
            f"Your request for '{event['name']}' has not been approved by the Dean Office.\n"
            f"Reason: {reason or 'Administrative conflict or scheduling constraint.'}\n\n"
            f"Please revise your venue or resource requests in the Event Planner."
        )
        kavach.verify_recipient_limit(conn, 1)
        conn.execute(
            """INSERT INTO outbox (id, event_id, recipient, subject, message, type, status, sent_at)
               VALUES (?, ?, 'organiser@galgotias.edu', ?, ?, 'rejection_notice', 'sent', CURRENT_TIMESTAMP)""",
            (notification_id, event_id, subject, message),
        )
        kavach.log_audit(
            conn,
            actor=supervisor_email,
            action="DEAN_APPROVAL_REJECTED",
            result="REJECTED",
            event_id=event_id,
            details={"reason": reason, "event_name": event["name"]},
        )
        return {
            "success": True,
            "event_id": event_id,
            "message": f"Event '{event['name']}' has been rejected.",
        }

    return _run_supervisor_transition(
        event_id, supervisor_email, "reject_event_by_supervisor", reject_event
    )

def get_event_with_details(event_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an event with its bookings, venue, requisitions, registrant count, and outbox logs."""
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        return None

    bookings = fetch_all("SELECT * FROM bookings WHERE event_id = ?", (event_id,))
    registrations_count = fetch_one("SELECT count(*) as count FROM registrations WHERE event_id = ? AND status = 'confirmed'", (event_id,))["count"]
    waitlist_count = fetch_one("SELECT count(*) as count FROM registrations WHERE event_id = ? AND status = 'waitlisted'", (event_id,))["count"]
    outbox = fetch_all("SELECT * FROM outbox WHERE event_id = ? ORDER BY created_at DESC", (event_id,))

    return {
        "event": event,
        "bookings": bookings,
        "confirmed_attendees": registrations_count,
        "waitlisted_attendees": waitlist_count,
        "outbox": outbox
    }
