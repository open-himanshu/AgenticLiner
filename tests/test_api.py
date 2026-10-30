from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, get_checkout_connection, seed_checkout_data
from backend.safety.checkout import initialize_database


@pytest.fixture
def client():
    connection = sqlite3.connect(
        ":memory:",
        isolation_level=None,
        check_same_thread=False,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    seed_checkout_data(connection)

    def override_connection():
        yield connection

    app.dependency_overrides[get_checkout_connection] = override_connection
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        connection.close()


def test_get_catalog_returns_mock_catalog(client):
    catalog_path = Path(__file__).resolve().parents[1] / "docs" / "mock" / "catalog.json"
    expected = json.loads(catalog_path.read_text(encoding="utf-8"))

    response = client.get("/catalog")

    assert response.status_code == 200
    assert response.json() == expected


def test_checkout_commits_and_matches_api_contract(client):
    request = {
        "venue_id": "STG-C",
        "date": (date.today() + timedelta(days=1)).isoformat(),
        "start_hour": 18,
        "end_hour": 20,
        "headcount": 150,
        "equipment": {
            "stage lights": 4,
            "sound system": 1,
            "wireless mic": 2,
        },
        "budget": 20000,
    }

    response = client.post("/checkout", json=request)

    assert response.status_code == 201
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["status"] == "committed"
    assert body["booking"] == {
        "venue_id": "STG-C",
        "venue_name": "Open Stage C",
        "date": request["date"],
        "start_hour": 18,
        "end_hour": 20,
        "headcount": 150,
        "equipment": request["equipment"],
        "total_cost": 6300,
    }
    assert body["budget_remaining"] == 13700


def test_checkout_returns_conflict_for_invalid_booking(client):
    request = {
        "venue_id": "STG-C",
        "date": (date.today() + timedelta(days=1)).isoformat(),
        "start_hour": 18,
        "end_hour": 20,
        "headcount": 150,
        "equipment": {"stage lights": 9},
        "budget": 20000,
    }

    response = client.post("/checkout", json=request)

    assert response.status_code == 409
    assert response.json()["status"] == "rolled_back"
    assert response.json()["committed"] is False
    assert any("in stock" in item for item in response.json()["violations"])


def test_post_brief_returns_fixed_mock_plan(client):
    response = client.post(
        "/brief",
        json={
            "event_type": "dance",
            "date": "2026-11-06",
            "start_hour": 18,
            "end_hour": 20,
            "headcount": 150,
            "budget": 20000,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["estimated_total"] == 6300
    assert response.json()["suggested_venue"]["id"] == "STG-C"


def test_cors_allows_local_frontend(client):
    response = client.options(
        "/checkout",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"