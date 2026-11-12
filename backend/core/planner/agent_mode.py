"""
Autopilot Agent Mode: real tool-calling loop powered by LLM providers.

The model chooses which tools to call; results are fed back each turn.
Falls back to the existing fixed pipeline if the provider is unavailable.

Hard limits enforced in code (not just prompt):
  - MAX_STEPS = 8 turns
  - Budget checked before requisition
  - Recipient cap via Kavach
  - MAX_ASK_USER = 2 questions
  - Destructive prompts are blocked
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date as CalendarDate, timedelta
from typing import Any, Dict, List

from backend.core.planner.call_llm import call_llm, get_provider_config, ProviderError
from backend.core.planner.tools import (
    tool_find_free_venues,
    tool_check_equipment,
    tool_recommend_from_history,
    tool_requisition_campus_resources,
)

MAX_STEPS = 8
MAX_ASK_USER = 2
DEFAULT_BUDGET = 100000.0
RECIPIENT_CAP = 500

# Patterns that indicate destructive intent — blocked before the LLM even runs.
_DESTRUCTIVE_PATTERNS = [
    r"\bcancel\s+(all|every)",
    r"\bdelete\s+(all|every)",
    r"\bdrop\s+(all|every)",
    r"\bpurge\b",
    r"\bwipe\b",
    r"\btruncate\b",
    r"\bdestroy\b",
]

# Tool declarations (OpenAI-style schema) exposed to the LLM.
AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_free_venues",
            "description": "Find campus venues free for a given date/time range with at least min_capacity seats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_capacity": {"type": "integer", "description": "Minimum seat count."},
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                    "start_time": {"type": "string", "description": "HH:MM:SS format."},
                    "end_time": {"type": "string", "description": "HH:MM:SS format."},
                },
                "required": ["min_capacity", "date", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_equipment",
            "description": "List campus logistics inventory. Optionally filter by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Optional category filter."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_from_history",
            "description": "Get equipment recommendations based on past similar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string"},
                    "headcount": {"type": "integer"},
                },
                "required": ["event_type", "headcount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the organiser a single clarifying question. Max 2 questions total.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "requisition",
            "description": (
                "Book a campus venue and equipment. This action is guarded by Kavach safety. "
                "Pass the chosen room_id, attendance, budget, and items as JSON."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "string"},
                    "attendance": {"type": "integer"},
                    "items_json": {"type": "string", "description": "JSON array of {resource_id, quantity}."},
                    "date": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "budget": {"type": "number"},
                    "event_name": {"type": "string"},
                    "event_type": {"type": "string"},
                },
                "required": [
                    "room_id", "attendance", "items_json",
                    "date", "start_time", "end_time", "budget",
                    "event_name", "event_type",
                ],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    "find_free_venues": lambda args: tool_find_free_venues(
        min_capacity=int(args.get("min_capacity", 100)),
        date=args.get("date", "2026-12-01"),
        start_time=args.get("start_time", "09:00:00"),
        end_time=args.get("end_time", "17:00:00"),
    ),
    "check_equipment": lambda args: tool_check_equipment(
        category=args.get("category"),
    ),
    "recommend_from_history": lambda args: tool_recommend_from_history(
        event_type=args.get("event_type", "seminar"),
        headcount=int(args.get("headcount", 100)),
    ),
}


def _execute_requisition(args: Dict[str, Any], event_id: str, budget: float) -> Dict[str, Any]:
    """Execute a requisition through Kavach.  Budget is enforced in code."""
    req_budget = float(args.get("budget", budget))
    if req_budget > budget:
        return {
            "status": "rolled_back",
            "violation": {
                "rule": "budget_exceeded",
                "item": "event",
                "detail": f"Requested budget {req_budget} exceeds allowed budget {budget}.",
            },
        }
    return tool_requisition_campus_resources(
        event_id=event_id,
        room_id=args["room_id"],
        attendance=int(args["attendance"]),
        items_json=args.get("items_json", "[]"),
        date=args["date"],
        start_time=args["start_time"],
        end_time=args["end_time"],
        budget=req_budget,
        event_details={
            "name": args.get("event_name", "Agent-Planned Event"),
            "brief": "Planned by Autopilot Agent Mode",
            "event_type": args.get("event_type", "seminar"),
            "expected_participants": int(args["attendance"]),
            "organizer_department": "School of Computing Science",
        },
    )


def _is_destructive(prompt: str) -> bool:
    """Check if a user prompt matches known destructive patterns."""
    lower = prompt.lower()
    return any(re.search(pat, lower) for pat in _DESTRUCTIVE_PATTERNS)


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(budget: float, today: str, next_friday: str) -> str:
    return (
        f"You are AgenticLiner Autopilot, a campus event planning assistant. "
        f"Today is {today}. Next Friday is {next_friday}. "
        f"Budget limit: {budget}. Max recipients per notification: {RECIPIENT_CAP}. "
        f"You have these tools: find_free_venues, check_equipment, recommend_from_history, "
        f"ask_user (max {MAX_ASK_USER} questions), requisition (always goes through Kavach safety). "
        f"Use the tools to discover venues, check equipment, get recommendations, then requisition. "
        f"You must not invent data — only use tool results. "
        f"Never cancel, delete, or destroy existing bookings. "
        f"Finish with a concise summary of what was booked."
    )


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent_mode(
    prompt: str,
    date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    budget: Optional[float] = None,
    call_llm_fn=None,
) -> Dict[str, Any]:
    """
    Run the agent-mode autopilot.

    Parameters
    ----------
    prompt : str
        Natural-language event request.
    call_llm_fn : callable, optional
        Override for testing — must match call_llm(messages, tools, config) signature.

    Returns
    -------
    dict with keys: success, mode, provider, model, tokens_used, timeline, event_id, ...
    """
    if call_llm_fn is None:
        call_llm_fn = call_llm

    # Block destructive prompts before any LLM call.
    if _is_destructive(prompt):
        return {
            "success": False,
            "mode": "agent",
            "provider": "",
            "model": "",
            "tokens_used": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "timeline": [{
                "step": 0,
                "tool": "safety_check",
                "arguments": {"prompt": prompt},
                "status": "blocked",
                "summary": "Destructive prompt detected and blocked by safety filter.",
            }],
            "event_id": None,
            "error": "Destructive prompt blocked.",
        }

    # Resolve provider config.
    try:
        config = get_provider_config()
    except ProviderError:
        config = None

    today = CalendarDate.today().isoformat()
    next_friday_date = CalendarDate.today() + timedelta(days=(4 - CalendarDate.today().weekday()) % 7 or 7)
    next_friday = next_friday_date.isoformat()

    event_id = f"ev_auto_{uuid.uuid4().hex[:8]}"
    timeline: List[Dict[str, Any]] = []
    total_tokens: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    ask_user_count = 0

    effective_budget = float(budget) if budget is not None else float(DEFAULT_BUDGET)
    system_prompt = _build_system_prompt(effective_budget, today, next_friday)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    provider_name = config["provider"] if config else ""
    model_name = config["model"] if config else ""
    final_text = ""

    try:
        for step_num in range(1, MAX_STEPS + 1):
            response = call_llm_fn(messages, AGENT_TOOLS, config)
            usage = response.get("usage", {})
            for k in total_tokens:
                total_tokens[k] += int(usage.get(k, 0))

            provider_name = response.get("provider", provider_name)
            model_name = response.get("model", model_name)
            final_text = response.get("text", "")

            # Record assistant message.
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": final_text,
                "tool_calls": response.get("tool_calls", []),
            }
            messages.append(assistant_msg)

            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                # Model finished — no more tool calls.
                timeline.append({
                    "step": step_num,
                    "tool": "llm_response",
                    "arguments": {},
                    "status": "completed",
                    "summary": final_text[:200] if final_text else "Agent finished.",
                })
                break

            for call in tool_calls:
                name = call.get("name", "")
                arguments = call.get("arguments", {})

                # Enforce ask_user cap in code.
                if name == "ask_user":
                    if ask_user_count >= MAX_ASK_USER:
                        result = "Question limit reached. Proceed with sensible defaults."
                    else:
                        ask_user_count += 1
                        result = f"User was asked: {arguments.get('question', '')}"
                    tool_status = "completed"
                elif name == "requisition":
                    # Enforce budget in code before calling Kavach.
                    result = _execute_requisition(arguments, event_id, effective_budget)
                    tool_status = "committed" if result.get("status") == "committed" else "rolled_back"
                elif name in TOOL_DISPATCH:
                    try:
                        result = TOOL_DISPATCH[name](arguments)
                        tool_status = "completed"
                    except Exception as exc:
                        result = {"error": str(exc)}
                        tool_status = "error"
                else:
                    result = {"error": f"Unknown tool: {name}"}
                    tool_status = "error"

                timeline.append({
                    "step": step_num,
                    "tool": name,
                    "arguments": arguments,
                    "status": tool_status,
                    "summary": _summarize_result(name, result),
                    "details": result if not isinstance(result, str) else None,
                })

                # Feed result back as a tool message.
                tool_msg: Dict[str, Any] = {
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
                if call.get("id"):
                    tool_msg["tool_call_id"] = call["id"]
                messages.append(tool_msg)
        else:
            # Reached MAX_STEPS without finishing.
            timeline.append({
                "step": MAX_STEPS,
                "tool": "step_limit",
                "arguments": {},
                "status": "stopped",
                "summary": f"Agent reached the {MAX_STEPS}-step limit.",
            })

        # Determine success from timeline.
        committed = any(s.get("status") == "committed" for s in timeline)
        return {
            "success": committed,
            "mode": "agent",
            "provider": provider_name,
            "model": model_name,
            "tokens_used": total_tokens,
            "timeline": timeline,
            "event_id": event_id,
            "final_text": final_text,
        }

    except (ProviderError, Exception) as exc:
        # Provider unavailable — raise to trigger fallback in the caller.
        raise ProviderError(str(exc)) from exc


def _summarize_result(tool_name: str, result: Any) -> str:
    """Create a short human-readable summary of a tool result."""
    if isinstance(result, str):
        return result[:200]
    if isinstance(result, dict):
        if result.get("status") == "committed":
            return "Kavach safety checks passed. Booking committed."
        if result.get("status") == "rolled_back":
            v = result.get("violation", {})
            return f"Rolled back: {v.get('detail', 'safety violation')}."
        if "venues" in result:
            count = result.get("available_venues_count", len(result.get("venues", [])))
            return f"Found {count} available venue(s)."
        if "items" in result:
            return f"Equipment check: {result.get('count', len(result.get('items', [])))} items."
        if "recommendations" in result:
            recs = result.get("recommendations", [])
            return f"Got {len(recs)} recommendation(s) from history."
        if "error" in result:
            return f"Error: {result['error']}"
    return str(result)[:200]


# ---------------------------------------------------------------------------
# Public entry point with fallback
# ---------------------------------------------------------------------------

def run_autopilot_with_fallback(
    prompt: str,
    date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    budget: Optional[float] = None,
    call_llm_fn=None,
) -> Dict[str, Any]:
    """
    Try agent mode first.  On ProviderError, fall back to the fixed pipeline.
    The response mode identifies agent, provider-fallback, or provider-free execution.
    """
    if call_llm_fn is None and not os.getenv("PROVIDER", "").strip():
        from backend.core.planner.agent import AutopilotAgent

        result = AutopilotAgent().run_autopilot(
            prompt=prompt,
            date=date,
            start_time=start_time,
            end_time=end_time,
            budget=budget,
        )
        result.update({
            "mode": "fixed",
            "provider": "",
            "model": "",
            "tokens_used": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })
        return result

    try:
        return run_agent_mode(
            prompt=prompt,
            date=date,
            start_time=start_time,
            end_time=end_time,
            budget=budget,
            call_llm_fn=call_llm_fn,
        )
    except ProviderError as exc:
        # Fall back to the existing fixed pipeline.
        from backend.core.planner.agent import AutopilotAgent
        try:
            provider_config = get_provider_config()
            provider = provider_config["provider"]
            model = provider_config["model"]
        except ProviderError:
            provider = os.getenv("PROVIDER", "").strip()
            model = os.getenv(f"{provider.upper()}_MODEL", "").strip() if provider else ""

        agent = AutopilotAgent()
        result = agent.run_autopilot(
            prompt=prompt,
            date=date,
            start_time=start_time,
            end_time=end_time,
            budget=budget,
        )
        result.update({
            "mode": "fixed_fallback",
            "provider": provider,
            "model": model,
            "tokens_used": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "fallback_reason": str(exc),
        })
        return result
