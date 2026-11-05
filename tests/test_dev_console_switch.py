import importlib
import pytest
from starlette.testclient import TestClient

from backend.core.database.connection import fetch_one
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


def test_switch_role_without_console_cookie_fails():
    """POST /dev/switch without console cookie returns 401 or redirects to /dev/login."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post("/dev/switch", data={"role": "supervisor"}, follow_redirects=False)
    assert res.status_code in (302, 303, 307, 401)


def test_switch_role_invalid_role_returns_400():
    """POST /dev/switch with an invalid role returns HTTP 400."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert "test_console" in client.cookies

    res = client.post("/dev/switch", data={"role": "invalid_super_role"})
    assert res.status_code == 400


def test_switch_to_supervisor_grants_supervisor_access():
    """Switching to supervisor logs in as seeded supervisor and allows /supervisor page (200)."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    switch_res = client.post("/dev/switch", data={"role": "supervisor"}, follow_redirects=False)
    assert switch_res.status_code in (200, 302, 303)

    # Supervisor dashboard must return 200
    page_res = client.get("/supervisor")
    assert page_res.status_code == 200


def test_switch_to_participant_matches_real_participant_rbac():
    """
    After switching to participant, an organiser-only page and an organiser /api
    route return the SAME status a real participant login gets today.
    """
    app = _load_app()

    # 1. Real participant login baseline
    real_client = TestClient(app, client=("127.0.0.1", 50000))
    login_res = real_client.post(
        "/login",
        data={
            "email": "student@galgotias.edu",
            "password": TEST_PASSWORDS["PARTICIPANT_PASSWORD"],
        },
    )
    assert login_res.status_code in (200, 302)

    real_page_status = real_client.get("/organiser", follow_redirects=False).status_code
    real_api_status = real_client.get("/api/outbox", headers={"accept": "application/json"}).status_code

    # 2. Console switch to participant
    dev_client = TestClient(app, client=("127.0.0.1", 50000))
    dev_client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    switch_res = dev_client.post("/dev/switch", data={"role": "participant"}, follow_redirects=False)
    assert switch_res.status_code in (200, 302, 303)

    dev_page_status = dev_client.get("/organiser", follow_redirects=False).status_code
    dev_api_status = dev_client.get("/api/outbox", headers={"accept": "application/json"}).status_code

    # Assert dev-switched user experiences exact same RBAC outcomes as real user
    assert dev_page_status == real_page_status
    assert dev_api_status == real_api_status


def test_switch_role_logs_exactly_one_audit_row():
    """Each role switch writes exactly one audit_log row with actor=test_console, action=role_switch, result=role."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    before_count = fetch_one("SELECT count(*) as count FROM audit_log WHERE action = 'role_switch'")["count"]

    res = client.post("/dev/switch", data={"role": "data_manager"}, follow_redirects=False)
    assert res.status_code in (200, 302, 303)

    after_count = fetch_one("SELECT count(*) as count FROM audit_log WHERE action = 'role_switch'")["count"]
    assert after_count == before_count + 1

    last_log = fetch_one("SELECT * FROM audit_log WHERE action = 'role_switch' ORDER BY timestamp DESC, rowid DESC LIMIT 1")
    assert last_log["actor"] == "test_console"
    assert last_log["action"] == "role_switch"
    assert last_log["result"] == "data_manager"


def test_normal_login_session_behaves_unchanged_without_test_console_claim():
    """Normal login establishes standard session without via_test_console claim."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    login_res = client.post(
        "/login",
        data={
            "email": "student@galgotias.edu",
            "password": TEST_PASSWORDS["PARTICIPANT_PASSWORD"],
        },
    )
    assert login_res.status_code in (200, 302)

    # Normal session operates as expected
    part_res = client.get("/participant")
    assert part_res.status_code == 200

    # Ensure no console cookie was set
    assert "test_console" not in client.cookies


def test_dev_exit_clears_normal_session_and_redirects_to_dev():
    """POST /dev/exit clears the active normal user session and redirects to /dev."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    # Switch to organiser
    client.post("/dev/switch", data={"role": "organiser"}, follow_redirects=False)
    assert client.get("/organiser").status_code == 200

    # Exit session
    exit_res = client.post("/dev/exit", follow_redirects=False)
    assert exit_res.status_code in (302, 303, 307)
    assert exit_res.headers["location"] == "/dev"

    # Organiser route should no longer be accessible
    after_res = client.get("/organiser", follow_redirects=False)
    assert after_res.status_code in (302, 307, 401, 403)

    # /dev is still accessible because test_console cookie persists
    dev_res = client.get("/dev")
    assert dev_res.status_code == 200
