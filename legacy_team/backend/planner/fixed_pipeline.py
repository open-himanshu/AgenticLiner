"""Deterministic event booking fallback; LLM wording is opt-in only."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date, timedelta
import json
import sqlite3
from typing import Any
import uuid

from backend.planner import test_tool_calling as mock_agent
from backend.safety.checkout import (
    MAX_RECORDS_PER_REQUEST,
    checkout,
    connect_database,
    initialize_database,
)


MAX_VENUE_ATTEMPTS = 2
MAX_EQUIPMENT_ITEMS = MAX_RECORDS_PER_REQUEST - 3


def next_friday(today: date | None = None) -> date:
    today = today or date.today()
    days_until_friday = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_until_friday)


def resolve_event_date(value: str, today: date | None = None) -> str:
    normalized = value.strip().lower()
    if normalized == "next friday":
        return next_friday(today).isoformat()
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD or 'next Friday'")
    return parsed.isoformat()


def seed_pipeline_database(connection: sqlite3.Connection) -> None:
    initialize_database(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        "INSERT OR IGNORE INTO venues (id, name, capacity, price_per_hour) "
        "VALUES (?, ?, ?, ?)",
        [
            (venue_id, venue["name"], venue["capacity"], venue["per_hour"])
            for venue_id, venue in mock_agent.VENUES.items()
        ],
    )
    connection.executemany(
        "INSERT OR IGNORE INTO equipment (name, price, stock) VALUES (?, ?, ?)",
        [
            (name, price, stock)
            for name, (stock, price) in mock_agent.STOCK.items()
        ],
    )
    for (venue_id, booking_date), intervals in mock_agent.VENUE_BUSY.items():
        for start_hour, end_hour in intervals:
            connection.execute(
                """
                INSERT OR IGNORE INTO bookings
                    (id, request_id, venue_id, date, start_hour, end_hour,
                     headcount, total_cost, equipment_json)
                VALUES (?, 'seeded-availability', ?, ?, ?, ?, 1, 0, '{}')
                """,
                (
                    f"seed-{venue_id}-{booking_date}-{start_hour}",
                    venue_id,
                    booking_date,
                    start_hour,
                    end_hour,
                ),
            )


def _timeline(step_number: int, name: str, arguments: dict, result: object) -> None:
    print(
        f"[step {step_number}] {name}("
        f"{json.dumps(arguments, ensure_ascii=False, default=str)}) -> "
        f"{json.dumps(result, ensure_ascii=False, default=str)}"
    )


def _free_venues(
    connection: sqlite3.Connection,
    event_date: str,
    start_hour: int,
    end_hour: int,
    headcount: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT id, name, capacity, price_per_hour FROM venues "
        "WHERE capacity >= ? ORDER BY price_per_hour, id",
        (headcount,),
    ).fetchall()
    free_venues = []
    for venue_id, name, capacity, price_per_hour in rows:
        conflict = connection.execute(
            """
            SELECT 1 FROM bookings
            WHERE venue_id = ? AND date = ?
              AND NOT (end_hour <= ? OR start_hour >= ?)
            LIMIT 1
            """,
            (venue_id, event_date, start_hour, end_hour),
        ).fetchone()
        if conflict is None:
            free_venues.append({
                "venue_id": venue_id,
                "name": name,
                "capacity": capacity,
                "price_per_hour": price_per_hour,
            })
    return free_venues


def _recommended_equipment(
    checklist: dict[str, Any],
    history: dict[str, Any],
) -> tuple[dict[str, int], list[str]]:
    recommendations: dict[str, int] = {}
    same_as_last_time = history.get("same_as_last_time") or {}
    recommendations.update(same_as_last_time.get("items") or {})
    for suggestion in history.get("similar_events", []):
        recommendations.setdefault(suggestion["item"], suggestion["suggested_qty"])
    for item in checklist.get("needs", []):
        recommendations.setdefault(item, 1)

    ordered_items = list(dict.fromkeys(checklist.get("needs", []) + list(recommendations)))
    selected = {
        item: recommendations[item]
        for item in ordered_items[:MAX_EQUIPMENT_ITEMS]
        if item in recommendations
    }
    omitted = [item for item in ordered_items[MAX_EQUIPMENT_ITEMS:] if item in recommendations]
    return selected, omitted


def _check_equipment(
    connection: sqlite3.Connection,
    requested: Mapping[str, int],
) -> tuple[dict[str, dict[str, int]], dict[str, int], list[str]]:
    availability: dict[str, dict[str, int]] = {}
    selected: dict[str, int] = {}
    shortages: list[str] = []
    for name, requested_quantity in requested.items():
        row = connection.execute(
            "SELECT stock, price FROM equipment WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            shortages.append(f"{name}: not in inventory")
            continue
        stock, price = row
        availability[name] = {"in_stock": stock, "unit_price": price}
        allowed_quantity = min(requested_quantity, stock)
        if allowed_quantity < requested_quantity:
            shortages.append(
                f"{name}: requested {requested_quantity}, available {stock}"
            )
        if allowed_quantity > 0:
            selected[name] = allowed_quantity
    return availability, selected, shortages


def _notice_text(request: dict[str, Any], venue: dict[str, Any], total_cost: int) -> str:
    return (
        f"Booking request for {request['headcount']} people at {venue['name']} "
        f"on {request['date']} from {request['start_hour']}:00 to "
        f"{request['end_hour']}:00; estimated total {total_cost}."
    )


def _polish_notice(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    try:
        from dotenv import load_dotenv

        load_dotenv(
            dotenv_path=mock_agent.REPOSITORY_ROOT / ".env",
            override=True,
        )
        provider = mock_agent.os.getenv("PROVIDER", "ollama").strip().lower()
        model_names = {
            "gemini": "GEMINI_MODEL",
            "groq": "GROQ_MODEL",
            "ollama": "OLLAMA_MODEL",
        }
        if provider not in model_names:
            return text
        mock_agent.PROVIDER = provider
        mock_agent.ACTIVE_MODEL = mock_agent.os.getenv(
            model_names[provider],
            mock_agent.DEFAULT_OLLAMA_MODEL if provider == "ollama" else "",
        ).strip()
        if not mock_agent.ACTIVE_MODEL:
            return text
        response = mock_agent.call_llm(
            [
                {
                    "role": "system",
                    "content": "Polish this booking notice in one concise sentence. Do not change facts.",
                },
                {"role": "user", "content": text},
            ],
            [],
        )
        polished = (response.get("text") or "").strip()
        return polished or text
    except Exception:
        return text


def run_pipeline(
    request: dict[str, Any],
    connection: sqlite3.Connection | None = None,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    owned_connection = connection is None
    if connection is None:
        connection = connect_database()
    seed_pipeline_database(connection)

    try:
        return _run_pipeline(request, connection, use_llm=use_llm)
    finally:
        if owned_connection:
            connection.close()


def _run_pipeline(
    request: dict[str, Any],
    connection: sqlite3.Connection,
    *,
    use_llm: bool,
) -> dict[str, Any]:
    required_fields = (
        "event_type", "headcount", "date", "start_hour", "end_hour", "budget"
    )
    missing = [field for field in required_fields if field not in request]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    event_type = mock_agent.normalize_event_type(request["event_type"])
    if event_type not in mock_agent.PLAYBOOK:
        raise ValueError("event_type must be dance, hackathon, or seminar")
    headcount = request["headcount"]
    start_hour = request["start_hour"]
    end_hour = request["end_hour"]
    budget = request["budget"]
    if isinstance(headcount, bool) or not isinstance(headcount, int) or headcount <= 0:
        raise ValueError("headcount must be a positive integer")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError("budget must be a non-negative integer")
    if any(isinstance(hour, bool) or not isinstance(hour, int) for hour in (start_hour, end_hour)):
        raise ValueError("start_hour and end_hour must be integers")
    if not 0 <= start_hour < end_hour <= 24:
        raise ValueError("start_hour/end_hour must be an increasing time window")

    event_date = resolve_event_date(str(request["date"]))
    organiser = str(request.get("organiser") or "Organiser").strip() or "Organiser"
    normalized_request = {
        **request,
        "event_type": event_type,
        "headcount": headcount,
        "date": event_date,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "budget": budget,
        "organiser": organiser,
    }
    step = 1

    checklist = mock_agent.get_event_checklist(event_type)
    _timeline(step, "get_event_checklist", {"event_type": event_type}, checklist)
    step += 1

    history = mock_agent.recommend_from_history(event_type, headcount, organiser)
    _timeline(
        step,
        "recommend_from_history",
        {"event_type": event_type, "headcount": headcount, "organiser": organiser},
        history,
    )
    step += 1

    venues = _free_venues(
        connection, event_date, start_hour, end_hour, headcount
    )
    _timeline(
        step,
        "find_free_venues",
        {
            "date": event_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "min_capacity": headcount,
        },
        {"free": venues},
    )
    step += 1
    if not venues:
        report = {
            "status": "no_venue",
            "bookings": [],
            "violations": ["no free venue fits the requested headcount and time"],
            "equipment_shortages": [],
            "assumptions": [],
            "human_decisions": ["Choose another date, time, or a smaller headcount."],
        }
        print_final_report(report, budget)
        return report

    requested_equipment, omitted_items = _recommended_equipment(checklist, history)
    availability, equipment, shortages = _check_equipment(
        connection, requested_equipment
    )
    _timeline(
        step,
        "check_equipment",
        {"item_names": list(requested_equipment)},
        availability,
    )
    step += 1

    assumptions = [
        f"Equipment quantities taken from the last similar event (past headcount "
        f"{(history.get('same_as_last_time') or {}).get('past_headcount', 'unknown')}), "
        "capped to stock and the checkout change limit; not scaled to the new headcount.",
        "Equipment is capped to current stock and the checkout record-change limit.",
    ]
    if omitted_items:
        assumptions.append(
            "Omitted to fit the checkout change limit: " + ", ".join(omitted_items)
        )
    if shortages:
        assumptions.append("Stock limits applied: " + "; ".join(shortages))

    attempts = []
    for venue in venues[:MAX_VENUE_ATTEMPTS]:
        checkout_request = {
            "request_id": uuid.uuid4().hex,
            "venue_id": venue["venue_id"],
            "date": event_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "headcount": headcount,
            "equipment": equipment,
            "budget": budget,
        }
        total_cost = (
            venue["price_per_hour"] * (end_hour - start_hour)
            + sum(
                availability[name]["unit_price"] * quantity
                for name, quantity in equipment.items()
            )
        )
        notice = _polish_notice(
            _notice_text(normalized_request, venue, total_cost), use_llm
        )
        _timeline(
            step,
            "build_equipment_list",
            {"venue_id": venue["venue_id"]},
            {"equipment": equipment, "notice": notice},
        )
        step += 1

        result = checkout(checkout_request, connection)
        _timeline(step, "checkout", checkout_request, result)
        step += 1
        attempts.append({
            "venue_id": venue["venue_id"],
            "status": result["status"],
            "violations": result.get("violations", []),
        })
        if result["status"] == "rolled_back":
            if len(attempts) < MAX_VENUE_ATTEMPTS and len(venues) > len(attempts):
                continue
            report = {
                "status": "rejected",
                "bookings": [],
                "violations": result["violations"],
                "equipment_shortages": shortages,
                "attempts": attempts,
                "assumptions": assumptions,
                "human_decisions": ["Review the checkout violations and choose an adjustment."],
            }
            print_final_report(report, budget)
            return report

        bookings = [{
            "venue_id": venue["venue_id"],
            "venue_name": venue["name"],
            "date": event_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "headcount": headcount,
            "equipment": equipment,
            "total_cost": result["total_cost"],
        }]
        connection.execute(
            "UPDATE outbox SET message_json = ? "
            "WHERE request_id = ? AND status = 'sent'",
            (
                json.dumps({
                    "type": "booking_confirmation",
                    "request_id": result["request_id"],
                    "message": notice,
                }),
                result["request_id"],
            ),
        )
        report = {
            "status": "committed",
            "bookings": bookings,
            "violations": [],
            "equipment_shortages": shortages,
            "attempts": attempts,
            "assumptions": assumptions,
            "human_decisions": [],
        }
        print_final_report(report, budget)
        return report

    report = {
        "status": "rejected",
        "bookings": [],
        "violations": ["all eligible venue attempts were rejected"],
        "equipment_shortages": shortages,
        "attempts": attempts,
        "assumptions": assumptions,
        "human_decisions": ["Choose another date, time, or a smaller headcount."],
    }
    print_final_report(report, budget)
    return report


def print_final_report(report: dict[str, Any], budget: int) -> None:
    total_cost = sum(booking["total_cost"] for booking in report["bookings"])
    report["total_cost"] = total_cost
    print("=== FINAL REPORT ===")
    if report["bookings"]:
        for booking in report["bookings"]:
            print(
                f"Booked {booking['venue_name']} ({booking['venue_id']}) on "
                f"{booking['date']} {booking['start_hour']}:00-"
                f"{booking['end_hour']}:00 for {booking['headcount']} people."
            )
    else:
        print("No booking was committed.")
    print(f"Total cost: {total_cost} vs budget {budget}.")
    print("Assumptions: " + ("; ".join(report["assumptions"]) or "none"))
    print(
        "Human decision: "
        + ("; ".join(report["human_decisions"]) or "none")
    )
    if report["violations"]:
        print("Violations: " + "; ".join(report["violations"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic event booking.")
    parser.add_argument("--event-type", default="dance")
    parser.add_argument("--headcount", type=int, default=150)
    parser.add_argument("--date", default="next Friday")
    parser.add_argument("--start-hour", type=int, default=18)
    parser.add_argument("--end-hour", type=int, default=20)
    parser.add_argument("--budget", type=int, default=20000)
    parser.add_argument("--organiser", default="Himanshu")
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args(argv)
    request = {
        "event_type": args.event_type,
        "headcount": args.headcount,
        "date": args.date,
        "start_hour": args.start_hour,
        "end_hour": args.end_hour,
        "budget": args.budget,
        "organiser": args.organiser,
    }
    result = run_pipeline(request, use_llm=args.use_llm)
    return 0 if result["status"] == "committed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
