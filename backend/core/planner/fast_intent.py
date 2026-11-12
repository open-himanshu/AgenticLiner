"""
Fast-Path Micro-Intent Classifier for Pillar 5.
Inspired by OpenAI ChatGPT Realtime Voice Interaction:
Provides sub-50ms deterministic regex & phonetic classification for instant voice/text
turn-taking and confirmation handling without requiring high-latency LLM roundtrips.
"""

import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from backend.core.planner.natural_intake import resolve_natural_datetime


class FastIntentResult(BaseModel):
    intent: str = Field(..., description="Classified intent: 'confirm', 'cancel', 'delta', or 'unknown'")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")
    verbal_ack: str = Field(default="", description="Crisp, instant spoken acknowledgment (OpenAI-style)")
    delta_params: Dict[str, Any] = Field(default_factory=dict, description="Extracted delta parameters for in-place edits")


# 1. Affirmative Token Sets (English, Hindi, Hinglish, Campus Slang)
CONFIRM_PATTERNS = [
    # English
    r"\b(?:yes|yep|yeah|yup|sure|confirm|confirmed|book\s*it|lock\s*it|go\s*ahead|proceed|done|perfect|looks\s*good|all\s*good|fine|ok|okay)\b",
    # Hindi / Hinglish
    r"\b(?:haan?|ha|hnn|kar\s*do|kardo|kar\s*dijiye|lock\s*karo|lock\s*kar\s*do|theek\s*hai|thik\s*hai|sahi\s*hai|chalo|pakka|final\s*karo|final\s*hai|book\s*karo|book\s*kar\s*do|chalega)\b",
]

# 2. Negative / Abort Token Sets
CANCEL_PATTERNS = [
    # English
    r"\b(?:no|nope|cancel|stop|abort|don'?t\s*book|nevermind|wait|hold\s*on|hold\s*up)\b",
    # Hindi / Hinglish
    r"\b(?:nahi|na|mat\s*karna|mat\s*karo|ruko|ruk\s*jao|rok\s*do|cancel\s*karo|rehne\s*do|chhod\s*do|nahi\s*chahiye)\b",
]

# 3. Edit / Delta Trigger Words
DELTA_TRIGGERS = [
    "change", "badal", "modify", "update", "instead", "remove", "hatao", "add", "aur",
    "baje", "time", "date", "students", "headcount", "participants", "venue", "hall"
]


def classify_fast_intent(user_input: str) -> FastIntentResult:
    """
    Classifies user spoken or typed confirmation reply in <10ms.
    Returns FastIntentResult with immediate spoken acknowledgment.
    """
    clean = user_input.strip().lower()
    if not clean:
        return FastIntentResult(
            intent="unknown",
            confidence=0.0,
            verbal_ack="Maine suna nahi, kripya dobara boliye."
        )

    # 1. Check for DELTA / EDIT requests first if concrete parameters are being modified
    delta_extracted = _extract_delta_parameters(clean)
    if delta_extracted:
        return FastIntentResult(
            intent="delta",
            confidence=0.95,
            verbal_ack="Samajh gaya! Details update kar raha hoon.",
            delta_params=delta_extracted
        )

    # 2. Check for immediate explicit CANCEL / ABORT
    for pat in CANCEL_PATTERNS:
        if re.search(pat, clean):
            return FastIntentResult(
                intent="cancel",
                confidence=0.98,
                verbal_ack="Theek hai, plan cancel kar diya gaya hai. Koi booking nahi ki gayi.",
                delta_params={}
            )

    # 3. Check for general delta triggers (even without extracted parameters)
    has_delta_trigger = any(trig in clean for trig in DELTA_TRIGGERS)
    if has_delta_trigger and not any(re.search(pat, clean) for pat in CONFIRM_PATTERNS):
        return FastIntentResult(
            intent="delta",
            confidence=0.90,
            verbal_ack="Samajh gaya! Details update kar raha hoon.",
            delta_params={}
        )

    # 3. Check for immediate explicit CONFIRM
    for pat in CONFIRM_PATTERNS:
        if re.search(pat, clean):
            return FastIntentResult(
                intent="confirm",
                confidence=0.99,
                verbal_ack="Lock kar diya! Galgotias campus booking process shuru ho gayi hai.",
                delta_params={}
            )

    # 4. Fallback: Check if ambiguous or unclassified
    return FastIntentResult(
        intent="unknown",
        confidence=0.4,
        verbal_ack="Kya aap confirm karna chahte hain? Haan ya Cancel boliye.",
        delta_params={}
    )


def _extract_delta_parameters(clean: str) -> Dict[str, Any]:
    """
    Extracts delta parameter mutations without resetting active planning state.
    Supports:
    - Headcount changes (e.g. "make headcount 150", "200 students")
    - Time/Date changes (e.g. "change time to 3 pm", "friday 4 pm")
    - Item additions/removals (e.g. "remove projector", "add mic")
    """
    deltas: Dict[str, Any] = {}

    # 1. Delta Headcount
    # Priority 1: Explicit unit (e.g. "200 students", "make headcount 150")
    hc_match = re.search(
        r'(?:headcount|capacity|strength|batch)?\s*(?:to|as|=|is|make it)?\s*(\d{1,4})\s*(?:students?|participants?|attendees?|heads?|bach[eo]|log)\b',
        clean
    )
    if not hc_match:
        # Priority 2: Preceded by explicit keyword (e.g. "headcount 200", "make headcount 200")
        hc_match = re.search(
            r'(?:headcount|capacity|strength|batch)\s*(?:to|as|=|is|make it)?\s*(\d{1,4})\b',
            clean
        )

    if hc_match:
        v = int(hc_match.group(1))
        if 15 <= v <= 5000 and (v < 1900 or v > 2099):
            deltas["headcount"] = v
    else:
        # Priority 3: Standalone number >= 15 not followed by time/currency
        candidates = re.findall(
            r'\b(\d{1,4})\b(?!\s*(?:am|pm|baje|hours?|hrs?|o\'clock|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|k|inr|rs|%|th|st|nd|rd))',
            clean
        )
        for c in candidates:
            v = int(c)
            if 15 <= v <= 5000 and (v < 1900 or v > 2099):
                deltas["headcount"] = v
                break

    # 2. Delta Date / Time
    has_time = any(k in clean for k in ["am", "pm", "baje", "morning", "afternoon", "evening", "shaam"])
    has_date = any(k in clean for k in ["today", "tomorrow", "kal", "parso", "friday", "monday", "saturday", "sunday", "nov", "dec", "jan"])
    if has_time or has_date:
        d_str, s_time, e_time, dur = resolve_natural_datetime(date_phrase=clean, time_phrase=clean)
        if has_date and d_str:
            deltas["target_date"] = d_str
        if has_time and s_time:
            deltas["start_time"] = s_time
            deltas["end_time"] = e_time
            deltas["duration_hours"] = dur

    # 3. Delta Items (Removals & Additions)
    removals = []
    if "remove" in clean or "hatao" in clean or "hata do" in clean or "drop" in clean or "without" in clean:
        if "projector" in clean:
            removals.append("Ultra HD 4K Laser Projector")
        if "mic" in clean or "microphone" in clean:
            removals.append("Wireless Handheld Mic Set (Pair)")
            removals.append("Cordless Microphones")
        if "sound" in clean or "speaker" in clean:
            removals.append("JBL High-Power Sound & PA System")
            removals.append("High-Power Sound System")
        if "light" in clean or "led" in clean:
            removals.append("Stage LED Par Lights & Spotlights")
        if "power" in clean or "spike" in clean or "extension" in clean:
            removals.append("Heavy Duty Extension Spike Boards")
    if removals:
        deltas["remove_items"] = removals

    additions = []
    if "add" in clean or "chahiye" in clean or "with" in clean or "jodo" in clean:
        if "projector" in clean and "remove" not in clean:
            additions.append("Ultra HD 4K Laser Projector")
        if "snack" in clean or "refreshment" in clean or "food" in clean:
            additions.append("Standard Refreshment Snack Box")
        if "spike" in clean or "extension" in clean:
            additions.append("Heavy Duty Extension Spike Boards")
    if additions:
        deltas["add_items"] = additions

    return deltas
