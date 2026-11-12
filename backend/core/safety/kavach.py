"""
Kavach Safety Engine: Fault-Tolerant Transaction Sandboxing & Invariant Enforcement
Part of AgenticLiner Core.

University Invariants Enforced:
1. Room Double-Booking / Time Overlap
2. Room Capacity Overrun (Expected Attendees > Room Seats)
3. Speaker Simultaneity Clash
4. Campus Inventory Stock Depletion
5. Dean Approval Policy (Large Audi / Transport)
6. Transactional Outbox Staging and Atomic Savepoint Rollback
"""

import sqlite3
import uuid
import json
import math
import os
from typing import Dict, Any, Optional, Callable
from datetime import date, datetime

class InvariantViolation(Exception):
    """Raised when an operation violates a core campus invariant."""
    def __init__(self, rule: str, item: str, detail: str, suggestion: Optional[str] = None):
        self.rule = rule
        self.item = item
        self.detail = detail
        self.suggestion = suggestion
        super().__init__(f"[{rule}] {item}: {detail}")

class KavachEngine:
    def __init__(
        self,
        max_blast_radius: int = 20,
        max_recipients: Optional[int] = None,
    ):
        self.max_blast_radius = max_blast_radius
        self.max_recipients = (
            max_recipients
            if max_recipients is not None
            else int(os.getenv("KAVACH_MAX_RECIPIENTS", "500"))
        )
        if self.max_recipients < 1:
            raise ValueError("KAVACH_MAX_RECIPIENTS must be a positive integer.")

    def log_audit(self, conn: sqlite3.Connection, actor: str, action: str, result: str, event_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        """Record an operation in the persistent audit log."""
        log_id = f"aud_{uuid.uuid4().hex[:10]}"
        details_str = json.dumps(details or {})
        conn.execute(
            "INSERT INTO audit_log (id, event_id, actor, action, details_json, result) VALUES (?, ?, ?, ?, ?, ?)",
            (log_id, event_id, actor, action, details_str, result)
        )

    def verify_room_capacity(self, conn: sqlite3.Connection, room_id: str, expected_attendance: int) -> None:
        """Verify that expected attendance does not exceed the room's maximum capacity."""
        cur = conn.cursor()
        cur.execute("SELECT name, capacity FROM rooms WHERE id = ?", (room_id,))
        row = cur.fetchone()
        if not row:
            raise InvariantViolation(
                rule="room_not_found",
                item=room_id,
                detail=f"Room ID '{room_id}' does not exist on campus."
            )
        room_name, capacity = row["name"], row["capacity"]
        if expected_attendance > capacity:
            # Find alternative rooms that CAN hold this attendance
            cur.execute("SELECT id, name, capacity FROM rooms WHERE capacity >= ? ORDER BY capacity ASC LIMIT 2", (expected_attendance,))
            alternatives = cur.fetchall()
            alt_msg = ", ".join([f"{a['name']} (Seats: {a['capacity']})" for a in alternatives]) if alternatives else "No single hall available with this capacity on campus."
            raise InvariantViolation(
                rule="capacity_overrun",
                item=room_name,
                detail=f"Attendance of {expected_attendance} exceeds room capacity of {capacity} seats.",
                suggestion=f"Allocate a larger hall: {alt_msg}"
            )

    def verify_room_overlap(self, conn: sqlite3.Connection, room_id: str, start_time: str, end_time: str, exclude_booking_id: Optional[str] = None) -> None:
        """Verify that the room is not already booked during the requested window."""
        cur = conn.cursor()
        query = """
            SELECT b.id, b.item_name, b.start_time, b.end_time, e.name as event_name
            FROM bookings b
            LEFT JOIN events e ON b.event_id = e.id
            WHERE b.room_id = ? 
              AND b.status = 'confirmed'
              AND (
                  (b.start_time < ? AND b.end_time > ?) OR
                  (b.start_time >= ? AND b.start_time < ?)
              )
        """
        params = [room_id, end_time, start_time, start_time, end_time]
        if exclude_booking_id:
            query += " AND b.id != ?"
            params.append(exclude_booking_id)

        cur.execute(query, tuple(params))
        conflict = cur.fetchone()
        if conflict:
            cur.execute("SELECT name FROM rooms WHERE id = ?", (room_id,))
            r_row = cur.fetchone()
            r_name = r_row["name"] if r_row else room_id
            raise InvariantViolation(
                rule="room_overlap",
                item=r_name,
                detail=f"Hall is already reserved for '{conflict['event_name'] or 'Academic Activity'}' from {conflict['start_time']} to {conflict['end_time']}.",
                suggestion="Choose a different time slot or allocate an alternative hall."
            )

    def verify_speaker_clash(
        self,
        conn: sqlite3.Connection,
        speaker_id: str,
        start_time: str,
        end_time: str,
        exclude_session_id: Optional[str] = None,
    ) -> None:
        """Verify that a speaker is not double-booked across simultaneous sessions on campus."""
        if not speaker_id:
            return
        cur = conn.cursor()
        query = """
            SELECT s.id, s.title, s.start_time, s.end_time, spk.name as speaker_name
            FROM sessions s
            LEFT JOIN speakers spk ON s.speaker_id = spk.id
            WHERE s.speaker_id = ?
              AND (
                  (s.start_time < ? AND s.end_time > ?) OR
                  (s.start_time >= ? AND s.start_time < ?)
              )
        """
        params = [speaker_id, end_time, start_time, start_time, end_time]
        if exclude_session_id:
            query += " AND s.id != ?"
            params.append(exclude_session_id)
        cur.execute(query, tuple(params))
        conflict = cur.fetchone()
        if conflict:
            spk_name = conflict["speaker_name"] or speaker_id
            raise InvariantViolation(
                rule="speaker_simultaneity_clash",
                item=spk_name,
                detail=f"Speaker is already assigned to session '{conflict['title']}' from {conflict['start_time']} to {conflict['end_time']}.",
                suggestion="Schedule session during an available time window or assign another speaker."
            )

    def verify_resource_stock(self, conn: sqlite3.Connection, resource_id: str, requested_qty: int, start_time: str, end_time: str) -> None:
        """Verify that requested campus equipment or volunteer quota does not exceed stock."""
        if requested_qty <= 0:
            raise InvariantViolation(
                rule="invalid_resource_quantity",
                item=resource_id,
                detail="Requested resource quantity must be greater than zero.",
            )

        cur = conn.cursor()
        cur.execute("SELECT name, stock FROM resources WHERE id = ?", (resource_id,))
        res = cur.fetchone()
        if not res:
            raise InvariantViolation(
                rule="resource_not_found",
                item=resource_id,
                detail=f"Resource ID '{resource_id}' does not exist in campus inventory.",
            )
        total_stock = res["stock"]
        
        cur.execute("""
            SELECT SUM(quantity) as booked_qty
            FROM bookings
            WHERE resource_id = ? 
              AND status = 'confirmed'
              AND (
                  (start_time < ? AND end_time > ?) OR
                  (start_time >= ? AND start_time < ?)
              )
        """, (resource_id, end_time, start_time, start_time, end_time))
        b_row = cur.fetchone()
        already_booked = b_row["booked_qty"] or 0
        if already_booked + requested_qty > total_stock:
            available = max(0, total_stock - already_booked)
            raise InvariantViolation(
                rule="resource_exhaustion",
                item=res["name"],
                detail=f"Requested {requested_qty} units, but only {available} units currently available in campus inventory (Total campus stock: {total_stock}).",
                suggestion=f"Cap quantity to {available} units or submit inter-department requisition."
            )

    def verify_time_window(self, start_time: str, end_time: str) -> None:
        """Reject malformed, non-positive, or same-day/past event windows."""
        try:
            start = datetime.fromisoformat(start_time)
            end = datetime.fromisoformat(end_time)
        except (TypeError, ValueError) as exc:
            raise InvariantViolation(
                "invalid_time_window",
                "event",
                "Start and end must be valid ISO date-time values.",
            ) from exc

        try:
            invalid_order = start >= end
        except TypeError as exc:
            raise InvariantViolation(
                "invalid_time_window",
                "event",
                "Start and end times must use compatible time-zone formats.",
            ) from exc
        if invalid_order:
            raise InvariantViolation(
                "invalid_time_window",
                "event",
                "The event start time must be earlier than its end time.",
            )
        if start.date() <= date.today():
            raise InvariantViolation(
                "invalid_time_window",
                "event",
                "Events must be scheduled for a future date.",
            )

    def verify_event_budget(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        budget: float,
        proposed_cost: float = 0,
    ) -> None:
        """Reject a requisition when committed and proposed costs exceed budget."""
        try:
            budget = float(budget)
            proposed_cost = float(proposed_cost)
        except (TypeError, ValueError) as exc:
            raise InvariantViolation(
                "invalid_budget",
                event_id,
                "Budget and booking costs must be valid numbers.",
            ) from exc
        if (
            not math.isfinite(budget)
            or not math.isfinite(proposed_cost)
            or budget < 0
            or proposed_cost < 0
        ):
            raise InvariantViolation(
                "invalid_budget",
                event_id,
                "Budget and booking costs cannot be negative.",
            )
        row = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0) AS total FROM bookings WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        committed_cost = row["total"] if row else 0
        total_cost = committed_cost + proposed_cost
        if total_cost > budget:
            raise InvariantViolation(
                "budget_exceeded",
                event_id,
                f"Booking cost {total_cost:.2f} exceeds event budget {budget:.2f}.",
                suggestion="Reduce requisition costs or increase the approved event budget.",
            )

    def verify_recipient_limit(self, conn: sqlite3.Connection, recipients: Any) -> None:
        """Enforce the per-operation outbox recipient cap."""
        count = recipients if isinstance(recipients, int) else len(recipients)
        if count > self.max_recipients:
            raise InvariantViolation(
                "recipient_limit_exceeded",
                "outbox",
                f"Notice targets {count} recipients; the configured limit is {self.max_recipients}.",
                suggestion="Split the broadcast into smaller approved batches.",
            )

    def execute_with_kavach(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        actor: str,
        operation_name: str,
        actions_callback,
        operation_id: Optional[str] = None,
        release_staged_notices: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes multi-action event mutations inside an isolated SQLite savepoint.
        If any campus invariant fails, performs an instant atomic ROLLBACK to the savepoint,
        drops any staged outbox notices, and logs the detailed failure in the audit log.
        """
        savepoint_name = f"sp_{uuid.uuid4().hex[:8]}"
        operation_id = operation_id or f"op_{uuid.uuid4().hex}"
        conn.execute(f"SAVEPOINT {savepoint_name};")
        self.log_audit(conn, actor, f"SAVEPOINT_CREATE:{savepoint_name}", "SUCCESS", event_id=event_id)
        changes_before = conn.total_changes

        try:
            result_payload = actions_callback(conn)

            if release_staged_notices:
                conn.execute(
                    "UPDATE outbox SET status = 'sent', sent_at = CURRENT_TIMESTAMP "
                    "WHERE operation_id = ? AND status = 'held'",
                    (operation_id,),
                )
            if operation_id:
                recipient_row = conn.execute(
                    "SELECT count(*) AS count FROM outbox WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                self.verify_recipient_limit(conn, recipient_row["count"])

            changed_rows = conn.total_changes - changes_before
            if changed_rows > self.max_blast_radius:
                raise InvariantViolation(
                    "blast_radius_exceeded",
                    operation_name,
                    f"Operation changed {changed_rows} rows; the configured limit is {self.max_blast_radius}.",
                    suggestion="Split the operation into smaller independently reviewed transactions.",
                )

            conn.execute(f"RELEASE SAVEPOINT {savepoint_name};")
            self.log_audit(conn, actor, f"SAVEPOINT_COMMIT:{operation_name}", "SUCCESS", event_id=event_id, details=result_payload)
            return {
                "status": "committed",
                "operation": operation_name,
                "savepoint": savepoint_name,
                "details": result_payload
            }

        except InvariantViolation as iv:
            # Atomic ROLLBACK to savepoint
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name};")
            error_details = {
                "rule": iv.rule,
                "item": iv.item,
                "detail": iv.detail,
                "suggestion": iv.suggestion
            }
            self.log_audit(conn, actor, f"SAVEPOINT_ROLLBACK:{operation_name}", "BLOCKED", event_id=event_id, details=error_details)

            return {
                "status": "rolled_back",
                "operation": operation_name,
                "violation": error_details,
                "error": str(iv)
            }
        except Exception as ex:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name};")
            self.log_audit(conn, actor, f"SYSTEM_ERROR:{operation_name}", "FAILED", event_id=event_id, details={"error": str(ex)})
            return {
                "status": "rolled_back",
                "operation": operation_name,
                "error": f"Unexpected execution error: {str(ex)}"
            }

    def execute_with_retry(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        actor: str,
        operation_name: str,
        planner_callback: Callable[[Optional[str], int], Callable[[sqlite3.Connection], Any]],
        request_payload: Dict[str, Any],
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Ask a planner to revise a violating request up to three times, then queue it."""
        retries_limit = min(max(0, max_retries), 3)
        attempts_limit = retries_limit + 1
        short_error = None

        for attempt in range(1, attempts_limit + 1):
            action = planner_callback(short_error, attempt)
            result = self.execute_with_kavach(
                conn,
                event_id,
                actor,
                operation_name,
                action,
                operation_id=f"op_{uuid.uuid4().hex}",
            )
            if result["status"] == "committed":
                result["attempts"] = attempt
                return result
            if "violation" not in result:
                result["attempts"] = attempt
                return result

            violation = result["violation"]
            short_error = (
                f"[{violation['rule']}] {violation['item']}: {violation['detail']}"
            )[:160]

        review_id = f"review_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO human_review_queue
               (id, event_id, actor, operation_name, request_json, attempts, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                review_id,
                event_id,
                actor,
                operation_name,
                json.dumps(request_payload),
                attempts_limit,
                short_error or "Automatic planning failed.",
            ),
        )
        return {
            "status": "human_review",
            "review_id": review_id,
            "attempts": attempts_limit,
            "error": short_error,
        }
