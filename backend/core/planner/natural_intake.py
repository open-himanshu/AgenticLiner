"""
Natural Language Intake & Entity Extraction Engine (Pillar 1 - Section 2).
Replaces rigid regex matching with LLM-powered context understanding,
relative calendar & time resolution, and proactive clarifying questions.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date as CalendarDate, datetime, time as ClockTime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.core.planner.call_llm import call_llm, get_provider_config, ProviderError

logger = logging.getLogger("agenticliner.natural_intake")

# Destructive action patterns blocked immediately by Kavach
_DESTRUCTIVE_PATTERNS = [
    r"\bcancel\s+(all|every)\b",
    r"\bdelete\s+(all|every)\b",
    r"\bdrop\s+(all|every|table|database)\b",
    r"\bpurge\b",
    r"\bwipe\b",
    r"\btruncate\b",
    r"\bdestroy\b",
]

class ExtractedEventEntities(BaseModel):
    raw_prompt: str
    event_name: str = "Campus Event"
    event_type: str = "general"          # hackathon | cultural | workshop | seminar | sports | general
    estimated_headcount: Optional[int] = None
    scale_category: str = "unknown"      # small (<50) | medium (50-150) | large (>150) | unknown
    target_date: Optional[str] = None    # YYYY-MM-DD
    date_original_phrase: Optional[str] = None
    start_time: str = "10:00:00"         # HH:MM:SS
    end_time: str = "13:00:00"           # HH:MM:SS
    duration_hours: float = 3.0
    budget_limit: Optional[float] = None
    requested_items: List[str] = Field(default_factory=list)
    missing_critical_fields: List[str] = Field(default_factory=list)
    is_ready_for_planning: bool = False
    clarification_prompt: Optional[str] = None
    language_used: str = "en"            # en | hi | hinglish


def validate_prompt_safety(prompt: str) -> Tuple[bool, Optional[str]]:
    """
    Kavach Safety Guard: Validates that the input prompt does not contain
    destructive mass-deletion commands.
    """
    lower = prompt.lower().strip()
    for pat in _DESTRUCTIVE_PATTERNS:
        if re.search(pat, lower):
            return False, "Destructive prompt detected and blocked by Kavach safety filter."
    return True, None


def resolve_natural_datetime(
    date_phrase: Optional[str] = None,
    time_phrase: Optional[str] = None,
    ref_date: Optional[CalendarDate] = None
) -> Tuple[str, str, str, float]:
    """
    Translates colloquial relative date/time expressions into exact ISO formats.
    Handles 'tomorrow', 'this Friday', 'next Monday', 'kal shaam', '28 Nov', etc.

    Returns:
        (target_date_str [YYYY-MM-DD], start_time_str [HH:MM:SS], end_time_str [HH:MM:SS], duration_hours [float])
    """
    today = ref_date or CalendarDate.today()
    clean_date = (date_phrase or "").lower().strip()
    clean_time = (time_phrase or "").lower().strip()

    # 1. Resolve Target Date
    target_date = None

    # Check for direct ISO date (e.g. 2026-11-28)
    iso_match = re.search(r'\b(202\d-\d{2}-\d{2})\b', clean_date)
    if iso_match:
        target_date = iso_match.group(1)

    # Check for DD/MM/YYYY or DD-MM-YYYY
    slash_match = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](202\d)\b', clean_date)
    if not target_date and slash_match:
        d, m, y = int(slash_match.group(1)), int(slash_match.group(2)), int(slash_match.group(3))
        try:
            target_date = CalendarDate(y, m, d).isoformat()
        except ValueError:
            pass

    # Check for Month Name e.g. "28 Nov", "28th November", "Nov 28"
    month_map = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
        "nov": 11, "november": 11, "dec": 12, "december": 12
    }
    month_pat = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\b|\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b', clean_date)
    if not target_date and month_pat:
        if month_pat.group(1) and month_pat.group(2) in month_map:
            d_val = int(month_pat.group(1))
            m_val = month_map[month_pat.group(2)]
            target_date = CalendarDate(today.year, m_val, d_val).isoformat()
        elif month_pat.group(3) in month_map and month_pat.group(4):
            d_val = int(month_pat.group(4))
            m_val = month_map[month_pat.group(3)]
            target_date = CalendarDate(today.year, m_val, d_val).isoformat()

    # Relative Day offsets
    if not target_date:
        if "today" in clean_date or "aaj" in clean_date:
            target_date = today.isoformat()
        elif "tomorrow" in clean_date or "kal" in clean_date:
            target_date = (today + timedelta(days=1)).isoformat()
        elif "day after tomorrow" in clean_date or "parso" in clean_date:
            target_date = (today + timedelta(days=2)).isoformat()
        else:
            # Weekdays: monday=0, tuesday=1, ..., sunday=6
            weekdays = {
                "monday": 0, "somwar": 0,
                "tuesday": 1, "mangalwar": 1,
                "wednesday": 2, "budhwar": 2,
                "thursday": 3, "guruwar": 3,
                "friday": 4, "shukrawar": 4,
                "saturday": 5, "shaniwar": 5,
                "sunday": 6, "ravivar": 6
            }
            for w_name, w_idx in weekdays.items():
                if w_name in clean_date:
                    cur_w = today.weekday()
                    offset = (w_idx - cur_w) % 7
                    if offset == 0:
                        offset = 7 # Next occurrence
                    target_date = (today + timedelta(days=offset)).isoformat()
                    break

    # Default fallback date: upcoming Friday or +3 days
    if not target_date:
        days_to_fri = (4 - today.weekday()) % 7 or 7
        target_date = (today + timedelta(days=days_to_fri)).isoformat()

    # 2. Resolve Start & End Time
    combined_time = f"{clean_date} {clean_time}".lower()
    start_time = "10:00:00"
    end_time = "13:00:00"
    duration_hours = 3.0

    # Specific hour detection (e.g. 6 PM, 14:00, 2:30 PM, shaam 6 baje)
    hour_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', combined_time)
    if hour_match:
        hr = int(hour_match.group(1))
        minute = int(hour_match.group(2) or 0)
        meridiem = hour_match.group(3)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        start_time = f"{hr:02d}:{minute:02d}:00"
        end_hr = min(23, hr + 3)
        end_time = f"{end_hr:02d}:{minute:02d}:00"
        duration_hours = 3.0
    elif re.search(r'(\d{1,2})\s*baje\b', combined_time):
        baje_match = re.search(r'(\d{1,2})\s*baje\b', combined_time)
        hr = int(baje_match.group(1))
        if any(k in combined_time for k in ["shaam", "raat", "dopahar", "evening", "night"]):
            if hr < 12:
                hr += 12
        start_time = f"{hr:02d}:00:00"
        end_time = f"{min(23, hr + 3):02d}:00:00"
        duration_hours = 3.0
    else:
        # Part-of-day defaults
        if any(k in combined_time for k in ["evening", "shaam"]):
            start_time = "18:00:00"
            end_time = "21:00:00"
            duration_hours = 3.0
        elif any(k in combined_time for k in ["afternoon", "dopahar"]):
            start_time = "14:00:00"
            end_time = "17:00:00"
            duration_hours = 3.0
        elif any(k in combined_time for k in ["morning", "subah"]):
            start_time = "09:30:00"
            end_time = "13:00:00"
            duration_hours = 3.5
        elif any(k in combined_time for k in ["night", "raat"]):
            start_time = "19:00:00"
            end_time = "23:00:00"
            duration_hours = 4.0

    return target_date, start_time, end_time, duration_hours


def _extract_entities_deterministic(prompt: str) -> ExtractedEventEntities:
    """
    Rule-based deterministic extractor used as a fallback if LLM is unavailable.
    Accurately extracts relative dates, headcount numbers, categories and budget.
    """
    lower = prompt.lower()
    
    # Event type
    event_type = "general"
    if any(k in lower for k in ["hackathon", "coding", "ctf", "hack", "developer"]):
        event_type = "hackathon"
        event_name = "Campus AI Hackathon"
    elif any(k in lower for k in ["dance", "cultural", "fest", "music", "drama", "garba", "band"]):
        event_type = "cultural"
        event_name = "University Cultural Performance"
    elif any(k in lower for k in ["workshop", "hands-on", "bootcamp", "training", "lab"]):
        event_type = "workshop"
        event_name = "Technical Workshop Session"
    elif any(k in lower for k in ["seminar", "talk", "keynote", "lecture", "panel"]):
        event_type = "seminar"
        event_name = "Campus Academic Seminar"
    elif any(k in lower for k in ["sport", "cricket", "football", "badminton", "tournament"]):
        event_type = "sports"
        event_name = "Inter-Department Sports Meet"
    else:
        event_name = "Campus Innovation Event"

    # Headcount & Scale
    headcount = None
    scale = "unknown"
    num_match = re.search(r'(\d+)\s*(?:students?|participants?|attendees?|people|members?|heads?)', lower)
    if num_match:
        headcount = int(num_match.group(1))
    else:
        any_nums = re.findall(r'\b\d{2,4}\b', lower)
        # Avoid picking up 2026 as headcount
        filtered_nums = [int(n) for n in any_nums if int(n) < 1900 or int(n) > 2099]
        if filtered_nums:
            headcount = filtered_nums[0]

    # Qualitative scale inference if no exact number
    if headcount is None:
        if any(k in lower for k in ["chhota", "small", "intimate", "team", "core"]):
            headcount = 40
            scale = "small"
        elif any(k in lower for k in ["bada", "huge", "mega", "annual", "college", "all students"]):
            headcount = 250
            scale = "large"
    else:
        scale = "small" if headcount < 50 else ("medium" if headcount <= 150 else "large")

    # Date & Time Resolution
    date_str, start_t, end_t, dur = resolve_natural_datetime(date_phrase=lower, time_phrase=lower)

    # Budget extraction
    budget = None
    budget_match = re.search(r'(?:budget|cost|rs\.?|inr|under|within)\s*(?:of)?\s*[:=]?\s*(?:rs\.?|inr)?\s*(\d+(?:,\d+)*(?:\.\d+)?)', lower)
    if budget_match:
        raw_b = budget_match.group(1).replace(",", "")
        budget = float(raw_b)
    elif re.search(r'(\d+)\s*(?:k|hazar|thousand)\b', lower):
        k_match = re.search(r'(\d+)\s*(?:k|hazar|thousand)\b', lower)
        budget = float(k_match.group(1)) * 1000.0

    # Logistics items
    requested = []
    if any(k in lower for k in ["mic", "microphone"]):
        requested.append("Cordless Microphones")
    if any(k in lower for k in ["sound", "audio", "speaker"]):
        requested.append("High-Power Sound System")
    if any(k in lower for k in ["light", "led", "stage light"]):
        requested.append("Stage LED Lighting")
    if any(k in lower for k in ["power", "strip", "extension"]):
        requested.append("Extension Power Strips")
    if any(k in lower for k in ["food", "lunch", "snack", "catering"]):
        requested.append("Catering / Lunch Boxes")

    # Missing critical fields evaluation
    missing = []
    if headcount is None:
        missing.append("headcount")
    if not any(k in lower for k in ["friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday", "tomorrow", "kal", "parso", "nov", "dec", "202"]):
        missing.append("target_date")

    lang = "hi" if any(k in lower for k in ["kal", "shaam", "baje", "kardo", "hazar", "chhota", "bada"]) else "en"

    return ExtractedEventEntities(
        raw_prompt=prompt,
        event_name=event_name,
        event_type=event_type,
        estimated_headcount=headcount,
        scale_category=scale,
        target_date=date_str,
        date_original_phrase=date_str,
        start_time=start_t,
        end_time=end_t,
        duration_hours=dur,
        budget_limit=budget,
        requested_items=requested,
        missing_critical_fields=missing,
        is_ready_for_planning=len(missing) == 0,
        language_used=lang
    )


def extract_event_entities_llm(
    prompt: str,
    user_context: Optional[Dict[str, Any]] = None
) -> ExtractedEventEntities:
    """
    LLM-Powered Contextual Entity Extraction.
    Uses Gemini 3.5 Flash Lite with structured schema to understand free text,
    colloquial phrasing, and implicit requirements.
    Falls back gracefully to deterministic parsing on provider errors.
    """
    user_context = user_context or {}
    organiser_name = user_context.get("name", "Organiser")
    department = user_context.get("department", "Campus")

    system_prompt = (
        f"You are the AgenticLiner Natural Language Event Parser for Galgotias University.\n"
        f"Today's reference date is {CalendarDate.today().isoformat()}.\n"
        f"Current Organiser: {organiser_name} ({department}).\n\n"
        f"Your task is to analyze natural language event requests (which may be in English, Hindi, or Hinglish) "
        f"and extract structured JSON. Do NOT rely on rigid keywords; understand the core intent.\n\n"
        f"Output ONLY a raw JSON object with these exact keys:\n"
        f"- event_name: concise title (e.g. 'Campus Cultural Dance Gala')\n"
        f"- event_type: one of ['hackathon', 'cultural', 'workshop', 'seminar', 'sports', 'general']\n"
        f"- estimated_headcount: integer headcount or null if completely unspecified\n"
        f"- scale_category: 'small' (<50), 'medium' (50-150), 'large' (>150), or 'unknown'\n"
        f"- date_phrase: the raw date expression mentioned (e.g. 'this Friday', 'kal shaam', '28 Nov') or null\n"
        f"- time_phrase: the raw time expression mentioned (e.g. '6 PM', 'shaam ko', 'morning') or null\n"
        f"- duration_hours: float estimated duration in hours (e.g. 3.0, 5.0, 24.0)\n"
        f"- budget_limit: float budget if mentioned, or null\n"
        f"- requested_items: list of requested logistics strings (e.g. ['sound system', '4 mics', 'lights'])\n"
        f"- missing_critical_fields: list of missing essential fields from ['target_date', 'scale', 'event_type']\n"
        f"- language_used: 'en', 'hi', or 'hinglish'\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Parse this event brief:\n{prompt}"}
    ]

    try:
        config = get_provider_config()
    except ProviderError:
        config = None

    if config and config.get("api_key"):
        try:
            response = call_llm(messages=messages, tools=[], config=config)
            text = (response.get("text") or "").strip()
            
            # Clean possible markdown fences
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?", "", text)
                text = re.sub(r"```$", "", text).strip()

            parsed = json.loads(text)

            # Resolve datetime using our deterministic calendar helper
            date_phrase = parsed.get("date_phrase")
            time_phrase = parsed.get("time_phrase")
            res_date, start_t, end_t, dur = resolve_natural_datetime(
                date_phrase=date_phrase,
                time_phrase=time_phrase
            )

            headcount = parsed.get("estimated_headcount")
            scale = parsed.get("scale_category", "unknown")
            missing = parsed.get("missing_critical_fields") or []

            # Ensure missing checks are consistent
            if not date_phrase and "target_date" not in missing:
                missing.append("target_date")
            if headcount is None and "scale" not in missing:
                missing.append("scale")

            is_ready = len(missing) == 0

            return ExtractedEventEntities(
                raw_prompt=prompt,
                event_name=parsed.get("event_name", "Campus Event"),
                event_type=parsed.get("event_type", "general"),
                estimated_headcount=headcount,
                scale_category=scale,
                target_date=res_date,
                date_original_phrase=date_phrase or res_date,
                start_time=start_t,
                end_time=end_t,
                duration_hours=float(parsed.get("duration_hours") or dur),
                budget_limit=float(parsed["budget_limit"]) if parsed.get("budget_limit") is not None else None,
                requested_items=parsed.get("requested_items") or [],
                missing_critical_fields=missing,
                is_ready_for_planning=is_ready,
                language_used=parsed.get("language_used", "en")
            )

        except Exception as exc:
            logger.warning(f"LLM entity extraction failed or invalid JSON: {exc}. Falling back to deterministic parser.")

    # Graceful Fallback
    return _extract_entities_deterministic(prompt)


def assess_intake_completeness(
    entities: ExtractedEventEntities
) -> Tuple[bool, List[str], str]:
    """
    Evaluates whether the extracted entities have sufficient details to proceed
    to autonomous venue locking and resource requisition.
    
    Returns:
        (is_ready: bool, counter_questions: List[str], tts_speech_text: str)
    """
    missing = entities.missing_critical_fields
    questions = []

    if "target_date" in missing:
        questions.append("Aap ye event kis date aur time par organize karna chahte hain? (e.g. This Friday 6 PM ya 28 Nov)")
    if "scale" in missing or "headcount" in missing:
        questions.append("Lagbhag kitne participants/students aane ka anumaan hai taaki sahi venue allot kiya ja sake?")
    if "event_type" in missing:
        questions.append("Event ka main format kya hoga? (Hackathon, Workshop, Dance/Cultural, ya Seminar?)")

    if questions:
        # Construct natural clarifying speech
        if len(questions) == 1:
            tts_text = f"Zaroor! {questions[0]}"
        else:
            tts_text = f"Event plan karne ke liye mujhe do baatein batayein: pehla, {questions[0]} Aur doosra, {questions[1]}"
        return False, questions, tts_text

    # All critical fields available!
    headcount_desc = f"{entities.estimated_headcount} attendees" if entities.estimated_headcount else "your participants"
    tts_text = (
        f"Samajh gaya! {entities.event_name} plan kar raha hoon {headcount_desc} ke liye, "
        f"tareekh {entities.target_date} par."
    )
    return True, [], tts_text
