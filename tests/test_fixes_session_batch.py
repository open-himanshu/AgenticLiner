import pytest
from starlette.testclient import TestClient

from backend.api.main import app
from backend.core.database.connection import fetch_one, fetch_all


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_LOGIN", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)


def test_data_manager_can_access_planner_page():
    """Bug 1: data_manager role must be authorized to access /organiser/planner without 403."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    # Log in as data manager
    login_res = client.post(
        "/api/auth/firebase-login",
        json={
            "demo_google": True,
            "email": "datamanager@galgotias.edu",
            "name": "Campus Data Manager",
            "role": "data_manager",
        },
    )
    assert login_res.status_code == 200

    # Access planner page
    res = client.get("/organiser/planner")
    assert res.status_code == 200
    assert "planner" in res.text.lower() or "inventory" in res.text.lower()


def test_autopilot_session_start_without_budget():
    """Bug 2: Event session start succeeds without specifying budget."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    # Log in as organiser
    client.post(
        "/api/auth/firebase-login",
        json={
            "demo_google": True,
            "email": "organiser@galgotias.edu",
            "name": "Organiser",
            "role": "organiser",
        },
    )

    res = client.post(
        "/api/autopilot/session/start",
        json={
            "prompt": "Organize an AI workshop for 60 students on 28 Nov",
            "target_date": "2026-11-28",
            # No budget_limit passed
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"]
    assert data["is_safe"] is True


def test_reseed_campus_data_endpoint():
    """Bug 4: Admin endpoint restores full campus datasets."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post(
        "/api/auth/firebase-login",
        json={
            "demo_google": True,
            "email": "datamanager@galgotias.edu",
            "name": "Data Manager",
            "role": "data_manager",
        },
    )

    res = client.post("/api/admin/reseed-campus-data")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["counts"]["rooms"] >= 5
    assert data["counts"]["resources"] >= 10
    assert data["counts"]["speakers"] >= 4
