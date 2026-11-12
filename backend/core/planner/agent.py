"""
AgenticLiner Autopilot Agent Engine (University Edition).
Executes multi-step autonomous planning, tool calling, and live activity logging.
Focuses on campus permissions, logistics quota, capacity matching, and Kavach safety.
"""

import os
import json
import uuid
import re
from typing import Dict, Any, List, Optional
from backend.core.planner.natural_intake import extract_event_entities_llm
from backend.core.planner.tools import (
    tool_find_free_venues,
    tool_recommend_from_history,
    tool_requisition_campus_resources
)

class AutopilotAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.timeline: List[Dict[str, Any]] = []

    def _log_step(self, step_no: int, tool_name: str, arguments: Dict[str, Any], status: str, summary: str, details: Optional[Any] = None):
        step_entry = {
            "step": step_no,
            "tool": tool_name,
            "arguments": arguments,
            "status": status,
            "summary": summary,
            "details": details
        }
        self.timeline.append(step_entry)
        return step_entry

    def run_autopilot(
        self,
        prompt: str,
        date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        budget: float | None = None,
    ) -> Dict[str, Any]:
        """
        Executes autonomous campus event planning:
        1. Adaptive Intake & Entity Extraction (Event Type, headcount, timing)
        2. Venue Discovery & Capacity Verification (tool_find_free_venues)
        3. Historical Pattern & Campus Safety Bundling (tool_recommend_from_history)
        4. Transactional Requisition guarded by Kavach Safety Layer (tool_requisition_campus_resources)
        5. Live Timeline Generation & Staged Outbox release.
        """
        self.timeline = []
        event_id = f"ev_auto_{uuid.uuid4().hex[:8]}"

        # Step 1: Entity Extraction from Natural Language Prompt
        from backend.core.planner.natural_intake import resolve_natural_datetime_with_assumptions

        step_no = 1
        prompt_lower = prompt.lower()

        # Extract Headcount
        headcount_match = re.search(r'(\d+)\s*(students|people|attendees|participants|heads)', prompt_lower)
        if headcount_match:
            headcount = int(headcount_match.group(1))
        else:
            numbers = re.findall(r'\b\d{2,4}\b', prompt)
            headcount = int(numbers[0]) if numbers else 120

        # Extract Budget if omitted by caller
        if budget is None:
            budget_match = re.search(
                r'(?:budget|rs\.?|inr|₹)\s*[:=]?\s*(\d[\d,]*)|(\d[\d,]*)\s*(?:budget|rs\.?|inr)\b',
                prompt_lower,
            )
            if budget_match:
                budget = float((budget_match.group(1) or budget_match.group(2)).replace(",", ""))
            else:
                budget = 25000.0

        # Extract Date, Time, and Assumptions if omitted by caller
        assumptions: list[str] = []
        used_intake_time = start_time is None and end_time is None
        if date is None or start_time is None or end_time is None:
            dt_info = resolve_natural_datetime_with_assumptions(prompt, prompt)
            if date is None:
                date = dt_info["date"]
            if start_time is None:
                start_time = dt_info["start_time"]
            if end_time is None:
                end_time = dt_info["end_time"]
            if used_intake_time:
                assumptions.extend(dt_info["assumptions"])

        # Extract Event Type (word boundaries prevent accidental substring mismatches)
        if re.search(r'\b(dance(?:\s+performance)?|cultural|music|drama)\b', prompt_lower):
            event_type = "cultural"
            event_name = "University Cultural Performance"
        elif re.search(r'\b(hackathon|coding|ctf)\b', prompt_lower):
            event_type = "hackathon"
            event_name = "Campus AI Hackathon"
        elif re.search(r'\bfest(?:ival)?\b', prompt_lower):
            event_type = "cultural"
            event_name = "University Cultural Performance"
        elif re.search(r'\b(workshop|hands-on|bootcamp|training)\b', prompt_lower):
            event_type = "workshop"
            event_name = "Technical Workshop"
        else:
            event_type = "seminar"
            event_name = "Academic Seminar"

        assumption_suffix = (" " + " ".join(assumptions)) if assumptions else ""
        self._log_step(
            step_no=step_no,
            tool_name="adaptive_intake",
            arguments={
                "prompt": prompt,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "assumptions": assumptions,
            },
            status="completed",
            summary=(
                f"Extracted: Event Type='{event_type.capitalize()}', "
                f"Headcount={headcount} students, Slot={date} ({start_time} - {end_time})."
                f"{assumption_suffix}"
            ),
        )

        # Step 2: Discover and filter free venues with adequate capacity
        step_no += 1
        venue_result = tool_find_free_venues(min_capacity=headcount, date=date, start_time=start_time, end_time=end_time)
        available_venues = venue_result.get("venues", [])

        if not available_venues:
            self._log_step(
                step_no=step_no,
                tool_name="find_free_venues",
                arguments={"min_capacity": headcount, "date": date, "start_time": start_time, "end_time": end_time},
                status="rolled_back",
                summary=f"No hall on campus satisfies requested capacity of {headcount} students on {date}. Proposing alternative hall or date."
            )
            return {
                "success": False,
                "event_id": event_id,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "timeline": self.timeline,
                "error": f"No campus venue satisfies required capacity of {headcount} seats."
            }

        # Select most appropriate venue
        chosen_venue = available_venues[0]
        approval_note = " (Requires Dean Sign-off)" if chosen_venue["requires_special_approval"] else " (Auto-Approved)"
        self._log_step(
            step_no=step_no,
            tool_name="find_free_venues",
            arguments={"min_capacity": headcount, "date": date, "start_time": start_time, "end_time": end_time},
            status="completed",
            summary=f"Discovered {len(available_venues)} available campus halls. Allocated '{chosen_venue['name']}' (Seats: {chosen_venue['capacity']}){approval_note}.",
            details=chosen_venue
        )

        # Step 3: Historical and Smart Recommendations (Sir's feature)
        step_no += 1
        history_result = tool_recommend_from_history(event_type=event_type, headcount=headcount)
        recs = history_result.get("recommendations", [])
        
        items_to_requisition = []
        for r in recs:
            items_to_requisition.append({
                "resource_id": r["resource_id"],
                "quantity": r["suggested_qty"]
            })

        recommendation_summary = (
            f"Synthesized {len(recs)} campus logistics recommendations: "
            f"'{recs[0]['item_name']}' ({recs[0]['reason']})."
            if recs
            else "No campus logistics recommendations are available."
        )
        self._log_step(
            step_no=step_no,
            tool_name="recommend_from_history",
            arguments={"event_type": event_type, "headcount": headcount},
            status="completed",
            summary=recommendation_summary,
            details=recs
        )

        # Step 4: Transactional Requisition guarded by Kavach Safety Layer
        step_no += 1
        booking_res = tool_requisition_campus_resources(
            event_id=event_id,
            room_id=chosen_venue["id"],
            attendance=headcount,
            items_json=json.dumps(items_to_requisition),
            date=date,
            start_time=start_time,
            end_time=end_time,
            budget=budget,
            event_details={
                "name": event_name,
                "brief": prompt,
                "event_type": event_type,
                "expected_participants": headcount,
                "organizer_department": "School of Computing Science",
            }
        )

        if booking_res.get("status") == "committed":
            details = booking_res["details"]
            self._log_step(
                step_no=step_no,
                tool_name="requisition_campus_resources",
                arguments={"room_id": chosen_venue["id"], "items_count": len(items_to_requisition)},
                status="committed",
                summary=f"Kavach Safety checks passed. Confirmed allocation of '{chosen_venue['name']}' and {len(items_to_requisition)} resource bundles.",
                details=details
            )

            # Step 5: Outbox Notice Dispatch
            step_no += 1
            self._log_step(
                step_no=step_no,
                tool_name="dispatch_outbox_notices",
                arguments={"event_id": event_id},
                status="completed",
                summary="Released official notification broadcast from Outbox to event coordinators and department head."
            )

            return {
                "success": True,
                "event_id": event_id,
                "event_name": event_name,
                "event_type": event_type,
                "headcount": headcount,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "venue": chosen_venue["name"],
                "timeline": self.timeline,
                "recommendations": recs,
                "allocation_details": details
            }
        else:
            violation = booking_res.get("violation", {})
            self._log_step(
                step_no=step_no,
                tool_name="requisition_campus_resources",
                arguments={"room_id": chosen_venue["id"]},
                status="rolled_back",
                summary=f"Kavach safety check caught violation: {violation.get('detail')}. State restored via SQLite rollback.",
                details=violation
            )
            return {
                "success": False,
                "event_id": event_id,
                "timeline": self.timeline,
                "violation": violation
            }
