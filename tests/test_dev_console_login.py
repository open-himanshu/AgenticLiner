import importlib
import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_dev_env_and_app(monkeypatch):
    """Ensure clean environment, reset rate limits, and reset main app after each test."""
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


def test_dev_login_form_renders():
    """GET /dev/login renders the test console login form."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.get("/dev/login")
    assert res.status_code == 200
    assert "form" in res.text.lower()
    assert "password" in res.text.lower()


def test_dev_login_wrong_password_returns_401():
    """Wrong credentials return 401 with a plain message and no cookie."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post("/dev/login", data={"username": "admin", "password": "wrongpassword"})
    assert res.status_code == 401
    assert "test_console" not in client.cookies


def test_dev_login_correct_password_sets_cookie():
    """Correct credentials set the signed test_console cookie."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert res.status_code in (200, 302, 303)
    assert "test_console" in client.cookies
    cookie_val = client.cookies.get("test_console")
    assert cookie_val and len(cookie_val) > 10


def test_dev_login_admin_email_also_accepted():
    """Admin email 'admin@galgotias.edu' is also accepted as username for convenience."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post("/dev/login", data={"username": "admin@galgotias.edu", "password": "admin"}, follow_redirects=False)
    assert res.status_code in (200, 302, 303)
    assert "test_console" in client.cookies


def test_dev_login_html_error_rendering():
    """Wrong credentials from browser renders login page with 401 status and error alert."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.post("/dev/login", data={"username": "admin", "password": "wrongpassword"}, headers={"accept": "text/html"})
    assert res.status_code == 401
    assert "Invalid test admin credentials" in res.text
    assert "form" in res.text.lower()


def test_dev_placeholder_without_cookie_redirects_to_login():
    """GET /dev without test_console cookie redirects to /dev/login."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.get("/dev", follow_redirects=False)
    assert res.status_code in (302, 303, 307)
    assert res.headers["location"] == "/dev/login"


def test_dev_placeholder_with_cookie_succeeds():
    """GET /dev with a valid signed test_console cookie returns 200 placeholder."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    login_res = client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert "test_console" in client.cookies

    res = client.get("/dev")
    assert res.status_code == 200
    assert "console" in res.text.lower()


def test_console_cookie_does_not_grant_access_to_normal_routes():
    """The console cookie must NOT grant access to normal app routes by itself."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    # Login to console to acquire test_console cookie
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert "test_console" in client.cookies

    # 1. Normal HTML organiser page must redirect or return 401/403
    page_res = client.get("/organiser", follow_redirects=False)
    assert page_res.status_code in (302, 307, 401, 403)

    # 2. Normal API organiser route must return 401/403
    api_res = client.get("/api/outbox", headers={"accept": "application/json"})
    assert api_res.status_code in (401, 403)


def test_dev_login_rate_limiting_lockout_on_5_wrong_attempts():
    """5 wrong attempts from one client triggers 429 for 60 seconds."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    # Send 4 failed attempts
    for _ in range(4):
        res = client.post("/dev/login", data={"username": "admin", "password": "bad"})
        assert res.status_code == 401

    # 5th attempt must trigger 429
    res5 = client.post("/dev/login", data={"username": "admin", "password": "bad"})
    assert res5.status_code == 429

    # 6th attempt within lockout must also be 429
    res6 = client.post("/dev/login", data={"username": "admin", "password": "bad"})
    assert res6.status_code == 429


def test_custom_admin_password_overrides_default(monkeypatch):
    """When TEST_ADMIN_PASSWORD is set, 'admin' no longer works."""
    monkeypatch.setenv("TEST_ADMIN_PASSWORD", "custom_secret_key_123")
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    # Default 'admin' password must fail
    res_default = client.post("/dev/login", data={"username": "admin", "password": "admin"})
    assert res_default.status_code == 401

    # Custom password must succeed
    res_custom = client.post("/dev/login", data={"username": "admin", "password": "custom_secret_key_123"}, follow_redirects=False)
    assert res_custom.status_code in (200, 302, 303)
    assert "test_console" in client.cookies


def test_dev_logout_clears_cookie():
    """POST /dev/logout clears the test_console cookie and revokes access."""
    app = _load_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    # Login
    client.post("/dev/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert client.get("/dev").status_code == 200

    # Logout
    logout_res = client.post("/dev/logout", follow_redirects=False)
    assert logout_res.status_code in (200, 302, 303)

    # Next attempt to view /dev must redirect
    res_after = client.get("/dev", follow_redirects=False)
    assert res_after.status_code in (302, 303, 307)
