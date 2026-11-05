import importlib
import re
import pytest
from starlette.testclient import TestClient

from conftest import TEST_PASSWORDS


@pytest.fixture(autouse=True)
def clean_dev_env_and_app(monkeypatch):
    """Ensure clean environment, reset rate limits, and reload fresh app."""
    monkeypatch.setenv("TEST_CONSOLE", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)
    monkeypatch.delenv("TEST_ADMIN_USER", raising=False)
    monkeypatch.delenv("TEST_ADMIN_PASSWORD", raising=False)

    try:
        from backend.dev.test_console import reset_rate_limits
        reset_rate_limits()
    except (ImportError, AttributeError):
        pass

    yield

    monkeypatch.delenv("TEST_CONSOLE", raising=False)
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)
    monkeypatch.delenv("TEST_ADMIN_USER", raising=False)
    monkeypatch.delenv("TEST_ADMIN_PASSWORD", raising=False)

    try:
        from backend.dev.test_console import reset_rate_limits
        reset_rate_limits()
    except (ImportError, AttributeError):
        pass

    import backend.api.main
    importlib.reload(backend.api.main)


def _load_app():
    import backend.api.main
    reloaded = importlib.reload(backend.api.main)
    return reloaded.app


def test_bar_present_for_switched_session():
    """Floating bar is present when user has switched role via test console."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    # Dev login & switch to supervisor
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    switch_res = client.post("/dev/switch", data={"role": "supervisor"}, follow_redirects=False)
    assert switch_res.status_code in (200, 302, 303)

    # Request supervisor page which extends base.html
    res = client.get("/supervisor")
    assert res.status_code == 200

    html = res.text
    assert "TEST MODE" in html
    assert "supervisor" in html.lower()
    assert "/dev" in html  # Link to Console
    assert "/dev/switch" in html  # Switch buttons


def test_bar_absent_for_normal_login():
    """Floating bar must never render for a normal user login."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    login_res = client.post(
        "/login",
        data={
            "email": "admin@galgotias.edu",
            "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"],
        },
        follow_redirects=False
    )
    assert login_res.status_code in (200, 302)

    res = client.get("/supervisor")
    assert res.status_code == 200

    html = res.text
    assert "TEST MODE" not in html
    assert "/dev/switch" not in html


def test_bar_absent_when_test_console_is_off(monkeypatch):
    """Floating bar must never render when TEST_CONSOLE is not '1' even if session has flag."""
    # 1. First switch role with TEST_CONSOLE=1
    monkeypatch.setenv("TEST_CONSOLE", "1")
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    client.post("/dev/switch", data={"role": "supervisor"}, follow_redirects=False)

    # 2. Turn off TEST_CONSOLE at request time
    monkeypatch.setenv("TEST_CONSOLE", "0")
    res = client.get("/supervisor")
    assert res.status_code == 200
    assert "TEST MODE" not in res.text


def test_dev_page_renders_role_buttons_and_logout():
    """GET /dev renders current role (or none), 4 switch buttons, and logout button."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    res = client.get("/dev")
    assert res.status_code == 200
    html = res.text

    assert "none" in html.lower() or "current role" in html.lower()
    assert "/dev/logout" in html
    assert "/dev/switch" in html
    for role in ["organiser", "supervisor", "data_manager", "participant"]:
        assert role in html.lower()


def test_every_link_on_dev_returns_neither_404_nor_500_as_matching_role():
    """Every link on /dev returns neither 404 nor 500 when requested as its matching role."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    dev_res = client.get("/dev")
    assert dev_res.status_code == 200

    page_hrefs = re.findall(r'href=["\']([^"\']+)["\']', dev_res.text)

    # Links mapped to their required roles
    expected_links = {
        "/autopilot": "organiser",
        "/organiser/planner": "organiser",
        "/schedule": "organiser",
        "/attendees": "organiser",
        "/outbox": "organiser",
        "/analytics": "supervisor",
        "/data-manager": "data_manager",
        "/participant": "participant",
        "/verify": "participant",
    }

    # Verify that links exist on /dev page
    for path in expected_links:
        # Check either exact path or path with query params
        matching = [h for h in page_hrefs if h == path or h.startswith(path + "?") or h.startswith(path + "/")]
        assert matching, f"Expected link to {path} not found on /dev page"

    # Test each link with its matching role
    for path, role in expected_links.items():
        switch_res = client.post("/dev/switch", data={"role": role}, follow_redirects=False)
        assert switch_res.status_code in (200, 302, 303)

        res = client.get(path, follow_redirects=True)
        assert res.status_code not in (404, 500), f"Route {path} returned {res.status_code} for role {role}"
