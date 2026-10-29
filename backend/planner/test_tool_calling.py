"""Provider-switchable tool-calling demo using mock event data.

Ollama is the default provider and requires a running local Ollama server.
Gemini requires google-genai plus GEMINI_API_KEY and GEMINI_MODEL in .env.
Set PROVIDER to "ollama" or "gemini"; Ollama defaults to qwen3.5:9b.
"""
import argparse
from datetime import date as CalendarDate, timedelta
import json
import math
import os
import time
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TODAY = CalendarDate.today().isoformat()
MAX_STEPS = 8
MAX_ASK_USER_CALLS = 2
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
GEMINI_RETRY_DELAYS = (2, 5, 10)
GROQ_RETRY_DELAYS = (2, 5, 10)
PROVIDER = os.getenv("PROVIDER", "ollama").strip().lower()
ACTIVE_MODEL = ""
BUDGET = 20000
ORGANISER = "Himanshu"
AUTO_ANSWER = None
GEMINI_CLIENT = None
ASK_USER_CALLS = 0
BOOKINGS = []
USER_ANSWERS = []
STEP = {"n": 0}

VENUES = {
    "AUD-A": {"name": "Auditorium A", "capacity": 400, "per_hour": 1500},
    "SEM-B": {"name": "Seminar Hall B", "capacity": 120, "per_hour": 600},
    "STG-C": {"name": "Open Stage C", "capacity": 300, "per_hour": 800},
}
VENUE_BUSY = {
    ("AUD-A", "2026-10-30"): [(17, 20)],
}
STOCK = {
    "stage lights": (8, 400),
    "sound system": (2, 2500),
    "wireless mic": (6, 300),
    "projector": (3, 500),
    "first-aid kit": (3, 150),
    "volunteer": (30, 100),
    "green room": (2, 500),
    "backup power": (2, 700),
    "photographer": (2, 1500),
}
PLAYBOOK = {
    "dance": {
        "needs": [
            "stage lights", "sound system", "wireless mic", "green room",
            "first-aid kit", "volunteer", "backup power", "photographer",
        ],
        "questions": [
            "number of performers", "rehearsal time needed", "recording needed",
        ],
    },
    "hackathon": {
        "needs": ["projector", "volunteer", "first-aid kit", "backup power"],
        "questions": ["duration in hours", "number of teams", "overnight or not"],
    },
    "seminar": {
        "needs": ["projector", "wireless mic", "volunteer", "photographer"],
        "questions": ["number of speakers", "recording needed"],
    },
}
HISTORY = [
    {
        "organiser": "Himanshu", "type": "dance", "headcount": 100,
        "items": {
            "stage lights": 4, "sound system": 1, "wireless mic": 2,
            "green room": 1, "first-aid kit": 1, "volunteer": 8,
        },
    },
    {
        "organiser": "Asha", "type": "dance", "headcount": 180,
        "items": {
            "stage lights": 6, "sound system": 1, "wireless mic": 3,
            "green room": 1, "first-aid kit": 1, "volunteer": 14,
            "photographer": 1,
        },
    },
    {
        "organiser": "Ravi", "type": "dance", "headcount": 140,
        "items": {
            "stage lights": 4, "sound system": 1, "wireless mic": 2,
            "first-aid kit": 1, "volunteer": 10, "backup power": 1,
        },
    },
    {
        "organiser": "Meena", "type": "hackathon", "headcount": 80,
        "items": {"projector": 1, "volunteer": 6, "first-aid kit": 1},
    },
    {
        "organiser": "Kabir", "type": "seminar", "headcount": 90,
        "items": {"projector": 1, "wireless mic": 2, "volunteer": 4},
    },
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the organiser for missing information or booking confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_event_checklist",
            "description": "Return the usual needs and questions for an event type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["dance", "hackathon", "seminar"],
                    },
                },
                "required": ["event_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_from_history",
            "description": "Recommend items from similar past events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["dance", "hackathon", "seminar"],
                    },
                    "headcount": {"type": "integer"},
                    "organiser": {"type": "string"},
                },
                "required": ["event_type", "headcount", "organiser"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_free_venues",
            "description": "Find venues free for the full time window and large enough.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "start_hour": {"type": "integer"},
                    "end_hour": {"type": "integer"},
                    "min_capacity": {"type": "integer"},
                },
                "required": ["date", "start_hour", "end_hour", "min_capacity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_equipment",
            "description": "Check equipment stock and unit prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["item_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_items",
            "description": "Book the selected venue and equipment after confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "venue_id": {"type": "string"},
                    "date": {"type": "string"},
                    "start_hour": {"type": "integer"},
                    "end_hour": {"type": "integer"},
                    "equipment": {
                        "type": "object",
                        "properties": {
                            name: {"type": "integer", "minimum": 0}
                            for name in STOCK
                        },
                        "additionalProperties": {"type": "integer", "minimum": 0},
                    },
                    "headcount": {"type": "integer"},
                },
                "required": [
                    "venue_id", "date", "start_hour", "end_hour",
                    "equipment", "headcount",
                ],
            },
        },
    },
]


def ask_user(question: str) -> str:
    # Ask the organiser a short question and return their answer.
    print(f"\n  AGENT ASKS: {question}")
    if AUTO_ANSWER is not None:
        print(f"  AUTO ANSWER: {AUTO_ANSWER}")
        return AUTO_ANSWER
    try:
        return input("  YOUR ANSWER: ").strip() or "no answer"
    except EOFError:
        return "no answer (use a sensible default and state it as an assumption)"


def get_event_checklist(event_type: str) -> dict:
    # Return the needs and useful questions for an event type.
    return PLAYBOOK.get(
        normalize_event_type(event_type),
        {"needs": [], "questions": [], "note": "unknown type"},
    )


def normalize_event_type(event_type: str) -> str:
    # Normalize a model-provided event type to an allowed canonical value.
    normalized = str(event_type or "").strip().lower()
    for allowed_type in PLAYBOOK:
        if normalized == allowed_type or allowed_type in normalized:
            return allowed_type
    return normalized


def recommend_from_history(event_type: str, headcount: int, organiser: str) -> dict:
    # Recommend equipment based on the organiser's and similar past events.
    event_type = normalize_event_type(event_type)
    same_type = [event for event in HISTORY if event["type"] == event_type]
    result = {"same_as_last_time": None, "similar_events": []}
    mine = [
        event for event in same_type
        if event["organiser"].lower() == organiser.lower()
    ]
    if mine:
        last = mine[-1]
        scale = headcount / last["headcount"]
        result["same_as_last_time"] = {
            "past_headcount": last["headcount"],
            "items": {
                name: (
                    quantity
                    if name in (
                        "sound system", "green room", "first-aid kit",
                        "photographer", "backup power",
                    )
                    else max(1, math.ceil(quantity * scale))
                )
                for name, quantity in last["items"].items()
            },
        }
    others = [
        event for event in same_type
        if event["organiser"].lower() != organiser.lower()
    ]
    if headcount > 0:
        others.sort(
            key=lambda event: abs(math.log(headcount / event["headcount"]))
        )
    top = others[:5]
    counts = {}
    for event in top:
        for item, quantity in event["items"].items():
            counts.setdefault(item, []).append(
                quantity * headcount / event["headcount"]
            )
    for item, quantities in sorted(
        counts.items(), key=lambda entry: -len(entry[1])
    ):
        result["similar_events"].append({
            "item": item,
            "used_in": f"{len(quantities)} of {len(top)} similar events",
            "suggested_qty": max(1, round(sum(quantities) / len(quantities))),
        })
    result["note"] = "Synthetic history, for demo only."
    return result


def find_free_venues(
    date: str, start_hour: int, end_hour: int, min_capacity: int
) -> dict:
    # List venues that are free for the whole time window and large enough.
    free, busy = [], []
    for venue_id, venue in VENUES.items():
        if venue["capacity"] < min_capacity:
            continue
        clashes = any(
            not (end_hour <= start or start_hour >= end)
            for start, end in VENUE_BUSY.get((venue_id, date), [])
        )
        clashes = clashes or any(
            booking["venue_id"] == venue_id
            and booking["date"] == date
            and not (
                end_hour <= booking["start_hour"]
                or start_hour >= booking["end_hour"]
            )
            for booking in BOOKINGS
        )
        entry = {
            "venue_id": venue_id,
            "name": venue["name"],
            "capacity": venue["capacity"],
            "price_per_hour": venue["per_hour"],
        }
        (busy if clashes else free).append(entry)
    return {"free": free, "busy_in_that_time": busy}


def check_equipment(item_names: list[str]) -> dict:
    # Return stock and unit prices for the requested equipment.
    return {
        name: (
            {"in_stock": STOCK[name][0], "unit_price": STOCK[name][1]}
            if name in STOCK
            else "unknown item"
        )
        for name in item_names
    }


def book_items(
    venue_id: str,
    date: str,
    start_hour: int,
    end_hour: int,
    equipment: dict[str, int],
    headcount: int,
) -> dict:
    # Validate a booking against capacity, conflicts, stock, and the budget.
    violations = []
    valid_time = 0 <= start_hour < end_hour <= 24
    if not valid_time:
        violations.append("start_hour/end_hour must be a valid increasing time window")
    try:
        booking_date = CalendarDate.fromisoformat(date)
        if booking_date <= CalendarDate.today():
            violations.append("booking date must be after today")
    except ValueError:
        violations.append("date must be a valid YYYY-MM-DD date")
    if venue_id not in VENUES:
        violations.append(f"unknown venue: {venue_id}")
    if headcount <= 0:
        violations.append("headcount must be positive")
    elif venue_id in VENUES and headcount > VENUES[venue_id]["capacity"]:
        violations.append(
            f"headcount {headcount} exceeds venue capacity "
            f"{VENUES[venue_id]['capacity']}"
        )

    if valid_time and venue_id in VENUES:
        reserved = list(VENUE_BUSY.get((venue_id, date), []))
        reserved.extend(
            (booking["start_hour"], booking["end_hour"])
            for booking in BOOKINGS
            if booking["venue_id"] == venue_id and booking["date"] == date
        )
        if any(
            not (end_hour <= start or start_hour >= end)
            for start, end in reserved
        ):
            violations.append("venue overlaps an existing booking")

    total_cost = 0
    if valid_time and venue_id in VENUES:
        total_cost += VENUES[venue_id]["per_hour"] * (end_hour - start_hour)
    for name, quantity in equipment.items():
        if name not in STOCK:
            violations.append(f"unknown equipment: {name}")
        elif quantity <= 0:
            violations.append(f"quantity for {name} must be greater than zero")
        elif quantity > STOCK[name][0]:
            violations.append(
                f"requested {quantity} {name}, but only {STOCK[name][0]} in stock"
            )
        else:
            total_cost += quantity * STOCK[name][1]

    if total_cost > BUDGET:
        violations.append(f"total cost {total_cost} exceeds budget {BUDGET}")
    if violations:
        return {"status": "rejected", "violations": violations}

    for name, quantity in equipment.items():
        stock, price = STOCK[name]
        STOCK[name] = (stock - quantity, price)
    booking = {
        "venue_id": venue_id,
        "date": date,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "equipment": dict(equipment),
        "headcount": headcount,
        "total_cost": total_cost,
    }
    BOOKINGS.append(booking)
    return {"status": "committed", "total_cost": total_cost}


TOOL_FUNCTIONS = {
    "ask_user": ask_user,
    "get_event_checklist": get_event_checklist,
    "recommend_from_history": recommend_from_history,
    "find_free_venues": find_free_venues,
    "check_equipment": check_equipment,
    "book_items": book_items,
}


def build_system_prompt(organiser: str, budget: int) -> str:
    # Build the agent instructions with the request's organiser and budget.
    return f"""You are a college event-booking agent. Today is {TODAY}.
Friday means the next upcoming Friday after today.
The organiser is {organiser}; the budget is {budget}.
Decide venue, duration and equipment yourself using the tools. Ask the user only for facts that cannot be inferred, such as date or time.
Today's date is {TODAY}.
1. Use get_event_checklist and recommend_from_history. Ask at most 2 short questions and do not repeat information already given.
2. Check venues and equipment before proposing a plan. Offer a concrete alternative if the requested time or venue is unavailable.
3. Show the plan and total cost, then ask for confirmation with ask_user. Only book after the organiser says yes.
4. Call book_items with venue_id, date, start_hour, end_hour, equipment (an item-to-quantity object), and headcount.
5. Treat rejected bookings as a reason to re-plan. The booking code enforces the budget; never claim an uncommitted booking succeeded.
6. Finish with a concise report describing bookings, assumptions, and anything still undecided.
Reply in the organiser's language. All event data is synthetic."""


def format_short(value: object) -> str:
    # Serialize a tool result compactly for the step timeline.
    short = json.dumps(value, ensure_ascii=False, default=str)
    return short if len(short) <= 220 else short[:217] + "..."


def invoke_tool(name: str, arguments: dict) -> object:
    # Run one validated tool request and print its numbered result.
    global ASK_USER_CALLS
    STEP["n"] += 1
    was_asked = False
    if name not in TOOL_FUNCTIONS:
        result = {"error": f"Unknown tool: {name}"}
    elif not isinstance(arguments, dict):
        result = {"error": "Tool arguments must be an object"}
    elif name == "ask_user" and ASK_USER_CALLS >= MAX_ASK_USER_CALLS:
        result = (
            "Do not ask again. Proceed with sensible assumptions and list them "
            "in the final report."
        )
    else:
        if name == "ask_user":
            ASK_USER_CALLS += 1
            was_asked = True
        result = TOOL_FUNCTIONS[name](**arguments)
    print(
        f"[step {STEP['n']}] {name}("
        f"{json.dumps(arguments, ensure_ascii=False, default=str)}) -> "
        f"{format_short(result)}"
    )
    if was_asked and isinstance(result, str):
        USER_ANSWERS.append(result)
    return result


def ollama_messages(messages: list[dict]) -> list[dict]:
    # Convert the shared conversation into Ollama's chat message format.
    converted = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            converted.append({
                "role": "tool",
                "tool_name": message["name"],
                "content": message["content"],
            })
        elif role == "assistant":
            assistant_message = {
                "role": "assistant",
                "content": message.get("content", ""),
            }
            if message.get("tool_calls"):
                assistant_message["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in message["tool_calls"]
                ]
            converted.append(assistant_message)
        else:
            converted.append({
                "role": role,
                "content": message.get("content", ""),
            })
    return converted


def call_ollama(messages: list[dict], tools: list[dict]) -> dict:
    # Request one assistant turn from Ollama's local chat API.
    request_data = json.dumps({
        "model": ACTIVE_MODEL,
        "messages": ollama_messages(messages),
        "tools": tools,
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=request_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama returned HTTP {error.code}: {details}") from None
    except urllib.error.URLError:
        raise RuntimeError(
            "Ollama is not running or is unreachable at http://localhost:11434. "
            "Start Ollama and run this command again."
        ) from None

    assistant_message = payload.get("message")
    if not isinstance(assistant_message, dict):
        raise RuntimeError(f"Ollama returned an unexpected response: {payload}")
    calls = []
    for tool_call in assistant_message.get("tool_calls") or []:
        function_call = tool_call.get("function", {})
        calls.append({
            "name": function_call.get("name"),
            "arguments": function_call.get("arguments", {}),
        })
    return {
        "text": assistant_message.get("content") or "",
        "tool_calls": calls,
        "native_content": None,
    }


def gemini_contents(messages: list[dict], types) -> list:
    # Convert shared messages into Gemini model and function-response contents.
    contents = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message["role"]
        if role == "system":
            index += 1
            continue
        if role == "tool":
            parts = []
            while index < len(messages) and messages[index]["role"] == "tool":
                tool_message = messages[index]
                parts.append(types.Part.from_function_response(
                    name=tool_message["name"],
                    response=json.loads(tool_message["content"]),
                ))
                index += 1
            contents.append(types.Content(role="user", parts=parts))
            continue
        if role == "assistant" and message.get("native_content") is not None:
            contents.append(message["native_content"])
            index += 1
            continue
        if role == "assistant":
            parts = []
            if message.get("content"):
                parts.append(types.Part(text=message["content"]))
            for call in message.get("tool_calls", []):
                parts.append(types.Part(function_call=types.FunctionCall(
                    name=call["name"],
                    args=call["arguments"],
                )))
            contents.append(types.Content(role="model", parts=parts))
        else:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=message.get("content", ""))],
            ))
        index += 1
    return contents


def call_gemini(messages: list[dict], tools: list[dict]) -> dict:
    # Request one Gemini turn with function execution disabled in the SDK.
    global GEMINI_CLIENT
    from google import genai
    from google.genai import errors, types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env.")
    if not ACTIVE_MODEL:
        raise RuntimeError("GEMINI_MODEL is missing from .env.")
    if GEMINI_CLIENT is None:
        GEMINI_CLIENT = genai.Client(api_key=api_key)

    declarations = [
        types.FunctionDeclaration(
            name=tool["function"]["name"],
            description=tool["function"]["description"],
            parameters_json_schema=tool["function"]["parameters"],
        )
        for tool in tools
    ]
    system_instruction = next(
        (message["content"] for message in messages if message["role"] == "system"),
        "",
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
        temperature=0,
    )
    contents = gemini_contents(messages, types)

    for attempt in range(len(GEMINI_RETRY_DELAYS) + 1):
        try:
            response = GEMINI_CLIENT.models.generate_content(
                model=ACTIVE_MODEL,
                contents=contents,
                config=config,
            )
            break
        except errors.APIError as error:
            code = getattr(error, "code", None)
            status_code = getattr(error, "status_code", None)
            status = str(getattr(error, "status", "")).upper()
            temporary = (
                code in (429, 503)
                or status_code in (429, 503)
                or "UNAVAILABLE" in status
                or "RESOURCE_EXHAUSTED" in status
            )
            if not temporary:
                raise RuntimeError(
                    f"Gemini request failed (HTTP {status_code or code}): "
                    f"{getattr(error, 'message', 'API error')}"
                ) from None
            if attempt == len(GEMINI_RETRY_DELAYS):
                raise RuntimeError(
                    "Gemini unavailable, try PROVIDER=ollama"
                ) from None
            delay = GEMINI_RETRY_DELAYS[attempt]
            print(
                f"Gemini temporarily unavailable; retry "
                f"{attempt + 1}/3 in {delay}s."
            )
            time.sleep(delay)

    content = None
    if response.candidates:
        content = response.candidates[0].content
    text_parts = []
    calls = []
    if content is not None:
        for part in content.parts or []:
            if part.text:
                text_parts.append(part.text)
            if part.function_call is not None:
                function_call = part.function_call
                calls.append({
                    "name": function_call.name,
                    "arguments": dict(function_call.args or {}),
                })
    return {
        "text": "\n".join(text_parts),
        "tool_calls": calls,
        "native_content": content,
    }


def groq_messages(messages: list[dict]) -> list[dict]:
    # Convert the shared conversation to Groq's OpenAI-compatible message shape.
    converted = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            converted.append({
                "role": "tool",
                "tool_call_id": message["tool_call_id"],
                "name": message["name"],
                "content": message["content"],
            })
        elif role == "assistant":
            assistant_message = {
                "role": "assistant",
                "content": message.get("content") or None,
            }
            if message.get("tool_calls"):
                assistant_message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for call in message["tool_calls"]
                ]
            converted.append(assistant_message)
        else:
            converted.append({
                "role": role,
                "content": message.get("content", ""),
            })
    return converted


def call_groq(messages: list[dict], tools: list[dict]) -> dict:
    # Request a single tool-capable completion from Groq's OpenAI-compatible API.
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from .env.")
    if not ACTIVE_MODEL:
        raise RuntimeError("GROQ_MODEL is missing from .env.")

    request_data = json.dumps({
        "model": ACTIVE_MODEL,
        "messages": groq_messages(messages),
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=request_data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(len(GROQ_RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            status_code = error.code
            error.read()
            error.close()
            if status_code not in (429, 503):
                raise RuntimeError(
                    f"Groq request failed (HTTP {status_code})."
                ) from None
            if attempt == len(GROQ_RETRY_DELAYS):
                raise RuntimeError(
                    f"Groq unavailable (HTTP {status_code}) after 3 retries."
                ) from None
            delay = GROQ_RETRY_DELAYS[attempt]
            print(
                f"Groq temporarily unavailable (HTTP {status_code}); "
                f"retry {attempt + 1}/3 in {delay}s."
            )
            time.sleep(delay)
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Could not connect to Groq: {error.reason}"
            ) from None

    choices = payload.get("choices")
    if not choices or not isinstance(choices[0].get("message"), dict):
        raise RuntimeError("Groq returned an unexpected chat completion response.")
    assistant_message = choices[0]["message"]
    calls = []
    for tool_call in assistant_message.get("tool_calls") or []:
        function_call = tool_call.get("function", {})
        arguments = function_call.get("arguments", "{}")
        try:
            parsed_arguments = (
                json.loads(arguments) if isinstance(arguments, str) else arguments
            )
        except json.JSONDecodeError:
            parsed_arguments = {}
        calls.append({
            "id": tool_call.get("id"),
            "name": function_call.get("name"),
            "arguments": parsed_arguments,
        })
    return {
        "text": assistant_message.get("content") or "",
        "tool_calls": calls,
        "native_content": None,
    }


def call_llm(messages: list[dict], tools: list[dict]) -> dict:
    # Dispatch one model turn to the selected provider.
    print("waiting for model...")
    if PROVIDER == "gemini":
        return call_gemini(messages, tools)
    if PROVIDER == "ollama":
        return call_ollama(messages, tools)
    if PROVIDER == "groq":
        return call_groq(messages, tools)
    raise RuntimeError('PROVIDER must be "gemini", "ollama", or "groq".')


def run_agent(prompt: str, organiser: str) -> str:
    # Run the tool loop until it books, answers, or reaches its step limit.
    global ASK_USER_CALLS
    ASK_USER_CALLS = 0
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(organiser, BUDGET),
        },
        {"role": "user", "content": prompt},
    ]
    final_text = ""
    for _ in range(MAX_STEPS):
        response = call_llm(messages, TOOLS)
        final_text = response["text"] or ""
        assistant_message = {
            "role": "assistant",
            "content": final_text,
            "tool_calls": response["tool_calls"],
        }
        if response.get("native_content") is not None:
            assistant_message["native_content"] = response["native_content"]
        messages.append(assistant_message)
        if not response["tool_calls"]:
            break
        for call in response["tool_calls"]:
            name = call.get("name")
            arguments = call.get("arguments", {})
            ask_limit_reached = (
                name == "ask_user" and ASK_USER_CALLS >= MAX_ASK_USER_CALLS
            )
            result = invoke_tool(name, arguments)
            tool_message = {
                "role": "tool",
                "name": name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            }
            if call.get("id"):
                tool_message["tool_call_id"] = call["id"]
            messages.append(tool_message)
            if ask_limit_reached:
                messages.append({
                    "role": "user",
                    "content": (
                        "Do not ask again. Proceed with sensible assumptions "
                        "and list them in the final report."
                    ),
                })
            if (
                name == "book_items"
                and isinstance(result, dict)
                and result.get("status") == "committed"
            ):
                return final_text
    return final_text


def fallback_report() -> str:
    # Build a non-empty report from bookings, costs, budget, and user answers.
    lines = []
    if BOOKINGS:
        lines.append("Bookings:")
        for booking in BOOKINGS:
            items = ", ".join(
                f"{name} x{quantity}"
                for name, quantity in booking["equipment"].items()
            ) or "no equipment"
            lines.append(
                f"- {booking['venue_id']} on {booking['date']} "
                f"{booking['start_hour']}:00-{booking['end_hour']}:00; "
                f"{booking['headcount']} people; {items}; "
                f"cost {booking['total_cost']}."
            )
    else:
        lines.append("No booking was committed.")
    total = sum(booking["total_cost"] for booking in BOOKINGS)
    lines.append(f"Total cost: {total} vs budget {BUDGET}.")
    if USER_ANSWERS:
        lines.append("User answers: " + "; ".join(USER_ANSWERS))
    else:
        lines.append("User answers: none recorded.")
    return "\n".join(lines)


def selftest() -> None:
    # Exercise the mock event tools and all required booking rejections.
    global ASK_USER_CALLS, AUTO_ANSWER, BUDGET
    original_budget = BUDGET
    original_stock = STOCK.copy()
    original_auto_answer = AUTO_ANSWER
    future_date = (CalendarDate.today() + timedelta(days=1)).isoformat()
    BOOKINGS.clear()
    USER_ANSWERS.clear()
    STEP["n"] = 0
    ASK_USER_CALLS = 0
    AUTO_ANSWER = "self-test answer"
    print("SELF-TEST (no provider calls).\n")
    try:
        checklist = invoke_tool("get_event_checklist", {"event_type": "dance"})
        assert checklist["needs"]
        assert get_event_checklist("  DANCE performance ")["needs"]
        assert normalize_event_type(" Hackathon event ") == "hackathon"
        recommendation = invoke_tool(
            "recommend_from_history",
            {"event_type": "dance", "headcount": 150, "organiser": ORGANISER},
        )
        assert recommendation["same_as_last_time"] is not None
        invoke_tool(
            "find_free_venues",
            {
                "date": future_date,
                "start_hour": 18,
                "end_hour": 21,
                "min_capacity": 150,
            },
        )
        invoke_tool(
            "check_equipment",
            {"item_names": ["stage lights", "unicorn"]},
        )

        valid = invoke_tool(
            "book_items",
            {
                "venue_id": "STG-C",
                "date": future_date,
                "start_hour": 18,
                "end_hour": 20,
                "equipment": {"stage lights": 1},
                "headcount": 150,
            },
        )
        assert valid == {"status": "committed", "total_cost": 2000}
        print("PASS: valid booking committed")

        overlap = invoke_tool(
            "book_items",
            {
                "venue_id": "STG-C",
                "date": future_date,
                "start_hour": 19,
                "end_hour": 21,
                "equipment": {},
                "headcount": 150,
            },
        )
        assert overlap["status"] == "rejected"
        assert any("overlaps" in item for item in overlap["violations"])
        print("PASS: overlapping booking rejected")

        BUDGET = 100
        over_budget = invoke_tool(
            "book_items",
            {
                "venue_id": "STG-C",
                "date": (CalendarDate.today() + timedelta(days=2)).isoformat(),
                "start_hour": 18,
                "end_hour": 20,
                "equipment": {},
                "headcount": 150,
            },
        )
        assert over_budget["status"] == "rejected"
        assert any("exceeds budget" in item for item in over_budget["violations"])
        print("PASS: over-budget booking rejected")

        BUDGET = original_budget
        over_capacity = invoke_tool(
            "book_items",
            {
                "venue_id": "AUD-A",
                "date": (CalendarDate.today() + timedelta(days=3)).isoformat(),
                "start_hour": 18,
                "end_hour": 20,
                "equipment": {},
                "headcount": 401,
            },
        )
        assert over_capacity["status"] == "rejected"
        assert any("capacity" in item for item in over_capacity["violations"])
        print("PASS: over-capacity booking rejected")

        over_stock = invoke_tool(
            "book_items",
            {
                "venue_id": "STG-C",
                "date": (CalendarDate.today() + timedelta(days=4)).isoformat(),
                "start_hour": 18,
                "end_hour": 20,
                "equipment": {"stage lights": STOCK["stage lights"][0] + 1},
                "headcount": 150,
            },
        )
        assert over_stock["status"] == "rejected"
        assert any("only" in item and "in stock" in item for item in over_stock["violations"])
        print("PASS: equipment quantity above stock rejected")

        for invalid_quantity in (0, -1):
            invalid_equipment_quantity = invoke_tool(
                "book_items",
                {
                    "venue_id": "STG-C",
                    "date": (CalendarDate.today() + timedelta(days=5)).isoformat(),
                    "start_hour": 18,
                    "end_hour": 20,
                    "equipment": {"stage lights": invalid_quantity},
                    "headcount": 150,
                },
            )
            assert invalid_equipment_quantity["status"] == "rejected"
            assert any(
                "must be greater than zero" in item
                for item in invalid_equipment_quantity["violations"]
            )
        print("PASS: zero and negative equipment quantities rejected")

        for invalid_start, invalid_end in ((20, 18), (18, 18)):
            invalid_time = invoke_tool(
                "book_items",
                {
                    "venue_id": "STG-C",
                    "date": (CalendarDate.today() + timedelta(days=6)).isoformat(),
                    "start_hour": invalid_start,
                    "end_hour": invalid_end,
                    "equipment": {},
                    "headcount": 150,
                },
            )
            assert invalid_time["status"] == "rejected"
            assert any(
                "valid increasing time window" in item
                for item in invalid_time["violations"]
            )
        print("PASS: start_hour >= end_hour rejected")

        unknown_equipment = invoke_tool(
            "book_items",
            {
                "venue_id": "STG-C",
                "date": (CalendarDate.today() + timedelta(days=7)).isoformat(),
                "start_hour": 18,
                "end_hour": 20,
                "equipment": {"unicorn": 1},
                "headcount": 150,
            },
        )
        assert unknown_equipment["status"] == "rejected"
        assert any(
            "unknown equipment: unicorn" in item
            for item in unknown_equipment["violations"]
        )
        print("PASS: unknown equipment rejected with clear message")

        for invalid_date in (
            CalendarDate.today().isoformat(),
            (CalendarDate.today() - timedelta(days=1)).isoformat(),
        ):
            past_booking = invoke_tool(
                "book_items",
                {
                    "venue_id": "STG-C",
                    "date": invalid_date,
                    "start_hour": 18,
                    "end_hour": 20,
                    "equipment": {},
                    "headcount": 150,
                },
            )
            assert past_booking["status"] == "rejected"
            assert any("must be after today" in item for item in past_booking["violations"])
        print("PASS: today and past booking dates rejected")

        invoke_tool("ask_user", {"question": "First test question?"})
        invoke_tool("ask_user", {"question": "Second test question?"})
        denied_question = invoke_tool(
            "ask_user", {"question": "This must not be asked."}
        )
        assert "Do not ask again." in denied_question
        assert ASK_USER_CALLS == MAX_ASK_USER_CALLS
        assert USER_ANSWERS == ["self-test answer", "self-test answer"]
        print("PASS: ask_user limited to two calls")
    finally:
        BUDGET = original_budget
        AUTO_ANSWER = original_auto_answer
        ASK_USER_CALLS = 0
        STOCK.clear()
        STOCK.update(original_stock)
        BOOKINGS.clear()


def main() -> int:
    # Parse options, run the self-test or selected provider, and print a report.
    global ACTIVE_MODEL, ASK_USER_CALLS, AUTO_ANSWER, BUDGET, ORGANISER, PROVIDER
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--budget", type=int, default=20000)
    parser.add_argument("--organiser", default="Himanshu")
    parser.add_argument("--auto-answer", help="Answer every ask_user tool call with this text.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0

    PROVIDER = os.getenv("PROVIDER", "ollama").strip().lower()
    if PROVIDER not in ("gemini", "ollama", "groq"):
        print('PROVIDER must be "gemini", "ollama", or "groq".')
        return 2
    BUDGET, ORGANISER = args.budget, args.organiser
    AUTO_ANSWER = args.auto_answer
    BOOKINGS.clear()
    USER_ANSWERS.clear()
    STEP["n"] = 0
    ASK_USER_CALLS = 0
    if PROVIDER == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            print("GEMINI_API_KEY is missing from .env.")
            return 2
        ACTIVE_MODEL = os.getenv("GEMINI_MODEL", "").strip()
        if not ACTIVE_MODEL:
            print("GEMINI_MODEL is missing from .env.")
            return 2
    elif PROVIDER == "groq":
        if not os.getenv("GROQ_API_KEY"):
            print("GROQ_API_KEY is missing from .env.")
            return 2
        ACTIVE_MODEL = os.getenv("GROQ_MODEL", "").strip()
        if not ACTIVE_MODEL:
            print("GROQ_MODEL is missing from .env.")
            return 2
    else:
        ACTIVE_MODEL = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
        if not ACTIVE_MODEL:
            ACTIVE_MODEL = DEFAULT_OLLAMA_MODEL

    prompt = " ".join(args.prompt) or (
        "Dance performance, 150 students, Friday evening. Book everything."
    )
    print(
        f"Provider: {PROVIDER}\nModel: {ACTIVE_MODEL}\n"
        f"Request: {prompt}\nBudget: {BUDGET}\n"
    )
    try:
        report = run_agent(prompt, ORGANISER)
    except RuntimeError as error:
        print(str(error))
        return 1
    print("\n=== FINAL REPORT ===")
    print(report.strip() or fallback_report())
    print("\nBookings in memory:", json.dumps(BOOKINGS, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
