import importlib
import os
from pathlib import Path
import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_dev_env_and_app(monkeypatch):
    """Ensure clean environment and reset main app after each test."""
    monkeypatch.delenv("TEST_CONSOLE", raising=False)
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)
    yield
    monkeypatch.delenv("TEST_CONSOLE", raising=False)
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)
    import backend.api.main
    importlib.reload(backend.api.main)


def _load_fresh_app():
    import backend.api.main
    reloaded = importlib.reload(backend.api.main)
    return reloaded.app


def test_dev_gate_unmounted_when_flag_unset():
    """When TEST_CONSOLE is unset at startup, /dev routes do not exist (404)."""
    app = _load_fresh_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.get("/dev/ping")
    assert response.status_code == 404


def test_dev_gate_accessible_on_localhost(monkeypatch, capsys):
    """When TEST_CONSOLE=1 at startup and request is loopback, GET /dev/ping returns 200."""
    monkeypatch.setenv("TEST_CONSOLE", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)

    app = _load_fresh_app()
    captured = capsys.readouterr()
    assert "TEST CONSOLE ENABLED: localhost only, never use for demo or submission" in captured.out

    # Test loopback IPv4
    client_ipv4 = TestClient(app, client=("127.0.0.1", 50000))
    res_ipv4 = client_ipv4.get("/dev/ping")
    assert res_ipv4.status_code == 200
    assert res_ipv4.json() == {"status": "ok", "mode": "test_console"}

    # Test loopback IPv6
    client_ipv6 = TestClient(app, client=("::1", 50000))
    res_ipv6 = client_ipv6.get("/dev/ping")
    assert res_ipv6.status_code == 200
    assert res_ipv6.json() == {"status": "ok", "mode": "test_console"}

    # Test standard testclient host
    client_default = TestClient(app, client=("testclient", 50000))
    res_default = client_default.get("/dev/ping")
    assert res_default.status_code == 200
    assert res_default.json() == {"status": "ok", "mode": "test_console"}


def test_dev_gate_blocks_non_local_host(monkeypatch):
    """When request.client.host is not local, /dev routes return plain 404 (never 403)."""
    monkeypatch.setenv("TEST_CONSOLE", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)

    app = _load_fresh_app()

    # External IPv4
    client_external = TestClient(app, client=("192.168.1.100", 50000))
    res_ext = client_external.get("/dev/ping")
    assert res_ext.status_code == 404
    assert res_ext.status_code != 403

    # External IPv6
    client_ext_v6 = TestClient(app, client=("2001:db8::1", 50000))
    res_ext_v6 = client_ext_v6.get("/dev/ping")
    assert res_ext_v6.status_code == 404
    assert res_ext_v6.status_code != 403


def test_dev_gate_blocks_when_tunnel_enabled(monkeypatch):
    """When ALLOW_PUBLIC_TUNNEL=1, all /dev routes return plain 404 (never 403)."""
    monkeypatch.setenv("TEST_CONSOLE", "1")
    monkeypatch.setenv("ALLOW_PUBLIC_TUNNEL", "1")

    app = _load_fresh_app()
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.get("/dev/ping")
    assert res.status_code == 404
    assert res.status_code != 403


def test_dev_gate_blocks_when_flag_disabled_at_request_time(monkeypatch):
    """If TEST_CONSOLE is modified to != '1' after startup, requests return 404."""
    monkeypatch.setenv("TEST_CONSOLE", "1")
    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)

    app = _load_fresh_app()
    client = TestClient(app, client=("127.0.0.1", 50000))

    # Sanity check: works when TEST_CONSOLE is 1
    assert client.get("/dev/ping").status_code == 200

    # Flip to disabled at request time
    monkeypatch.setenv("TEST_CONSOLE", "0")
    res = client.get("/dev/ping")
    assert res.status_code == 404
    assert res.status_code != 403


def test_env_example_has_commented_test_console_guard():
    """Fails if .env.example has an uncommented TEST_CONSOLE line, and ensures comment documentation exists."""
    env_example_path = Path(__file__).resolve().parent.parent / ".env.example"
    assert env_example_path.exists(), ".env.example does not exist"

    text = env_example_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Must contain the commented documentation line
    assert any("# TEST_CONSOLE=1  (local testing only, remove before demo or submission)" in line for line in lines), (
        "Expected commented '# TEST_CONSOLE=1  (local testing only, remove before demo or submission)' in .env.example"
    )
    assert any("# TEST_ADMIN_USER=" in line for line in lines), (
        "Expected commented '# TEST_ADMIN_USER=' in .env.example"
    )
    assert any("# TEST_ADMIN_PASSWORD=" in line for line in lines), (
        "Expected commented '# TEST_ADMIN_PASSWORD=' in .env.example"
    )

    # Must fail if any uncommented TEST_CONSOLE line exists
    uncommented = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#") and "TEST_CONSOLE" in line
    ]
    assert not uncommented, f"Found uncommented TEST_CONSOLE setting in .env.example: {uncommented}"


def test_validator_fails_if_env_example_has_uncommented_test_console():
    """Explicitly verifies the validator logic catches uncommented TEST_CONSOLE."""
    sample_content = "ALLOW_PUBLIC_TUNNEL=0\nTEST_CONSOLE=1\n"
    lines = sample_content.splitlines()
    uncommented = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#") and line.strip().startswith("TEST_CONSOLE=")
    ]
    assert len(uncommented) > 0, "Validator failed to flag uncommented TEST_CONSOLE"


def test_with_test_console_unset_no_route_starts_with_dev(monkeypatch):
    """With TEST_CONSOLE unset, no route in app.routes starts with /dev."""
    monkeypatch.delenv("TEST_CONSOLE", raising=False)
    app = _load_fresh_app()
    dev_routes = [
        r.path for r in app.routes
        if hasattr(r, "path") and r.path.startswith("/dev")
    ]
    assert dev_routes == [], f"Expected zero /dev routes in app.routes when TEST_CONSOLE unset, found: {dev_routes}"

