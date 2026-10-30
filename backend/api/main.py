from __future__ import annotations

from collections.abc import Iterator
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.safety.checkout import checkout, connect_database


CATALOG_PATH = Path(__file__).resolve().parents[2] / "docs" / "mock" / "catalog.json"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
VENUE_CAPACITIES = {"AUD-A": 400, "SEM-B": 120, "STG-C": 300}

app = FastAPI(title="AgenticLiner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class BriefRequest(BaseModel):
    event_type: str
    date: str
    start_hour: int
    end_hour: int
    headcount: int
    budget: int
    description: str | None = None
    organiser: str | None = None
    requirements: list[str] = Field(default_factory=list)


def seed_checkout_data(connection: sqlite3.Connection) -> None:
    for item in CATALOG["items"]:
        if item["category"] == "venues":
            connection.execute(
                "INSERT OR IGNORE INTO venues "
                "(id, name, capacity, price_per_hour) VALUES (?, ?, ?, ?)",
                (
                    item["id"],
                    item["name"],
                    VENUE_CAPACITIES.get(item["id"], 500),
                    item["price"],
                ),
            )
        else:
            connection.execute(
                "INSERT OR IGNORE INTO equipment (name, price, stock) "
                "VALUES (?, ?, ?)",
                (item["name"], item["price"], item["stock"]),
            )


def get_checkout_connection() -> Iterator[sqlite3.Connection]:
    connection = connect_database()
    seed_checkout_data(connection)
    try:
        yield connection
    finally:
        connection.close()


@app.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return CATALOG


@app.post("/checkout")
def create_checkout(
    request: dict[str, Any],
    connection: sqlite3.Connection = Depends(get_checkout_connection),
) -> JSONResponse:
    payload = dict(request)
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = uuid.uuid4().hex
    payload["request_id"] = request_id

    venue = connection.execute(
        "SELECT name FROM venues WHERE id = ?", (payload.get("venue_id"),)
    ).fetchone()
    result = checkout(payload, connection)

    if result["status"] == "rolled_back":
        return JSONResponse(
            status_code=409,
            content={
                "api_version": "v1",
                "status": "rolled_back",
                "checkout_id": f"checkout_{uuid.uuid4().hex}",
                "committed": False,
                "violations": result["violations"],
                "suggestions": [
                    "Review the violations and adjust the booking request."
                ],
            },
        )

    return JSONResponse(
        status_code=201,
        content={
            "api_version": "v1",
            "status": "committed",
            "checkout_id": result["booking_id"],
            "booking": {
                "venue_id": payload["venue_id"],
                "venue_name": venue[0],
                "date": payload["date"],
                "start_hour": payload["start_hour"],
                "end_hour": payload["end_hour"],
                "headcount": payload["headcount"],
                "equipment": payload["equipment"],
                "total_cost": result["total_cost"],
            },
            "budget_remaining": payload["budget"] - result["total_cost"],
        },
    )


@app.post("/brief")
def create_brief(request: BriefRequest) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "brief_id": "brief_mock_01",
        "status": "ready",
        "event_type": request.event_type,
        "date": request.date,
        "start_hour": request.start_hour,
        "end_hour": request.end_hour,
        "headcount": request.headcount,
        "budget": request.budget,
        "suggested_venue": {
            "id": "STG-C",
            "name": "Open Stage C",
            "capacity": 300,
            "price_per_hour": 800,
        },
        "suggested_items": [
            {"id": "stage-lights", "name": "stage lights", "quantity": 4},
            {"id": "sound-system", "name": "sound system", "quantity": 1},
            {"id": "wireless-mic", "name": "wireless mic", "quantity": 2},
        ],
        "estimated_total": 6300,
        "questions": [],
    }