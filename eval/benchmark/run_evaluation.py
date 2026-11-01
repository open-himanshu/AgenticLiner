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
SETUP_NAMES = {
    "setup_a": "Setup A (Direct planned actions)",
    "setup_b": "Setup B (SQLite constraints only)",
    "setup_c": "Setup C (Kavach agent pipeline)",
}
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
            f"{value}:00" for value in time_match.groups()
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
        "res_mic_cordless": ("cordless mic", "wireless mic", "wireless mics"),
        "res_mic_collar": ("collar mic", "lapel mic"),
        "res_sound_jbl": ("sound system", "jbl", "high power sound"),
        "res_led_lights": ("led light", "stage light"),
        "res_projector_4k": ("projector",),
        "res_ext_boards": ("extension board", "spike board", "power strip"),
        "res_food_lunch": ("lunch pack", "lunch box", "lunch"),
        "res_food_snack": ("snack", "refreshment"),
        "res_volunteer_reg": ("volunteer",),
        "res_bus_shuttle": ("shuttle bus", "buses", "bus"),
    }
    requests = []
    for resource in resources:
        terms = aliases.get(resource["id"], ())
        if not any(term in normalized_prompt for term in terms):
            continue
        quantity_match = re.search(
            rf"\b(\d[\d,]*)\s+(?:wireless\s+|cordless\s+)?"
            rf"(?:{ '|'.join(re.escape(term) for term in terms) })\b",
            prompt,
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
    return {
        "event_id": f"benchmark_{uuid.uuid4().hex}",
        "event_name": prompt[:120],
        "event_type": "workshop",
        "attendance": attendance,
        "room_id": room["id"],
        "start_time": f"{selected_date} {start_time}",
        "end_time": f"{selected_date} {end_time}",
        "resources": _resource_requests(prompt, resources),
        "destructive_operations": operations,
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
    plan: dict[str, Any], prompt: str
) -> Callable[..., dict[str, Any]]:
    intake = adaptive_intake(prompt)

    def provide(*_args: Any) -> dict[str, Any]:
        messages = _args[0] if _args else []
        prior_requisition = any(
            message.get("role") == "tool"
            and message.get("name") == "requisition"
            for message in messages
        )
        if prior_requisition:
            text = "Kavach returned the requisition result; no retry was planned."
            calls: list[dict[str, Any]] = []
        elif plan["destructive_operations"]:
            text = "The requested destructive operation was not submitted."
            calls: list[dict[str, Any]] = []
        elif (
            not intake.get("extracted_headcount")
            or intake.get("event_type") == "general"
        ):
            text = "The request needs clarification before booking."
            calls = [
                {
                    "name": "ask_user",
                    "arguments": {
                        "question": intake["clarification_questions"][0]
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
    if expected == "adaptive_clarification":
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


def _evaluate_case(
    prompt: dict[str, Any],
    setup: str,
    database_path: Path,
    plan: dict[str, Any] | None,
    call_llm_fn: Callable[..., dict[str, Any]] | None,
    real_provider: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    create_scenario_database(database_path, setup=setup)
    with scenario_database_path(database_path):
        if setup == "setup_a":
            with closing(get_connection()) as connection:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("PRAGMA ignore_check_constraints = ON")
                if plan is None:
                    plan = plan_prompt(prompt["prompt"], connection)
                started_at = time.perf_counter()
                try:
                    execution = _apply_direct_plan(connection, plan)
                except sqlite3.Error as error:
                    execution = {"status": "error", "error": str(error)}
        elif setup == "setup_b":
            with closing(get_connection()) as connection:
                started_at = time.perf_counter()
                try:
                    execution = _apply_direct_plan(connection, plan or {})
                except sqlite3.Error as error:
                    execution = {"status": "error", "error": str(error)}
        else:
            if plan is None:
                raise RuntimeError("Setup C requires the shared prompt plan.")
            provider = call_llm_fn
            if provider is None and not real_provider:
                provider = _scripted_provider(plan, prompt["prompt"])
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
            state, timeline = _actual_state(setup, execution)
            audit = IndependentDBChecker().run_full_audit(database_path)
            state = _include_audit_state(setup, state, execution, audit)
            case = {
                "prompt_id": prompt.get("id"),
                "expected_state": _expected_state(prompt),
                "actual_state": state,
                "latency_seconds": elapsed,
                "audit": audit,
            }
            return case, {
                "execution": execution,
                "timeline": timeline,
                "state": state,
                "elapsed": elapsed,
                "audit": audit,
                "plan": plan,
            }

        elapsed = time.perf_counter() - started_at
        state, timeline = _actual_state(setup, execution)
        audit = IndependentDBChecker().run_full_audit(database_path)
        state = _include_audit_state(setup, state, execution, audit)
        case = {
            "prompt_id": prompt.get("id"),
            "expected_state": _expected_state(prompt),
            "actual_state": state,
            "latency_seconds": elapsed,
            "audit": audit,
        }
        return case, {
            "execution": execution,
            "timeline": timeline,
            "state": state,
            "elapsed": elapsed,
            "audit": audit,
            "plan": plan,
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


def evaluate_prompts(
    prompts: list[dict[str, Any]],
    *,
    results_path: str | Path = RESULTS_PATH,
    call_llm_fn: Callable[..., dict[str, Any]] | None = None,
    real_provider: bool = False,
) -> dict[str, Any]:
    """Measure each prompt/setup against an isolated copy of the seeded database."""
    counters = {setup: _new_setup_counters() for setup in SETUP_NAMES}
    provider_names: set[str] = set()
    model_names: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="agenticliner-benchmark-") as temp_dir:
        for prompt_index, prompt in enumerate(prompts):
            plan = None
            for setup in SETUP_NAMES:
                database_path = Path(temp_dir) / f"{prompt_index}-{setup}.sqlite3"
                case, measured = _evaluate_case(
                    prompt,
                    setup,
                    database_path,
                    plan,
                    call_llm_fn,
                    real_provider,
                )
                if setup == "setup_a":
                    plan = measured["plan"]
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

    report = {
        "date": date.today().isoformat(),
        "provider": ", ".join(sorted(provider_names)) or "fixed-fallback",
        "model": ", ".join(sorted(model_names)) or "unspecified",
        "total_prompts": len(prompts),
        "setups": {
            setup: {
                "setup_name": SETUP_NAMES[setup],
                **counters[setup],
            }
            for setup in SETUP_NAMES
        },
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
    arguments = parser.parse_args()
    results = evaluate_prompts(load_prompts(), real_provider=arguments.real_provider)
    print(f"Benchmark completed for {results['total_prompts']} prompts.")
    print(f"Results written to: {RESULTS_PATH}")
    for setup, metrics in results["setups"].items():
        print(
            f"{SETUP_NAMES[setup]}: wrong={metrics['wrong_final_states']}, "
            f"caught={metrics['errors_caught']}, missed={metrics['errors_missed']}, "
            f"false_blocks={metrics['valid_requests_wrongly_blocked']}, "
            f"retries={metrics['retries']}, latency={metrics['latency_seconds']}s"
        )


if __name__ == "__main__":
    main()
