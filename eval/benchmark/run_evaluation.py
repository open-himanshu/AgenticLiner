"""Run the prompt benchmark against isolated SQLite databases and live pipelines."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import closing, contextmanager, redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Generator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.database.connection import get_connection
from backend.core.planner.agent_mode import run_autopilot_with_fallback
from backend.modules.module1_coplan.brief_parser import adaptive_intake
from eval.benchmark.independent_checker import IndependentDBChecker

PROMPTS_PATH = ROOT / "eval" / "prompts" / "test_prompts.json"
RESULTS_PATH = ROOT / "eval" / "benchmark" / "results.json"
APP_DATABASE_PATH = ROOT / "agenticliner.db"
SCHEMA_PATH = ROOT / "backend" / "core" / "database" / "schema.sql"
BASELINE_SCHEMA_PATH = ROOT / "eval" / "benchmark" / "schema_baseline.sql"
SETUP_NAMES = {
    "setup_a": "Setup A (Direct planned actions)",
    "setup_b": "Setup B (SQLite constraints only)",
    "setup_c": "Setup C (Kavach agent pipeline)",
}
ALLOWED_STOPPED_BY = (
    "intake",
    "destructive_filter",
    "kavach",
    "db_constraint",
    "none",
)
ENTRY_MODES = ("shared", "raw")
DESTRUCTIVE_TABLES = frozenset(
    {
        "attendance",
        "bookings",
        "events",
        "registrations",
        "rooms",
        "sessions",
    }
)


@contextmanager
def scenario_database_path(path: Path) -> Generator[None, None, None]:
    previous_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(path)
    try:
        yield
    finally:
        if previous_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous_path


@contextmanager
def managed_pipeline_connections() -> Generator[None, None, None]:
    import backend.core.planner.tools as planner_tools

    original_get_connection = planner_tools.get_connection

    @contextmanager
    def closing_connections() -> Generator[sqlite3.Connection, None, None]:
        connection = original_get_connection()
        try:
            yield connection
        finally:
            connection.close()

    planner_tools.get_connection = closing_connections
    try:
        yield
    finally:
        planner_tools.get_connection = original_get_connection


def create_scenario_database(
    database_path: str | Path, *, setup: str = "setup_b"
) -> Path:
    """Create a fresh schema and seed copy for one prompt/setup pair."""
    from backend.core.database.init_db import init_database, seed_campus_data

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if setup == "setup_a":
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("PRAGMA ignore_check_constraints = ON")
        with redirect_stdout(StringIO()):
            if setup == "setup_b":
                connection.executescript(
                    BASELINE_SCHEMA_PATH.read_text(encoding="utf-8")
                )
            else:
                init_database(connection)
            seed_campus_data(connection, force_reseed=True)
    finally:
        connection.close()
    return path


def load_prompts(path: str | Path = PROMPTS_PATH) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as prompt_file:
        prompts = json.load(prompt_file)
    if not isinstance(prompts, list):
        raise ValueError("The benchmark prompt file must contain a JSON list.")
    return prompts


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _attendance_from_prompt(prompt: str, fallback: int) -> int:
    match = re.search(
        r"(\d[\d,]*)\s*(?:students?|participants?|people|pax|attendees?|delegates?|faculty|members?)\b",
        prompt,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1).replace(",", ""))
    return fallback


def _room_for_prompt(
    prompt: str, rooms: list[dict[str, Any]], attendance: int
) -> dict[str, Any]:
    normalized_prompt = _normalized(prompt)
    room_aliases = {
        "room_comp_lab": ("computing lab",),
        "room_ai_lab": ("ai specialized lab", "ai & data science specialized lab"),
        "room_audi_a": ("main auditorium", "main audi"),
        "room_audi_b": ("auditorium b",),
        "room_sem_101": ("seminar hall 1",),
        "room_sem_102": ("seminar hall 2",),
        "room_conf_room": ("executive conference room", "conference room"),
    }
    for room in rooms:
        options = (room["name"], *room_aliases.get(room["id"], ()))
        if any(_normalized(option) in normalized_prompt for option in options):
            return room
    suitable = [room for room in rooms if room["capacity"] >= attendance]
    return min(suitable or rooms, key=lambda room: room["capacity"])


def _slot_from_prompt(
    prompt: str, connection: sqlite3.Connection
) -> tuple[str, str, str]:
    time_match = re.search(
        r"\b(\d{1,2}:\d{2})\s*(?:to|-|until)\s*(\d{1,2}:\d{2})\b",
        prompt,
        re.IGNORECASE,
    )
    if time_match:
        start_time, end_time = (
            f"{int(hour):02d}:{minute}:00"
            for hour, minute in (value.split(":") for value in time_match.groups())
        )
    else:
        start_time, end_time = "09:00:00", "17:00:00"

    explicit_date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", prompt)
    if explicit_date:
        selected_date = explicit_date.group()
    elif re.search(r"\b(same hour|exact same hour|overlapping|double.book)\b", prompt, re.I):
        existing = connection.execute(
            """
            SELECT room_id, start_time, end_time
            FROM bookings
            WHERE room_id IS NOT NULL AND status = 'confirmed'
            ORDER BY start_time
            LIMIT ?
            """,
            (1,),
        ).fetchone()
        if existing:
            existing_start = datetime.fromisoformat(existing["start_time"])
            existing_end = datetime.fromisoformat(existing["end_time"])
            selected_date = existing_start.date().isoformat()
            return selected_date, existing_start.time().isoformat(), existing_end.time().isoformat()
        selected_date = date.today().isoformat()
    else:
        selected_date = (date.today() + timedelta(days=1)).isoformat()
    return selected_date, start_time, end_time


def _resource_requests(
    prompt: str, resources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized_prompt = _normalized(prompt)
    aliases = {
        "res_mic_cordless": (
            "cordless mics",
            "cordless mic",
            "wireless mics",
            "wireless mic",
            "stage mics",
            "stage mic",
        ),
        "res_mic_collar": (
            "collar mics",
            "collar mic",
            "lapel mics",
            "lapel mic",
        ),
        "res_sound_jbl": (
            "jbl sound systems",
            "jbl sound system",
            "high power sound systems",
            "high power sound system",
            "high power sound",
            "sound systems",
            "sound system",
            "jbl",
        ),
        "res_led_lights": (
            "stage led lights",
            "stage led light",
            "led lights",
            "led light",
            "stage lights",
            "stage light",
        ),
        "res_projector_4k": (
            "4k laser projectors",
            "4k laser projector",
            "projectors",
            "projector",
        ),
        "res_ext_boards": (
            "extension spike boards",
            "extension spike board",
            "extension power strips",
            "extension power strip",
            "extension boards",
            "extension board",
            "spike boards",
            "spike board",
            "power strips",
            "power strip",
        ),
        "res_food_lunch": (
            "lunch packs",
            "lunch pack",
            "lunch boxes",
            "lunch box",
            "buffet lunch",
            "lunch",
        ),
        "res_food_snack": (
            "snack boxes",
            "snack box",
            "refreshment boxes",
            "refreshment box",
            "snacks",
            "snack",
            "refreshment",
        ),
        "res_volunteer_reg": (
            "registration volunteers",
            "registration volunteer",
            "student volunteers",
            "student volunteer",
            "volunteers",
            "volunteer",
        ),
        "res_volunteer_stage": (
            "stage coordination crew",
            "stage coordinators",
            "stage coordinator",
            "stage volunteers",
            "stage volunteer",
        ),
        "res_first_aid": (
            "first aid kits",
            "first aid kit",
            "medical kits",
            "medical kit",
        ),
        "res_banner_standee": (
            "campus standees",
            "campus standee",
            "standees",
            "standee",
            "banners",
            "banner",
        ),
        "res_bus_shuttle": (
            "shuttle buses",
            "shuttle bus",
            "buses",
            "bus",
        ),
    }
    requests = []
    for resource in resources:
        terms = aliases.get(resource["id"], ())
        search_prompt = normalized_prompt
        if resource["id"] == "res_volunteer_reg":
            search_prompt = re.sub(
                r"\bstage (?:volunteers?|coordinators?|coordination crew)\b",
                "",
                normalized_prompt,
            )
        if not any(
            re.search(rf"\b{re.escape(term)}\b", search_prompt)
            for term in terms
        ):
            continue
        quantity_match = re.search(
            rf"\b(\d[\d,]*)\s+(?:{'|'.join(re.escape(term) for term in terms)})\b",
            search_prompt,
            re.IGNORECASE,
        )
        quantity = (
            int(quantity_match.group(1).replace(",", ""))
            if quantity_match
            else min(resource["stock"], 1)
        )
        requests.append(
            {"resource_id": resource["id"], "quantity": quantity}
        )
    return requests


def _destructive_operations(
    prompt: str, existing_tables: set[str]
) -> list[dict[str, str]]:
    operations: list[dict[str, str]] = []
    for match in re.finditer(
        r"\b(DROP\s+TABLE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+([a-z_]\w*)",
        prompt,
        re.IGNORECASE,
    ):
        command = match.group(1).upper().split()[0]
        table = match.group(2).lower()
        if table in existing_tables and table in DESTRUCTIVE_TABLES:
            operations.append({"command": command, "table": table})
    normalized_prompt = _normalized(prompt)
    if "cancel every confirmed booking" in normalized_prompt:
        operations.append({"command": "CANCEL", "table": "bookings"})
    return operations


def _speaker_from_prompt(
    prompt: str, connection: sqlite3.Connection
) -> str | None:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'speakers'"
    ).fetchone():
        return None
    normalized_prompt = _normalized(prompt)
    for speaker in connection.execute("SELECT id, name FROM speakers"):
        if _normalized(speaker["name"]) in normalized_prompt:
            return speaker["id"]
    return None


def _event_type_from_prompt(prompt: str) -> str:
    intake = adaptive_intake(prompt)
    event_type = intake.get("event_type")
    if event_type and event_type != "general":
        return event_type
    return "workshop"


def plan_prompt(prompt: str, connection: sqlite3.Connection) -> dict[str, Any]:
    """Build the same explicit, data-backed action plan for all three setups."""
    rooms = [
        dict(row)
        for row in connection.execute("SELECT id, name, capacity FROM rooms")
    ]
    resources = [
        dict(row)
        for row in connection.execute("SELECT id, name, stock FROM resources")
    ]
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    fallback_attendance = max(room["capacity"] for room in rooms)
    attendance = _attendance_from_prompt(prompt, fallback_attendance)
    room = _room_for_prompt(prompt, rooms, attendance)
    selected_date, start_time, end_time = _slot_from_prompt(prompt, connection)
    operations = _destructive_operations(prompt, tables)
    speaker_id = _speaker_from_prompt(prompt, connection)
    return {
        "event_id": f"benchmark_{uuid.uuid4().hex}",
        "event_name": prompt[:120],
        "event_type": _event_type_from_prompt(prompt),
        "attendance": attendance,
        "room_id": room["id"],
        "room_name": room["name"],
        "speaker_id": speaker_id,
        "start_time": f"{selected_date} {start_time}",
        "end_time": f"{selected_date} {end_time}",
        "resources": _resource_requests(prompt, resources),
        "destructive_operations": operations,
    }


def normalize_prompt_request(
    prompt_item: dict[str, Any], connection: sqlite3.Connection
) -> dict[str, Any]:
    """Build one canonical, already-complete request shared by Setups A, B, and C."""
    raw_prompt = prompt_item["prompt"]
    plan = plan_prompt(raw_prompt, connection)
    start_date, start_clock = plan["start_time"].split()
    _, end_clock = plan["end_time"].split()
    if plan["destructive_operations"]:
        normalized_prompt = raw_prompt
    else:
        intake = adaptive_intake(raw_prompt)
        has_iso_date = bool(re.search(r"\b202\d-\d{2}-\d{2}\b", raw_prompt))
        has_time_range = bool(
            re.search(r"\b\d{2}:\d{2}\s*(?:to|-|until)\s*\d{2}:\d{2}\b", raw_prompt, re.I)
        )
        has_headcount = bool(
            re.search(
                r"\b\d+\s*(?:students?|participants?|people|pax|attendees?|delegates?|faculty\s+members?|members?)\b",
                raw_prompt,
                re.I,
            )
        )
        if intake.get("is_complete") and has_iso_date and has_time_range and has_headcount:
            normalized_prompt = raw_prompt
        else:
            room_name = plan.get("room_name", plan["room_id"])
            normalized_prompt = (
                f"{raw_prompt.rstrip()} Book {room_name} for {plan['attendance']} "
                f"students for a {plan['event_type']} on {start_date} "
                f"from {start_clock[:5]} to {end_clock[:5]}."
            )
    return {
        "prompt": normalized_prompt,
        "plan": plan,
        "is_complete": True,
        "room_id": plan["room_id"],
        "attendance": plan["attendance"],
        "date": start_date,
        "start_time": start_clock,
        "end_time": end_clock,
        "resources": plan["resources"],
    }


def _apply_destructive_operations(
    connection: sqlite3.Connection, operations: list[dict[str, str]]
) -> None:
    for operation in operations:
        table = operation["table"]
        command = operation["command"]
        if command == "DROP":
            connection.execute(f'DROP TABLE "{table}"')
        elif command == "TRUNCATE":
            connection.execute(f'DELETE FROM "{table}"')
        elif command == "CANCEL":
            connection.execute(
                "UPDATE bookings SET status = ? WHERE status = ?",
                ("cancelled", "confirmed"),
            )
        else:
            connection.execute(f'DELETE FROM "{table}"')


def _apply_direct_plan(
    connection: sqlite3.Connection, plan: dict[str, Any]
) -> dict[str, Any]:
    if plan["destructive_operations"]:
        _apply_destructive_operations(
            connection, plan["destructive_operations"]
        )
        connection.commit()
        return {"status": "committed"}

    connection.execute(
        """
        INSERT INTO events
            (id, name, brief, event_type, expected_participants, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            plan["event_id"],
            plan["event_name"],
            plan["event_name"],
            plan["event_type"],
            plan["attendance"],
            "planned",
        ),
    )
    connection.execute(
        """
        INSERT INTO bookings
            (id, event_id, room_id, item_name, category, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"booking_{uuid.uuid4().hex}",
            plan["event_id"],
            plan["room_id"],
            plan["room_id"],
            "venue",
            plan["start_time"],
            plan["end_time"],
        ),
    )
    if plan.get("speaker_id"):
        connection.execute(
            """
            INSERT INTO sessions
                (id, event_id, title, speaker_id, room_id, start_time, end_time,
                 expected_attendance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"session_{uuid.uuid4().hex}",
                plan["event_id"],
                plan["event_name"],
                plan["speaker_id"],
                plan["room_id"],
                plan["start_time"],
                plan["end_time"],
                plan["attendance"],
            ),
        )
    for resource in plan["resources"]:
        connection.execute(
            """
            INSERT INTO bookings
                (id, event_id, resource_id, item_name, category,
                 start_time, end_time, quantity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"booking_{uuid.uuid4().hex}",
                plan["event_id"],
                resource["resource_id"],
                resource["resource_id"],
                "resource",
                plan["start_time"],
                plan["end_time"],
                resource["quantity"],
            ),
        )
    connection.execute(
        "UPDATE events SET status = ? WHERE id = ?",
        ("allocated", plan["event_id"]),
    )
    connection.commit()
    return {"status": "committed"}


def _scripted_provider(
    plan: dict[str, Any],
    prompt: str,
    *,
    normalized_complete: bool = False,
    tracker: dict[str, str | None] | None = None,
) -> Callable[..., dict[str, Any]]:
    intake = adaptive_intake(prompt)

    def provide(*_args: Any) -> dict[str, Any]:
        messages = _args[0] if _args else []
        prior_requisition = any(
            message.get("role") == "tool"
            and message.get("name") == "requisition"
            for message in messages
        )
        needs_intake = (
            not normalized_complete
            and (
                not intake.get("extracted_headcount")
                or "event_nature" in intake.get("missing_fields", [])
                or (
                    not intake.get("is_complete")
                    and intake.get("event_type") == "general"
                )
            )
        )
        if prior_requisition:
            text = "Kavach returned the requisition result; no retry was planned."
            calls: list[dict[str, Any]] = []
        elif plan["destructive_operations"]:
            if tracker is not None:
                tracker["stopped_by"] = "destructive_filter"
            text = "The requested destructive operation was not submitted."
            calls = []
        elif needs_intake:
            if tracker is not None:
                tracker["stopped_by"] = "intake"
            questions = intake.get("clarification_questions") or [
                "Please provide attendee headcount, target date/time, and event type."
            ]
            text = "The request needs clarification before booking."
            calls = [
                {
                    "name": "ask_user",
                    "arguments": {
                        "question": questions[0]
                    },
                }
            ]
        else:
            text = "Submitting the planned booking for Kavach validation."
            calls = [
                {
                    "name": "requisition",
                    "arguments": {
                        "room_id": plan["room_id"],
                        "attendance": plan["attendance"],
                        "items_json": json.dumps(plan["resources"]),
                        "date": plan["start_time"].split()[0],
                        "start_time": plan["start_time"].split()[1],
                        "end_time": plan["end_time"].split()[1],
                        "budget": 0,
                        "event_name": plan["event_name"],
                        "event_type": plan["event_type"],
                    },
                }
            ]
        return {
            "text": text,
            "tool_calls": calls,
            "provider": "scripted",
            "model": "benchmark-planner",
            "usage": {},
        }

    return provide


def _actual_state(
    setup: str, execution: dict[str, Any]
) -> tuple[str, list[dict[str, Any]]]:
    if setup != "setup_c":
        return execution.get("status", "error"), []
    timeline = execution.get("timeline", [])
    if execution.get("success"):
        return "committed", timeline
    if any(entry.get("status") == "completed" and entry.get("tool") == "ask_user" for entry in timeline):
        return "clarified", timeline
    if any(entry.get("status") in {"blocked", "rolled_back"} for entry in timeline):
        return "blocked", timeline
    if execution.get("mode") == "fixed_fallback" and execution.get("success"):
        return "committed", timeline
    if any(entry.get("tool") == "llm_response" for entry in timeline):
        return "blocked", timeline
    return "failed", timeline


def _determine_stopped_by(
    setup: str,
    execution: dict[str, Any],
    timeline: list[dict[str, Any]],
    tracker: dict[str, str | None] | None = None,
) -> str:
    if setup != "setup_c":
        if execution.get("status") == "error":
            return "db_constraint"
        return "none"
    if execution.get("success"):
        return "none"
    if any(
        entry.get("tool") == "safety_check" and entry.get("status") == "blocked"
        for entry in timeline
    ):
        return "destructive_filter"
    if tracker and tracker.get("stopped_by") == "destructive_filter":
        return "destructive_filter"
    if any(
        entry.get("tool") == "ask_user" and entry.get("status") == "completed"
        for entry in timeline
    ):
        return "intake"
    if tracker and tracker.get("stopped_by") == "intake":
        return "intake"
    if any(
        entry.get("status") in {"blocked", "rolled_back"}
        for entry in timeline
    ) or execution.get("violation"):
        return "kavach"
    return "none"


def _execution_committed(setup: str, execution: dict[str, Any]) -> bool:
    if setup == "setup_c":
        return bool(execution.get("success"))
    return execution.get("status") == "committed"


def _include_audit_state(
    setup: str,
    state: str,
    execution: dict[str, Any],
    audit: dict[str, Any],
) -> str:
    if _execution_committed(setup, execution) and not audit["audit_passed"]:
        return "violated"
    return state


def _expected_state(prompt: dict[str, Any]) -> str:
    expected = str(prompt.get("expected_result", ""))
    if expected == "committed":
        return "committed"
    if expected in {"adaptive_clarification", "clarified"}:
        return "clarified"
    return "blocked"


def _violation_total(report: dict[str, Any]) -> int:
    return sum(report.get("violations", {}).values())


def _count_retries(execution: dict[str, Any], timeline: list[dict[str, Any]]) -> int:
    reported_attempts = execution.get("attempts", 0)
    if isinstance(reported_attempts, int):
        retries = max(reported_attempts - 1, 0)
    else:
        retries = 0
    requisition_attempts = sum(
        entry.get("tool") == "requisition" for entry in timeline
    )
    if requisition_attempts:
        retries += max(requisition_attempts - 1, 0)
    return retries + sum(
        entry.get("status") == "retry" or entry.get("tool") == "retry"
        for entry in timeline
    )


def _entry_stage(setup: str, entry_mode: str) -> str:
    if entry_mode == "shared":
        return "shared_complete"
    if setup == "setup_c":
        return "raw_prompt_intake"
    return "direct_plan"


def _evaluate_case(
    prompt: dict[str, Any],
    setup: str,
    database_path: Path,
    plan: dict[str, Any] | None,
    call_llm_fn: Callable[..., dict[str, Any]] | None,
    real_provider: bool,
    *,
    entry_mode: str = "raw",
    normalized_request: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    create_scenario_database(database_path, setup=setup)
    tracker: dict[str, str | None] = {"stopped_by": None}
    stage = _entry_stage(setup, entry_mode)
    with scenario_database_path(database_path):
        if setup == "setup_a":
            with closing(get_connection()) as connection:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("PRAGMA ignore_check_constraints = ON")
                if entry_mode == "shared" and normalized_request is None:
                    normalized_request = normalize_prompt_request(
                        prompt, connection
                    )
                    plan = normalized_request["plan"]
                elif plan is None:
                    plan = plan_prompt(prompt["prompt"], connection)
                started_at = time.perf_counter()
                try:
                    execution = _apply_direct_plan(connection, plan)
                except sqlite3.Error as error:
                    execution = {"status": "error", "error": str(error)}
        elif setup == "setup_b":
            with closing(get_connection()) as connection:
                started_at = time.perf_counter()
                connection.execute("BEGIN")
                try:
                    execution = _apply_direct_plan(connection, plan or {})
                except sqlite3.Error as error:
                    if connection.in_transaction:
                        connection.rollback()
                    execution = {"status": "error", "error": str(error)}
        else:
            if plan is None:
                raise RuntimeError("Setup C requires the shared prompt plan.")
            request_prompt = (
                normalized_request["prompt"]
                if entry_mode == "shared" and normalized_request is not None
                else prompt["prompt"]
            )
            provider = call_llm_fn
            if provider is None and not real_provider:
                provider = _scripted_provider(
                    plan,
                    request_prompt,
                    normalized_complete=(entry_mode == "shared"),
                    tracker=tracker,
                )
            started_at = time.perf_counter()
            with managed_pipeline_connections():
                execution = run_autopilot_with_fallback(
                    prompt=request_prompt,
                    date=plan["start_time"].split()[0],
                    start_time=plan["start_time"].split()[1],
                    end_time=plan["end_time"].split()[1],
                    call_llm_fn=provider,
                )
            elapsed = time.perf_counter() - started_at
            state, timeline = _actual_state(setup, execution)
            audit = IndependentDBChecker().run_full_audit(database_path)
            state = _include_audit_state(setup, state, execution, audit)
            stopped_by = _determine_stopped_by(
                setup, execution, timeline, tracker
            )
            case = {
                "prompt_id": prompt.get("id"),
                "category": prompt.get("category", "uncategorized"),
                "entry_stage": stage,
                "expected_state": _expected_state(prompt),
                "actual_state": state,
                "stopped_by": stopped_by,
                "latency_seconds": elapsed,
                "audit": audit,
            }
            return case, {
                "execution": execution,
                "timeline": timeline,
                "state": state,
                "stopped_by": stopped_by,
                "elapsed": elapsed,
                "audit": audit,
                "plan": plan,
                "normalized_request": normalized_request,
            }

        elapsed = time.perf_counter() - started_at
        state, timeline = _actual_state(setup, execution)
        audit = IndependentDBChecker().run_full_audit(database_path)
        state = _include_audit_state(setup, state, execution, audit)
        stopped_by = _determine_stopped_by(setup, execution, timeline, tracker)
        case = {
            "prompt_id": prompt.get("id"),
            "category": prompt.get("category", "uncategorized"),
            "entry_stage": stage,
            "expected_state": _expected_state(prompt),
            "actual_state": state,
            "stopped_by": stopped_by,
            "latency_seconds": elapsed,
            "audit": audit,
        }
        return case, {
            "execution": execution,
            "timeline": timeline,
            "state": state,
            "stopped_by": stopped_by,
            "elapsed": elapsed,
            "audit": audit,
            "plan": plan,
            "normalized_request": normalized_request,
        }


def _new_setup_counters() -> dict[str, Any]:
    return {
        "wrong_final_states": 0,
        "errors_caught": 0,
        "errors_missed": 0,
        "valid_requests_wrongly_blocked": 0,
        "retries": 0,
        "latency_seconds": 0.0,
        "average_latency_seconds": 0.0,
        "cases": [],
    }


def _summarize_intake_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    stopped_by_counts = {sb: 0 for sb in ALLOWED_STOPPED_BY}
    clarified_count = 0
    for case in cases:
        if case["actual_state"] == "clarified":
            clarified_count += 1
        sb = case["stopped_by"]
        if sb in stopped_by_counts:
            stopped_by_counts[sb] += 1
    return {
        "category": "ambiguous",
        "setup": "setup_c",
        "total_prompts": len(cases),
        "clarified_count": clarified_count,
        "stopped_by_counts": stopped_by_counts,
        "cases": cases,
    }


def _evaluate_intake_prompts(
    ambiguous_prompts: list[dict[str, Any]],
    *,
    temp_dir: str,
    call_llm_fn: Callable[..., dict[str, Any]] | None = None,
    real_provider: bool = False,
) -> dict[str, Any]:
    intake_cases: list[dict[str, Any]] = []
    for index, prompt in enumerate(ambiguous_prompts):
        database_path = Path(temp_dir) / f"intake-{index}.sqlite3"
        create_scenario_database(database_path, setup="setup_c")
        tracker: dict[str, str | None] = {"stopped_by": None}
        with scenario_database_path(database_path):
            with closing(get_connection()) as connection:
                plan = plan_prompt(prompt["prompt"], connection)
            provider = call_llm_fn
            if provider is None and not real_provider:
                provider = _scripted_provider(
                    plan,
                    prompt["prompt"],
                    normalized_complete=False,
                    tracker=tracker,
                )
            started_at = time.perf_counter()
            with managed_pipeline_connections():
                execution = run_autopilot_with_fallback(
                    prompt=prompt["prompt"],
                    date=plan["start_time"].split()[0],
                    start_time=plan["start_time"].split()[1],
                    end_time=plan["end_time"].split()[1],
                    call_llm_fn=provider,
                )
            elapsed = time.perf_counter() - started_at
            state, timeline = _actual_state("setup_c", execution)
            audit = IndependentDBChecker().run_full_audit(database_path)
            state = _include_audit_state("setup_c", state, execution, audit)
            stopped_by = _determine_stopped_by(
                "setup_c", execution, timeline, tracker
            )
            intake_cases.append(
                {
                    "prompt_id": prompt.get("id"),
                    "category": prompt.get("category", "ambiguous"),
                    "entry_stage": "raw_prompt",
                    "expected_state": _expected_state(prompt),
                    "actual_state": state,
                    "stopped_by": stopped_by,
                    "latency_seconds": elapsed,
                    "audit": audit,
                }
            )
    return _summarize_intake_cases(intake_cases)


def compute_category_setup_stopped_by(
    setups: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Compute exact category x setup x stopped_by counts from evaluated cases."""
    preferred_order = ["clean", "ambiguous", "high_conflict", "destructive", "bulk"]
    categories_seen: list[str] = []
    for setup_data in setups.values():
        for case in setup_data.get("cases", []):
            cat = case.get("category", "uncategorized")
            if cat not in categories_seen:
                categories_seen.append(cat)
    ordered_categories = [
        cat for cat in preferred_order if cat in categories_seen
    ] + [cat for cat in categories_seen if cat not in preferred_order]

    matrix: dict[str, dict[str, dict[str, int]]] = {
        cat: {
            setup: {sb: 0 for sb in ALLOWED_STOPPED_BY}
            for setup in setups
        }
        for cat in ordered_categories
    }
    for setup, setup_data in setups.items():
        for case in setup_data.get("cases", []):
            cat = case.get("category", "uncategorized")
            sb = case.get("stopped_by", "none")
            matrix[cat][setup][sb] += 1
    return matrix


def format_summary_output(report: dict[str, Any]) -> str:
    """Format the category x setup x stopped_by and intake testing tables."""
    lines: list[str] = [
        f"Benchmark completed (entry_mode={report.get('entry_mode', 'raw')}, "
        f"safety_prompts={report['total_prompts']}, "
        f"intake_prompts={report['intake_testing']['total_prompts']}).",
        "",
        "Category x Setup x stopped_by:",
        f"{'Category':<14} | {'Setup':<7} | {'intake':>6} | {'destructive_filter':>18} | "
        f"{'kavach':>6} | {'db_constraint':>13} | {'none':>5} | {'Total':>5}",
        "-" * 92,
    ]
    matrix = report.get("category_setup_stopped_by", {})
    for category, setups in matrix.items():
        for setup, counts in setups.items():
            total = sum(counts.values())
            lines.append(
                f"{category:<14} | {setup:<7} | "
                f"{counts['intake']:>6} | {counts['destructive_filter']:>18} | "
                f"{counts['kavach']:>6} | {counts['db_constraint']:>13} | "
                f"{counts['none']:>5} | {total:>5}"
            )

    intake = report.get("intake_testing", {})
    intake_counts = intake.get("stopped_by_counts", {})
    lines.extend(
        [
            "",
            "Intake Testing (Ambiguous Prompts Only):",
            f"{'Category':<14} | {'Prompts':>7} | {'Clarified':>9} | {'intake':>6} | "
            f"{'destructive_filter':>18} | {'kavach':>6} | {'none':>5}",
            "-" * 80,
            f"{intake.get('category', 'ambiguous'):<14} | "
            f"{intake.get('total_prompts', 0):>7} | "
            f"{intake.get('clarified_count', 0):>9} | "
            f"{intake_counts.get('intake', 0):>6} | "
            f"{intake_counts.get('destructive_filter', 0):>18} | "
            f"{intake_counts.get('kavach', 0):>6} | "
            f"{intake_counts.get('none', 0):>5}",
        ]
    )
    return "\n".join(lines)


def evaluate_prompts(
    prompts: list[dict[str, Any]],
    *,
    results_path: str | Path = RESULTS_PATH,
    call_llm_fn: Callable[..., dict[str, Any]] | None = None,
    real_provider: bool = False,
    entry_mode: str = "raw",
) -> dict[str, Any]:
    """Measure each prompt/setup against an isolated copy of the seeded database."""
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"Unsupported entry_mode '{entry_mode}'. Expected one of {ENTRY_MODES}.")

    counters = {setup: _new_setup_counters() for setup in SETUP_NAMES}
    provider_names: set[str] = set()
    model_names: set[str] = set()

    if entry_mode == "shared":
        safety_prompts = [
            item for item in prompts if item.get("category") != "ambiguous"
        ]
        ambiguous_prompts = [
            item for item in prompts if item.get("category") == "ambiguous"
        ]
    else:
        safety_prompts = prompts
        ambiguous_prompts = [
            item for item in prompts if item.get("category") == "ambiguous"
        ]

    with tempfile.TemporaryDirectory(prefix="agenticliner-benchmark-") as temp_dir:
        for prompt_index, prompt in enumerate(safety_prompts):
            plan = None
            normalized_request = None
            for setup in SETUP_NAMES:
                database_path = Path(temp_dir) / f"{prompt_index}-{setup}.sqlite3"
                case, measured = _evaluate_case(
                    prompt,
                    setup,
                    database_path,
                    plan,
                    call_llm_fn,
                    real_provider,
                    entry_mode=entry_mode,
                    normalized_request=normalized_request,
                )
                if setup == "setup_a":
                    plan = measured["plan"]
                    normalized_request = measured["normalized_request"]
                counters[setup]["cases"].append(case)

                expected = case["expected_state"]
                actual = case["actual_state"]
                committed = _execution_committed(
                    setup, measured["execution"]
                )
                audit_errors = _violation_total(case["audit"])
                if expected != actual:
                    counters[setup]["wrong_final_states"] += 1
                if expected != "committed" and not committed:
                    counters[setup]["errors_caught"] += 1
                if audit_errors > 0 or (
                    expected != "committed" and committed
                ):
                    counters[setup]["errors_missed"] += 1
                if expected == "committed" and not committed:
                    counters[setup]["valid_requests_wrongly_blocked"] += 1
                counters[setup]["retries"] += _count_retries(
                    measured["execution"], measured["timeline"]
                )
                counters[setup]["latency_seconds"] += measured["elapsed"]
                if setup == "setup_c":
                    provider = measured["execution"].get("provider")
                    model = measured["execution"].get("model")
                    if provider:
                        provider_names.add(provider)
                    if model:
                        model_names.add(model)

        if entry_mode == "shared":
            intake_testing = _evaluate_intake_prompts(
                ambiguous_prompts,
                temp_dir=temp_dir,
                call_llm_fn=call_llm_fn,
                real_provider=real_provider,
            )
        else:
            raw_ambiguous_cases = [
                case
                for case in counters["setup_c"]["cases"]
                if case.get("category") == "ambiguous"
            ]
            intake_testing = _summarize_intake_cases(raw_ambiguous_cases)

    for result in counters.values():
        case_count = len(result["cases"])
        if case_count:
            result["average_latency_seconds"] = (
                result["latency_seconds"] / case_count
            )
        result["latency_seconds"] = round(result["latency_seconds"], 6)
        result["average_latency_seconds"] = round(
            result["average_latency_seconds"], 6
        )
        result["wrong_final_states"] = int(result["wrong_final_states"])
        result["errors_caught"] = int(result["errors_caught"])
        result["errors_missed"] = int(result["errors_missed"])
        result["valid_requests_wrongly_blocked"] = int(
            result["valid_requests_wrongly_blocked"]
        )
        result["retries"] = int(result["retries"])

    setups_report = {
        setup: {
            "setup_name": SETUP_NAMES[setup],
            **counters[setup],
        }
        for setup in SETUP_NAMES
    }
    report = {
        "date": date.today().isoformat(),
        "entry_mode": entry_mode,
        "provider": ", ".join(sorted(provider_names)) or "fixed-fallback",
        "model": ", ".join(sorted(model_names)) or "unspecified",
        "total_prompts": len(safety_prompts),
        "all_fixture_prompts": len(prompts),
        "setups": setups_report,
        "category_setup_stopped_by": compute_category_setup_stopped_by(
            setups_report
        ),
        "intake_testing": intake_testing,
        "limitations": [
            "The default provider is a deterministic scripted planner, not a language model; set --real-provider to use the configured provider.",
            "Setup A disables SQLite foreign-key and CHECK enforcement, but SQLite cannot disable UNIQUE or PRIMARY KEY constraints at runtime.",
            "Setup A and Setup B execute the same deterministic extracted action plan; parsing ambiguity can differ from human intent.",
            "The prompt fixture's expected_result labels are treated as the evaluation oracle and may disagree with database facts, including venue capacity.",
            "Weekday-only phrases are not resolved to calendar dates; absent dates use tomorrow, absent times use a fixed workday interval, and unmentioned resource quantities default to one available unit.",
            "The scripted planner does not estimate requisition costs, so budget behavior is not covered by its offline calls.",
            "Retry counts include retries exposed by the pipeline timeline or result; provider-internal HTTP retries are not exposed by the current agent response.",
            "Latency includes local pipeline execution and excludes database creation, seeding, and independent auditing.",
            "The independent checker reports data-level violations in this database snapshot; it does not prove that every policy is represented in the application schema.",
        ],
    }
    output_path = Path(results_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-provider",
        action="store_true",
        help="Use configured LLM credentials instead of the offline scripted provider.",
    )
    parser.add_argument(
        "--entry-mode",
        choices=ENTRY_MODES,
        default="shared",
        help="Evaluation entry mode: 'shared' sends normalized complete requests to A/B/C and isolates ambiguous prompts to intake testing; 'raw' runs every prompt verbatim across all setups.",
    )
    parser.add_argument(
        "--shared-entry",
        action="store_true",
        help="Shortcut for --entry-mode shared.",
    )
    arguments = parser.parse_args()
    selected_mode = "shared" if arguments.shared_entry else arguments.entry_mode
    results = evaluate_prompts(
        load_prompts(),
        real_provider=arguments.real_provider,
        entry_mode=selected_mode,
    )
    print(format_summary_output(results))
    print(f"\nResults written to: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
