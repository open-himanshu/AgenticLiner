import pytest
import httpx
from starlette.testclient import TestClient

from backend.api.main import app


@pytest.fixture(autouse=True)
def enable_demo_login_env(monkeypatch):
    monkeypatch.setenv("ALLOW_DEMO_LOGIN", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)


@pytest.mark.parametrize(
    "email,name,role,expected_redirect",
    [
        ("casey@example.invalid", "Casey Example", "organiser", "/organiser"),
        ("dean.office@galgotias.edu", "University Dean (Admin)", "supervisor", "/supervisor"),
        ("datamanager@galgotias.edu", "Logistics Data Manager", "data_manager", "/data-manager"),
        ("student@galgotias.edu", "Galgotias Student", "participant", "/participant"),
    ],
)
def test_demo_google_login_role_and_redirect(email, name, role, expected_redirect):
    """Each demo account in Google sign-in modal must redirect to its own role dashboard."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post(
        "/api/auth/firebase-login",
        json={
            "demo_google": True,
            "email": email,
            "name": name,
            "role": role,
            "department": "School of AI",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["user"]["role"] == role
    assert data["redirect_url"] == expected_redirect

    # Verify session cookie was established and target dashboard returns 200 (not 403)
    dash_res = client.get(expected_redirect)
    assert dash_res.status_code == 200
