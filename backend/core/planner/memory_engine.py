"""
Dynamic Preference Learning & Context Enrichment Engine (Pillar 3 - Section 2).
Learns organiser preferences from committed events and injects historical habits
into natural language intake and conversational dialogue.
"""

from __future__ import annotations

import logging
import re
from datetime import date as CalendarDate, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.core.planner.memory_store import (
    OrganiserMemoryProfile,
    get_organiser_memory,
    save_organiser_memory,
    add_memory_note,
)
from backend.core.planner.natural_intake import ExtractedEventEntities

logger = logging.getLogger("agenticliner.memory_engine")

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def record_committed_event(
    user_id: str,
    event_name: str,
    venue_name: Optional[str] = None,
    headcount: Optional[int] = None,
    equipment_items: Optional[List[str]] = None,
    target_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    department: Optional[str] = None
) -> OrganiserMemoryProfile:
    """
    Called when an autopilot planning run is successfully committed.
    Updates rolling statistics, favourite venues, and common logistics items.
    """
    profile = get_organiser_memory(user_id)
    profile.total_events_planned += 1

    if department:
        profile.department = department

    if target_date:
        profile.last_event_date = target_date
        try:
            # Parse day of week
            dt = CalendarDate.fromisoformat(target_date)
            day_name = _DAY_NAMES[dt.weekday()]
            if day_name not in profile.preferred_days:
                profile.preferred_days.insert(0, day_name)
                # Keep top 3 preferred days
                profile.preferred_days = profile.preferred_days[:3]
        except Exception:
            pass

    # 1. Update Rolling Headcount
    if headcount and headcount > 0:
        if profile.total_events_planned == 1:
            profile.typical_headcount = headcount
        else:
            # Weighted rolling average: give 60% weight to history, 40% to latest
            profile.typical_headcount = round(
                (profile.typical_headcount * 0.6) + (headcount * 0.4)
            )

    # 2. Update Favourite Venues Frequency
    if venue_name:
        venue_clean = venue_name.strip()
        found = False
        for v in profile.favourite_venues:
            if v.get("venue", "").lower() == venue_clean.lower():
                v["count"] = v.get("count", 0) + 1
                found = True
                break
        if not found:
            profile.favourite_venues.append({"venue": venue_clean, "count": 1})

        # Sort descending by booking frequency
        profile.favourite_venues.sort(key=lambda x: x.get("count", 0), reverse=True)

    # 3. Update Favourite Equipment
    if equipment_items:
        for item in equipment_items:
            clean_item = item.strip()
            if clean_item and clean_item not in profile.favourite_equipment:
                profile.favourite_equipment.append(clean_item)

    # 4. Update Time Slots
    if start_time:
        profile.preferred_start_time = start_time
    if end_time:
        profile.preferred_end_time = end_time

    save_organiser_memory(profile)
    logger.info(f"Updated memory profile for {user_id}: total {profile.total_events_planned} events.")
    return profile


def extract_explicit_memory_facts(user_id: str, prompt: str) -> List[str]:
    """
    Detects explicit organiser preference declarations in natural language
    (e.g., 'we always need 2 cordless mics', 'humare events me 150 bache aate hain')
    and saves them to memory_notes.
    """
    lower = prompt.lower()
    discovered_facts = []

    # Detect always / humesha preferences
    if "always" in lower or "humesha" in lower or "standard" in lower or "regular" in lower:
        if any(k in lower for k in ["mic", "microphone"]):
            discovered_facts.append("Always requires cordless microphones for presentations.")
        if any(k in lower for k in ["projector", "screen"]):
            discovered_facts.append("Prefers rooms equipped with high-definition digital projector.")
        if any(k in lower for k in ["buffet", "lunch", "refreshment"]):
            discovered_facts.append("Prefers catering / lunch arrangements for attendees.")
        if any(k in lower for k in ["recording", "video"]):
            discovered_facts.append("Standard requirement: session video recording.")

    # Save to memory profile
    for fact in discovered_facts:
        add_memory_note(user_id, fact)

    return discovered_facts


def enrich_entities_with_organiser_memory(
    entities: ExtractedEventEntities,
    user_id: str
) -> Tuple[ExtractedEventEntities, List[str]]:
    """
    Enriches incoming prompt entities using the organiser's persistent memory.
    Fills in missing headcount and logistics if absent from the prompt,
    drastically reducing the need for counter-questions.
    
    Returns:
        (enriched_entities, list_of_memory_assumptions)
    """
    profile = get_organiser_memory(user_id)
    assumptions = []

    # Only apply memory defaults if the organiser has past event history or saved notes
    has_history = profile.total_events_planned > 0 or len(profile.favourite_venues) > 0

    if not has_history:
        return entities, assumptions

    # 1. Enrich missing headcount
    if entities.estimated_headcount is None and profile.typical_headcount:
        entities.estimated_headcount = profile.typical_headcount
        entities.scale_category = (
            "small" if profile.typical_headcount < 50
            else ("medium" if profile.typical_headcount <= 150 else "large")
        )
        if "headcount" in entities.missing_critical_fields:
            entities.missing_critical_fields.remove("headcount")
        if "scale" in entities.missing_critical_fields:
            entities.missing_critical_fields.remove("scale")

        assumptions.append(
            f"Recalled your typical turnout ({profile.typical_headcount} attendees) from past events."
        )

    # 2. Enrich missing logistics equipment
    if not entities.requested_items and profile.favourite_equipment:
        entities.requested_items = list(profile.favourite_equipment[:3])
        assumptions.append(
            f"Auto-loaded your favourite logistics package ({', '.join(entities.requested_items)})."
        )

    # Re-evaluate planning readiness
    entities.is_ready_for_planning = (len(entities.missing_critical_fields) == 0)
    return entities, assumptions


def get_memory_badge_summary(user_id: str) -> Dict[str, Any]:
    """
    Returns structured data for the frontend memory indicator badge.
    """
    profile = get_organiser_memory(user_id)
    if profile.total_events_planned == 0 and not profile.favourite_venues:
        return {
            "has_memory": False,
            "badge_text": "New Organiser (No Past Memory)",
            "summary": "Agent is learning your preferences.",
            "top_venue": None,
            "typical_headcount": 100,
            "events_count": 0
        }

    top_venue = profile.favourite_venues[0]["venue"] if profile.favourite_venues else None
    parts = []
    if top_venue:
        parts.append(f"Prefers {top_venue}")
    if profile.typical_headcount:
        parts.append(f"~{profile.typical_headcount} students")
    if profile.preferred_days:
        parts.append(f"{profile.preferred_days[0]}s")

    return {
        "has_memory": True,
        "badge_text": f"Memory Active: {', '.join(parts)}",
        "summary": f"Learned from {profile.total_events_planned} past campus events.",
        "top_venue": top_venue,
        "typical_headcount": profile.typical_headcount,
        "favourite_equipment": profile.favourite_equipment,
        "memory_notes": profile.memory_notes,
        "events_count": profile.total_events_planned
    }
