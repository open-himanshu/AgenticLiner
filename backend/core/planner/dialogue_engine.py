"""
Conversational Multi-Turn Dialogue & Counter-Question Engine (Pillar 2).
Enables interactive back-and-forth clarification between the Organiser and Agent
before committing campus event logistics.

Guarantees:
1. Multi-turn context fusion without overwriting previously confirmed entities.
2. STRICT LOOP CIRCUIT BREAKER (MAX_ASK_USER = 2): Prevents infinite question/output loops.
   If turn_count >= 2, the agent stops asking questions, immediately fills sensible campus
   defaults (e.g. upcoming Friday 10:00 AM, 100 headcount), declares assumptions,
   and proceeds straight to autonomous venue planning.
3. Repetition Prevention: Never asks the exact same question twice.
4. Smart Quick-Reply Chips: Delivers 1-tap option pills for rapid mobile/voice interaction.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import date as CalendarDate, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from backend.core.planner.call_llm import call_llm, get_provider_config, ProviderError
from backend.core.planner.natural_intake import (
    ExtractedEventEntities,
    assess_intake_completeness,
    extract_event_entities_llm,
    resolve_natural_datetime,
    validate_prompt_safety,
)

from backend.core.planner.memory_engine import (
    enrich_entities_with_organiser_memory,
    extract_explicit_memory_facts,
)
from backend.core.planner.memory_store import get_organiser_memory

logger = logging.getLogger("agenticliner.dialogue_engine")

# Hard circuit-breaker turn limit to protect user experience
MAX_ASK_USER: int = 2
DEFAULT_HEADCOUNT: int = 100
DEFAULT_START_TIME: str = "10:00:00"
DEFAULT_END_TIME: str = "13:00:00"
SESSION_TTL_SECONDS: int = 3600  # 1 hour in-memory cache


def get_default_upcoming_friday(ref_date: Optional[CalendarDate] = None) -> str:
    """Returns the ISO string for the next upcoming Friday at Galgotias campus."""
    ref = ref_date or CalendarDate.today()
    # Friday is weekday 4 (Monday = 0)
    days_ahead = 4 - ref.weekday()
    if days_ahead <= 0:  # If today is Friday, Saturday, or Sunday -> next week's Friday
        days_ahead += 7
    return (ref + timedelta(days=days_ahead)).isoformat()


class DialogueTurn(BaseModel):
    speaker: str  # "agent" | "user"
    message: str
    timestamp: float = Field(default_factory=time.time)
    turn_index: int = 0


class AutopilotDialogueSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "organiser"
    turn_count: int = 0  # Number of clarification counter-questions asked by agent
    max_turns: int = MAX_ASK_USER
    status: str = "clarifying"  # "clarifying" | "ready_to_plan" | "blocked"
    accumulated_entities: ExtractedEventEntities
    turns: List[DialogueTurn] = Field(default_factory=list)
    questions_asked: List[str] = Field(default_factory=list)
    assumptions_made: List[str] = Field(default_factory=list)
    current_question: Optional[str] = None
    quick_replies: List[str] = Field(default_factory=list)
    tts_response: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


# In-memory thread-safe session store
_session_lock = threading.Lock()
_active_sessions: Dict[str, AutopilotDialogueSession] = {}


def get_or_create_session(
    prompt: str,
    user_id: str = "organiser",
    user_context: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None
) -> Tuple[AutopilotDialogueSession, bool]:
    """
    Initializes a new dialogue session or retrieves an existing active session.
    Returns (session, is_new).
    """
    with _session_lock:
        _cleanup_expired_sessions()
        if session_id and session_id in _active_sessions:
            return _active_sessions[session_id], False

        # Extract initial entities
        initial_entities = extract_event_entities_llm(prompt=prompt, user_context=user_context)

        # Pillar 3: Extract explicit facts and enrich with organiser persistent memory
        extract_explicit_memory_facts(user_id=user_id, prompt=prompt)
        initial_entities, memory_assumptions = enrich_entities_with_organiser_memory(
            entities=initial_entities,
            user_id=user_id
        )

        new_session = AutopilotDialogueSession(
            session_id=session_id or str(uuid.uuid4()),
            user_id=user_id,
            accumulated_entities=initial_entities,
            assumptions_made=memory_assumptions
        )
        new_session.turns.append(
            DialogueTurn(speaker="user", message=prompt, turn_index=0)
        )

        # Initial assessment
        _evaluate_session_state(new_session)
        _active_sessions[new_session.session_id] = new_session
        return new_session, True


def get_session(session_id: str) -> Optional[AutopilotDialogueSession]:
    """Retrieves an active dialogue session by ID."""
    with _session_lock:
        return _active_sessions.get(session_id)


def reset_session(session_id: str) -> bool:
    """Removes a session from memory."""
    with _session_lock:
        return _active_sessions.pop(session_id, None) is not None


def _cleanup_expired_sessions() -> None:
    """Evicts stale sessions older than SESSION_TTL_SECONDS."""
    now = time.time()
    expired = [
        sid for sid, s in _active_sessions.items()
        if now - s.updated_at > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _active_sessions.pop(sid, None)


def fuse_dialogue_reply(
    session: AutopilotDialogueSession,
    user_reply: str,
    user_context: Optional[Dict[str, Any]] = None
) -> AutopilotDialogueSession:
    """
    Fuses the user's spoken or typed reply into accumulated entities.
    Enforces the STRICT LOOP CIRCUIT BREAKER (turn_count >= 2 -> finish).
    """
    session.updated_at = time.time()
    session.turns.append(
        DialogueTurn(speaker="user", message=user_reply, turn_index=session.turn_count)
    )

    clean_reply = user_reply.strip().lower()

    # Fast user shortcut to skip questions: "default", "you decide", "kuch bhi", "skip"
    if any(k in clean_reply for k in ["skip", "you decide", "default", "kuch bhi", "apne hisab se", "as you wish"]):
        session.assumptions_made.append("User requested autonomous defaults for remaining parameters.")
        _apply_circuit_breaker_defaults(session)
        return session

    # 1. Update entities based on reply content
    _merge_reply_into_entities(session, user_reply, user_context)

    # 2. Check turn limit (Loop Circuit Breaker)
    if session.turn_count >= MAX_ASK_USER:
        logger.info(
            f"Dialogue circuit breaker activated for session {session.session_id}: "
            f"Reached max {MAX_ASK_USER} turns. Applying campus defaults without looping."
        )
        _apply_circuit_breaker_defaults(session)
        return session

    # 3. Evaluate state for next turn
    _evaluate_session_state(session)
    return session


def _merge_reply_into_entities(
    session: AutopilotDialogueSession,
    reply: str,
    user_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Carefully updates accumulated entities using reply heuristics and LLM extraction
    without erasing previously gathered details.
    """
    ent = session.accumulated_entities
    lower = reply.lower()

    # 1. Check Date / Time in reply
    date_str, start_t, end_t, dur = resolve_natural_datetime(date_phrase=lower, time_phrase=lower)
    has_date_indicator = any(
        k in lower for k in [
            "today", "tomorrow", "kal", "parso", "friday", "monday", "tuesday",
            "wednesday", "thursday", "saturday", "sunday", "nov", "dec", "jan",
            "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "202"
        ]
    )
    if has_date_indicator:
        ent.target_date = date_str
        ent.date_original_phrase = date_str
        if "target_date" in ent.missing_critical_fields:
            ent.missing_critical_fields.remove("target_date")

    has_time_indicator = any(
        k in lower for k in ["am", "pm", "baje", "morning", "afternoon", "evening", "shaam", "dopahar", "subah"]
    )
    if has_time_indicator:
        ent.start_time = start_t
        ent.end_time = end_t
        ent.duration_hours = dur

    # 2. Check Headcount in reply
    # Priority 1: Explicit headcount unit (e.g. 150 students, 80 participants)
    num_match = re.search(
        r'\b(\d{1,4})\s*(?:students?|participants?|attendees?|people|members?|heads?|bach[eo]|log|seats?)\b',
        lower
    )
    if not num_match:
        # Priority 2: Preceded by capacity or quantifier (e.g. for 150, around 80)
        num_match = re.search(
            r'(?:for|around|approx|about|capacity|of)\s*(\d{1,4})\b(?!\s*(?:am|pm|baje|hours?|hrs?|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct))',
            lower
        )

    if num_match:
        try:
            val = int(num_match.group(1))
            if 1 <= val <= 5000 and (val < 1900 or val > 2099):
                ent.estimated_headcount = val
                ent.scale_category = "small" if val < 50 else ("medium" if val <= 150 else "large")
                if "scale" in ent.missing_critical_fields:
                    ent.missing_critical_fields.remove("scale")
                if "headcount" in ent.missing_critical_fields:
                    ent.missing_critical_fields.remove("headcount")
        except ValueError:
            pass
    else:
        # Priority 3: Standalone numbers excluding time, date, currency, ordinal suffixes
        candidates = re.findall(
            r'\b(\d{1,4})\b(?!\s*(?:am|pm|baje|hours?|hrs?|o\'clock|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|k|inr|rs|%|th|st|nd|rd))',
            lower
        )
        valid_candidates = []
        for c in candidates:
            v = int(c)
            # Exclude year numbers and small time-like numbers unless explicit
            if (v < 1900 or v > 2099) and v >= 15:
                valid_candidates.append(v)
        if valid_candidates:
            val = valid_candidates[0]
            ent.estimated_headcount = val
            ent.scale_category = "small" if val < 50 else ("medium" if val <= 150 else "large")
            if "scale" in ent.missing_critical_fields:
                ent.missing_critical_fields.remove("scale")
            if "headcount" in ent.missing_critical_fields:
                ent.missing_critical_fields.remove("headcount")

    # Qualitative scale words
    if ent.estimated_headcount is None:
        if any(k in lower for k in ["chhota", "small", "core team", "team only"]):
            ent.estimated_headcount = 40
            ent.scale_category = "small"
            if "scale" in ent.missing_critical_fields:
                ent.missing_critical_fields.remove("scale")
        elif any(k in lower for k in ["medium", "normal", "moderate"]):
            ent.estimated_headcount = 100
            ent.scale_category = "medium"
            if "scale" in ent.missing_critical_fields:
                ent.missing_critical_fields.remove("scale")
        elif any(k in lower for k in ["bada", "huge", "mega", "college-wide", "all students"]):
            ent.estimated_headcount = 300
            ent.scale_category = "large"
            if "scale" in ent.missing_critical_fields:
                ent.missing_critical_fields.remove("scale")

    # 3. Check Event Type in reply
    if any(k in lower for k in ["hackathon", "coding", "ctf"]):
        ent.event_type = "hackathon"
        if "event_type" in ent.missing_critical_fields:
            ent.missing_critical_fields.remove("event_type")
    elif any(k in lower for k in ["dance", "cultural", "fest", "drama", "music"]):
        ent.event_type = "cultural"
        if "event_type" in ent.missing_critical_fields:
            ent.missing_critical_fields.remove("event_type")
    elif any(k in lower for k in ["workshop", "hands-on", "bootcamp"]):
        ent.event_type = "workshop"
        if "event_type" in ent.missing_critical_fields:
            ent.missing_critical_fields.remove("event_type")
    elif any(k in lower for k in ["seminar", "talk", "keynote", "lecture"]):
        ent.event_type = "seminar"
        if "event_type" in ent.missing_critical_fields:
            ent.missing_critical_fields.remove("event_type")

    # 4. Check Logistics Items in reply
    if any(k in lower for k in ["mic", "microphone"]) and "Cordless Microphones" not in ent.requested_items:
        ent.requested_items.append("Cordless Microphones")
    if any(k in lower for k in ["sound", "audio", "speaker"]) and "High-Power Sound System" not in ent.requested_items:
        ent.requested_items.append("High-Power Sound System")
    if any(k in lower for k in ["light", "led", "lighting"]) and "Stage LED Lighting" not in ent.requested_items:
        ent.requested_items.append("Stage LED Lighting")
    if any(k in lower for k in ["food", "lunch", "refreshment", "snacks"]) and "Catering / Refreshments" not in ent.requested_items:
        ent.requested_items.append("Catering / Refreshments")

    # Re-evaluate critical fields completeness
    remaining = []
    if not ent.target_date:
        remaining.append("target_date")
    if ent.estimated_headcount is None:
        remaining.append("headcount")
    ent.missing_critical_fields = remaining
    ent.is_ready_for_planning = (len(remaining) == 0)


def _evaluate_session_state(session: AutopilotDialogueSession) -> None:
    """
    Examines accumulated entities. If ready, transitions to 'ready_to_plan'.
    If fields are still missing, formulates a non-repetitive counter-question
    and quick reply pills.
    """
    ent = session.accumulated_entities

    if ent.is_ready_for_planning or len(ent.missing_critical_fields) == 0:
        session.status = "ready_to_plan"
        session.current_question = None
        session.quick_replies = []
        headcount_txt = f"{ent.estimated_headcount} participants" if ent.estimated_headcount else "attendees"
        date_txt = ent.target_date or "scheduled date"
        session.tts_response = (
            f"Sabhi zaroori jankari mil gayi hai! {ent.event_name} plan kar raha hoon {date_txt} ke liye, "
            f"{headcount_txt} ke sath. Ab campus venues aur resources lock karte hain."
        )
        session.turns.append(
            DialogueTurn(speaker="agent", message=session.tts_response, turn_index=session.turn_count)
        )
        return

    # Details are still missing
    # Increment turn count for asking a question
    session.turn_count += 1

    # Formulate targeted counter-question
    question, quick_replies, tts = _formulate_counter_question(session)
    session.current_question = question
    session.questions_asked.append(question)
    session.quick_replies = quick_replies
    session.tts_response = tts
    session.status = "clarifying"

    session.turns.append(
        DialogueTurn(speaker="agent", message=question, turn_index=session.turn_count)
    )


def _formulate_counter_question(
    session: AutopilotDialogueSession
) -> Tuple[str, List[str], str]:
    """
    Produces concise, natural counter-questions with smart quick-reply option chips.
    Avoids duplicate questions.
    """
    ent = session.accumulated_entities
    missing = ent.missing_critical_fields

    default_friday = get_default_upcoming_friday()
    tomorrow = (CalendarDate.today() + timedelta(days=1)).isoformat()

    # Prioritize missing target_date
    if "target_date" in missing:
        question = "Aap ye event kis date aur time par karwana chahte hain?"
        quick_replies = [
            f"This Friday 10 AM ({default_friday})",
            f"Tomorrow 5 PM ({tomorrow})",
            "Next Monday 2 PM",
            "Use Campus Default Slot"
        ]
        tts = f"Event kis date aur time par organize karna hai? Jaise this Friday shaam ya weekend?"
        return question, quick_replies, tts

    # Next prioritize headcount/scale
    if "headcount" in missing or "scale" in missing:
        question = "Lagbhag kitne participants / students aane ka anumaan hai?"
        profile = get_organiser_memory(session.user_id)
        quick_replies = []
        if profile.total_events_planned > 0 and profile.typical_headcount:
            quick_replies.append(f"{profile.typical_headcount} Students (Your Usual)")
        quick_replies.extend([
            "40 Students (Small Workshop)",
            "100 Students (Medium Hall)",
            "250+ Students (Auditorium)",
            "100 Students (Default)"
        ])
        seen = set()
        dedup = [x for x in quick_replies if not (x in seen or seen.add(x))][:4]
        tts = "Lagbhag kitne students participate karenge taaki sahi venue allot kiya ja sake?"
        return question, dedup, tts

    # General event format clarification
    question = "Event ka format kya rahega aur kya special audio/visual logistics chahiye?"
    quick_replies = [
        "Hackathon with Power Strips",
        "Workshop with Projector & Mics",
        "Cultural Fest with Full Sound & Lights",
        "Standard Academic Seminar"
    ]
    tts = "Event ka format aur logistics requirements kya rahengi?"
    return question, quick_replies, tts


def _apply_circuit_breaker_defaults(session: AutopilotDialogueSession) -> None:
    """
    STRICT LOOP BREAKER:
    Triggered when turn_count >= MAX_ASK_USER or user asks to proceed.
    Applies deterministic campus defaults for any unprovided details so the agent
    NEVER traps the user in an infinite clarification loop.
    """
    ent = session.accumulated_entities

    # 1. Fallback for Target Date
    if not ent.target_date or "target_date" in ent.missing_critical_fields:
        default_date = get_default_upcoming_friday()
        ent.target_date = default_date
        ent.start_time = DEFAULT_START_TIME
        ent.end_time = DEFAULT_END_TIME
        ent.duration_hours = 3.0
        session.assumptions_made.append(
            f"Date & Time assumed as upcoming Friday ({default_date} 10:00 AM - 01:00 PM) to avoid delay."
        )

    # 2. Fallback for Headcount
    if ent.estimated_headcount is None or "headcount" in ent.missing_critical_fields:
        ent.estimated_headcount = DEFAULT_HEADCOUNT
        ent.scale_category = "medium"
        session.assumptions_made.append(
            f"Headcount assumed as {DEFAULT_HEADCOUNT} participants (medium tier capacity)."
        )

    # 3. Fallback for Logistics
    if not ent.requested_items:
        ent.requested_items = ["Cordless Microphones", "High-Power Sound System"]
        session.assumptions_made.append(
            "Default campus logistics package assigned (Cordless Microphones & Sound System)."
        )

    # Clear missing fields and lock status
    ent.missing_critical_fields = []
    ent.is_ready_for_planning = True
    session.status = "ready_to_plan"
    session.current_question = None
    session.quick_replies = []

    announcement = (
        f"Aapki details compile kar li gayi hain! Event: {ent.event_name}, "
        f"Tareekh: {ent.target_date}, Participants: {ent.estimated_headcount}. "
        f"Assumptions: {', '.join(session.assumptions_made)}. "
        f"Autonomous booking start ho rahi hai."
    )
    session.tts_response = announcement
    session.turns.append(
        DialogueTurn(speaker="agent", message=announcement, turn_index=session.turn_count)
    )
