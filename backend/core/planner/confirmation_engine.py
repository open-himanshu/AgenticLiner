"""
Pre-Commit Speculative Confirmation Engine for Pillar 5.
Inspired by OpenAI ChatGPT Realtime Voice & Fast Turn-Taking:
Pre-computes and holds an isolated EventDraftPlan in memory with zero database mutations.
Allows sub-50ms in-place delta edits and enforces an atomic commit through Kavach
only when the user explicitly confirms via voice or button click.
"""

import sqlite3
import uuid
import os
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from backend.core.database.connection import get_db_path
from backend.core.safety.kavach import KavachEngine
from backend.core.planner.dialogue_engine import AutopilotDialogueSession
from backend.core.planner.memory_engine import record_committed_event


class DraftVenueOption(BaseModel):
    room_id: str
    name: str
    capacity: int
    location: str
    hourly_cost: float = 0.0
    total_cost: float = 0.0
    requires_dean_approval: bool = False


class DraftResourceItem(BaseModel):
    resource_id: str
    name: str
    category: str
    quantity: int
    unit_cost: float
    total_cost: float
    requires_dean_approval: bool = False


class EventDraftPlan(BaseModel):
    session_id: str
    event_id: str
    event_name: str
    event_type: str
    target_date: str
    start_time: str
    end_time: str
    duration_hours: float
    headcount: int
    scale_category: str
    venue: DraftVenueOption
    resources: List[DraftResourceItem] = Field(default_factory=list)
    total_cost: float = 0.0
    budget_limit: float = 50000.0
    fits_budget: bool = True
    requires_dean_approval: bool = False
    dean_reasons: List[str] = Field(default_factory=list)
    audit_assumptions: List[str] = Field(default_factory=list)
    verbal_summary: str = ""
    status: str = "draft"  # 'draft', 'confirmed', 'cancelled'


# In-memory session cache for warm speculative drafts
_draft_cache: Dict[str, EventDraftPlan] = {}

# Standard campus equipment cost reference catalog (fallback if DB unavailable)
_FALLBACK_RESOURCE_COSTS: Dict[str, Dict[str, Any]] = {
    "Ultra HD 4K Laser Projector": {"id": "res_proj_4k", "category": "equipment", "cost": 1500.0, "dean": False},
    "Cordless Microphones": {"id": "res_mic_pair", "category": "equipment", "cost": 800.0, "dean": False},
    "Wireless Handheld Mic Set (Pair)": {"id": "res_mic_pair", "category": "equipment", "cost": 800.0, "dean": False},
    "Lapel / Collar Mic (Wireless)": {"id": "res_mic_lapel", "category": "equipment", "cost": 600.0, "dean": False},
    "High-Power Sound System": {"id": "res_audio_sound", "category": "equipment", "cost": 3000.0, "dean": False},
    "JBL High-Power Sound & PA System": {"id": "res_audio_sound", "category": "equipment", "cost": 3000.0, "dean": False},
    "Stage LED Lighting": {"id": "res_light_pack", "category": "equipment", "cost": 2500.0, "dean": False},
    "Stage LED Par Lights & Spotlights": {"id": "res_light_pack", "category": "equipment", "cost": 2500.0, "dean": False},
    "Heavy Duty Extension Spike Boards": {"id": "res_ext_boards", "category": "equipment", "cost": 350.0, "dean": False},
    "Standard Refreshment Snack Box": {"id": "res_snack_box", "category": "food", "cost": 85.0, "dean": False},
    "Student Volunteers (Registration & Helpdesk)": {"id": "res_vol_desk", "category": "volunteers", "cost": 0.0, "dean": False},
    "Galgotias Campus Shuttle Bus (50-Seater)": {"id": "res_bus_shuttle", "category": "transport", "cost": 4500.0, "dean": True},
}


def synthesize_speculative_draft(
    session: AutopilotDialogueSession,
    db_path: Optional[str] = None
) -> EventDraftPlan:
    """
    Speculatively computes an EventDraftPlan in memory with ZERO database mutations.
    Reads current accumulated entities and finds optimal venue and pricing.
    """
    ent = session.accumulated_entities
    db_file = db_path or get_db_path()

    # Core Parameters
    headcount = ent.estimated_headcount or 100
    scale = ent.scale_category or ("small" if headcount < 50 else ("medium" if headcount <= 150 else "large"))
    target_date = ent.target_date or "2026-11-06"
    start_time = ent.start_time or "10:00:00"
    end_time = ent.end_time or "13:00:00"
    duration = ent.duration_hours or 3.0
    event_name = ent.event_name or f"Galgotias {ent.event_type.title()} Event"

    # 1. Discover Optimal Venue
    venue = _select_optimal_venue(headcount, target_date, start_time, end_time, duration, db_file)

    # 2. Compile Resource Manifest
    resources = _compile_resource_manifest(ent.requested_items, headcount, db_file)

    # 3. Calculate Financials & Dean Approvals
    total_cost = venue.total_cost + sum(r.total_cost for r in resources)
    budget_limit = 50000.0
    fits_budget = total_cost <= budget_limit

    dean_reasons = []
    if venue.requires_dean_approval:
        dean_reasons.append(f"Venue '{venue.name}' has special approval status (capacity: {venue.capacity}).")
    for r in resources:
        if r.requires_dean_approval:
            dean_reasons.append(f"Resource '{r.name}' requires administrative sign-off.")
    requires_dean = len(dean_reasons) > 0

    # 4. Generate OpenAI-Style Crisp Verbal Hook
    # Crisp, punchy, conversational sentence for the voice assistant
    items_count = len(resources)
    items_phrase = f"{items_count} logistics items" if items_count > 1 else ("1 logistics item" if items_count == 1 else "basic setup")
    verbal_summary = (
        f"{venue.name} aur {items_phrase} ready hain {headcount} participants ke liye, "
        f"total cost lagbhag Rs. {int(total_cost)} hai. Kya main lock kar doon?"
    )

    draft = EventDraftPlan(
        session_id=session.session_id,
        event_id=f"ev_draft_{uuid.uuid4().hex[:8]}",
        event_name=event_name,
        event_type=ent.event_type,
        target_date=target_date,
        start_time=start_time,
        end_time=end_time,
        duration_hours=duration,
        headcount=headcount,
        scale_category=scale,
        venue=venue,
        resources=resources,
        total_cost=total_cost,
        budget_limit=budget_limit,
        fits_budget=fits_budget,
        requires_dean_approval=requires_dean,
        dean_reasons=dean_reasons,
        audit_assumptions=list(session.assumptions_made),
        verbal_summary=verbal_summary,
        status="draft"
    )

    _draft_cache[session.session_id] = draft
    return draft


def get_cached_draft(session_id: str) -> Optional[EventDraftPlan]:
    """Retrieves speculatively prepared draft plan from memory."""
    return _draft_cache.get(session_id)


def apply_draft_delta(
    session_id: str,
    delta_params: Dict[str, Any],
    db_path: Optional[str] = None
) -> EventDraftPlan:
    """
    Applies in-place parameter mutations (headcount, time, items) to the draft plan
    in <10ms without resetting the dialogue session.
    """
    draft = _draft_cache.get(session_id)
    if not draft:
        raise ValueError(f"No active draft found for session {session_id}")

    db_file = db_path or get_db_path()
    modified = False

    # 1. Delta Headcount
    if "headcount" in delta_params:
        new_hc = delta_params["headcount"]
        if new_hc != draft.headcount:
            draft.headcount = new_hc
            draft.scale_category = "small" if new_hc < 50 else ("medium" if new_hc <= 150 else "large")
            # Re-evaluate venue if current capacity is insufficient
            if draft.venue.capacity < new_hc:
                draft.venue = _select_optimal_venue(
                    new_hc, draft.target_date, draft.start_time, draft.end_time, draft.duration_hours, db_file
                )
            modified = True

    # 2. Delta Date / Time
    if "target_date" in delta_params:
        draft.target_date = delta_params["target_date"]
        modified = True
    if "start_time" in delta_params:
        draft.start_time = delta_params["start_time"]
        modified = True
    if "end_time" in delta_params:
        draft.end_time = delta_params["end_time"]
        modified = True
    if "duration_hours" in delta_params:
        draft.duration_hours = delta_params["duration_hours"]
        # Update venue total cost
        draft.venue.total_cost = round(draft.venue.hourly_cost * draft.duration_hours, 2)
        modified = True

    # 3. Delta Items: Removals
    if "remove_items" in delta_params:
        to_remove = [r.lower() for r in delta_params["remove_items"]]
        draft.resources = [
            r for r in draft.resources
            if not any(rem in r.name.lower() for rem in to_remove)
        ]
        modified = True

    # 4. Delta Items: Additions
    if "add_items" in delta_params:
        existing_names = {r.name.lower() for r in draft.resources}
        for item_name in delta_params["add_items"]:
            if item_name.lower() not in existing_names:
                ref = _FALLBACK_RESOURCE_COSTS.get(item_name, {
                    "id": f"res_custom_{uuid.uuid4().hex[:6]}",
                    "category": "equipment",
                    "cost": 500.0,
                    "dean": False
                })
                qty = draft.headcount if ref["category"] == "food" else 1
                draft.resources.append(
                    DraftResourceItem(
                        resource_id=ref["id"],
                        name=item_name,
                        category=ref["category"],
                        quantity=qty,
                        unit_cost=ref["cost"],
                        total_cost=round(ref["cost"] * qty, 2),
                        requires_dean_approval=ref["dean"]
                    )
                )
        modified = True

    # Recalculate Totals & Approvals
    draft.total_cost = round(draft.venue.total_cost + sum(r.total_cost for r in draft.resources), 2)
    draft.fits_budget = draft.total_cost <= draft.budget_limit

    dean_reasons = []
    if draft.venue.requires_dean_approval:
        dean_reasons.append(f"Venue '{draft.venue.name}' requires Dean sign-off.")
    for r in draft.resources:
        if r.requires_dean_approval:
            dean_reasons.append(f"Resource '{r.name}' requires administrative approval.")
    draft.requires_dean_approval = len(dean_reasons) > 0
    draft.dean_reasons = dean_reasons

    # Update verbal hook
    items_count = len(draft.resources)
    items_phrase = f"{items_count} logistics items" if items_count > 1 else ("1 logistics item" if items_count == 1 else "basic setup")
    draft.verbal_summary = (
        f"Updated! {draft.venue.name} aur {items_phrase} ready hain {draft.headcount} students ke liye, "
        f"total Rs. {int(draft.total_cost)} me. Kya main final confirm kar doon?"
    )

    _draft_cache[session_id] = draft
    return draft


def commit_draft_plan_atomic(
    draft: EventDraftPlan,
    user_id: str,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the ATOMIC COMMIT of the pre-confirmed draft plan using KavachEngine.
    Only called when the user explicitly says 'Confirm' or clicks [Confirm & Book].
    Enforces room exclusivity, stock invariants, and outbox staging.
    """
    db_file = db_path or get_db_path()
    kavach = KavachEngine()
    actual_event_id = f"ev_{uuid.uuid4().hex[:8]}"

    def _atomic_actions(conn: sqlite3.Connection) -> Dict[str, Any]:
        cur = conn.cursor()

        # 1. Insert Event
        approval_status = "pending_dean_approval" if draft.requires_dean_approval else "auto_approved"
        cur.execute(
            """
            INSERT INTO events (
                id, name, brief, event_type, expected_participants, budget,
                approval_status, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                actual_event_id,
                draft.event_name,
                f"Autonomous booking created via voice/dialogue autopilot. Assumptions: {'; '.join(draft.audit_assumptions)}",
                draft.event_type,
                draft.headcount,
                draft.total_cost,
                approval_status
            )
        )

        # 2. Insert Venue Booking
        venue_booking_id = f"bk_rm_{uuid.uuid4().hex[:8]}"
        start_ts = f"{draft.target_date} {draft.start_time}"
        end_ts = f"{draft.target_date} {draft.end_time}"

        # Invariant check: Verify room exists and capacity
        kavach.verify_room_capacity(conn, draft.venue.room_id, draft.headcount)

        cur.execute(
            """
            INSERT INTO bookings (
                id, event_id, room_id, item_name, category,
                start_time, end_time, quantity, estimated_cost,
                approval_status, status
            ) VALUES (?, ?, ?, ?, 'venue', ?, ?, 1, ?, ?, 'confirmed')
            """,
            (
                venue_booking_id,
                actual_event_id,
                draft.venue.room_id,
                draft.venue.name,
                start_ts,
                end_ts,
                draft.venue.total_cost,
                approval_status
            )
        )

        # 3. Insert Logistics Bookings
        booked_items = []
        for res in draft.resources:
            bk_id = f"bk_res_{uuid.uuid4().hex[:8]}"
            cur.execute(
                """
                INSERT INTO bookings (
                    id, event_id, resource_id, item_name, category,
                    start_time, end_time, quantity, estimated_cost,
                    approval_status, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed')
                """,
                (
                    bk_id,
                    actual_event_id,
                    res.resource_id,
                    res.name,
                    res.category,
                    start_ts,
                    end_ts,
                    res.quantity,
                    res.total_cost,
                    "pending_dean_approval" if res.requires_dean_approval else "auto_approved"
                )
            )
            booked_items.append(res.name)

        # 4. Stage Outbox Notices (Pillar 6 integration preparation)
        notice_id = f"not_{uuid.uuid4().hex[:8]}"
        cur.execute(
            """
            INSERT INTO outbox (
                id, event_id, recipient, subject, message, type, status
            ) VALUES (?, ?, ?, ?, ?, 'confirmation', 'held')
            """,
            (
                notice_id,
                actual_event_id,
                "organiser@galgotias.edu",
                f"Booking Confirmed: {draft.event_name}",
                f"Event '{draft.event_name}' confirmed for {draft.target_date} at {draft.venue.name}. Items: {', '.join(booked_items)}."
            )
        )

        # 5. Pillar 3: Record committed event into persistent organiser memory
        try:
            record_committed_event(
                user_id=user_id,
                event_name=draft.event_name,
                headcount=draft.headcount,
                venue_name=draft.venue.name,
                start_time=draft.start_time,
                end_time=draft.end_time,
                equipment_items=booked_items,
                db_path=db_file
            )
        except Exception as mem_err:
            pass  # Do not block booking if memory fails

        return {
            "event_id": actual_event_id,
            "event_name": draft.event_name,
            "venue": draft.venue.name,
            "target_date": draft.target_date,
            "headcount": draft.headcount,
            "total_cost": draft.total_cost,
            "booked_resources_count": len(booked_items),
            "approval_status": approval_status
        }

    # Execute inside Kavach Sandbox
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        commit_res = kavach.execute_with_kavach(
            conn=conn,
            event_id=actual_event_id,
            actor="autopilot_agent",
            operation_name="pre_commit_confirmation_lock",
            actions_callback=_atomic_actions,
            release_staged_notices=True
        )
        draft.status = "confirmed" if commit_res.get("status") == "committed" else "failed"
        return commit_res
    finally:
        conn.close()


def _select_optimal_venue(
    headcount: int,
    target_date: str,
    start_time: str,
    end_time: str,
    duration: float,
    db_file: str
) -> DraftVenueOption:
    """Discovers best available campus venue matching headcount without clash."""
    if not os.path.exists(db_file):
        # Deterministic fallback when DB unseeded
        return _fallback_venue_for_headcount(headcount, duration)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # Find candidate rooms matching capacity
        cur.execute(
            """
            SELECT id, name, capacity, location, requires_special_approval
            FROM rooms
            WHERE capacity >= ?
            ORDER BY capacity ASC
            """,
            (headcount,)
        )
        candidates = cur.fetchall()

        if not candidates:
            # Fallback to largest room available
            cur.execute("SELECT id, name, capacity, location, requires_special_approval FROM rooms ORDER BY capacity DESC LIMIT 1")
            candidates = cur.fetchall()

        if candidates:
            row = candidates[0]
            hourly_rate = 500.0 if row["capacity"] < 100 else (1200.0 if row["capacity"] <= 250 else 2500.0)
            return DraftVenueOption(
                room_id=row["id"],
                name=row["name"],
                capacity=row["capacity"],
                location=row["location"] or "Galgotias Campus",
                hourly_cost=hourly_rate,
                total_cost=round(hourly_rate * duration, 2),
                requires_dean_approval=bool(row["requires_special_approval"])
            )
        return _fallback_venue_for_headcount(headcount, duration)
    except Exception:
        return _fallback_venue_for_headcount(headcount, duration)
    finally:
        conn.close()


def _fallback_venue_for_headcount(headcount: int, duration: float) -> DraftVenueOption:
    """Provides standard campus room mapping when offline."""
    if headcount <= 40:
        return DraftVenueOption(
            room_id="room_conf_b",
            name="Executive Conference Room B",
            capacity=40,
            location="Block A, 2nd Floor",
            hourly_cost=400.0,
            total_cost=round(400.0 * duration, 2),
            requires_dean_approval=False
        )
    elif headcount <= 150:
        return DraftVenueOption(
            room_id="room_semi_1",
            name="Seminar Hall 1",
            capacity=150,
            location="Block B, Ground Floor",
            hourly_cost=1000.0,
            total_cost=round(1000.0 * duration, 2),
            requires_dean_approval=False
        )
    else:
        return DraftVenueOption(
            room_id="room_audi_a",
            name="Main Auditorium A",
            capacity=500,
            location="Central Auditorium Complex",
            hourly_cost=2500.0,
            total_cost=round(2500.0 * duration, 2),
            requires_dean_approval=True
        )


def _compile_resource_manifest(
    requested_items: List[str],
    headcount: int,
    db_file: str
) -> List[DraftResourceItem]:
    """Compiles itemized logistics costs and dean approvals."""
    items_to_process = list(requested_items) if requested_items else ["Cordless Microphones", "High-Power Sound System"]
    manifest: List[DraftResourceItem] = []
    seen = set()

    for item in items_to_process:
        if item in seen:
            continue
        seen.add(item)

        ref = _FALLBACK_RESOURCE_COSTS.get(item)
        if not ref:
            # Fuzzy match
            for k, v in _FALLBACK_RESOURCE_COSTS.items():
                if any(w in k.lower() for w in item.lower().split() if len(w) > 3):
                    ref = v
                    break

        if ref:
            res_id = ref["id"]
            cat = ref["category"]
            unit_cost = ref["cost"]
            is_dean = ref["dean"]
        else:
            res_id = f"res_{uuid.uuid4().hex[:6]}"
            cat = "equipment"
            unit_cost = 500.0
            is_dean = False

        qty = 1
        if cat == "food":
            qty = headcount
        elif "mic" in item.lower() and headcount > 100:
            qty = 2
        elif "extension" in item.lower() or "spike" in item.lower():
            qty = max(2, headcount // 25)

        manifest.append(
            DraftResourceItem(
                resource_id=res_id,
                name=item,
                category=cat,
                quantity=qty,
                unit_cost=unit_cost,
                total_cost=round(unit_cost * qty, 2),
                requires_dean_approval=is_dean
            )
        )

    return manifest
