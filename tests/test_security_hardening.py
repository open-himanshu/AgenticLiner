import logging
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from conftest import TEST_PASSWORDS

from backend.api.main import app


TEST_ACCOUNTS = {
    "supervisor": ("admin@galgotias.edu", TEST_PASSWORDS["SUPERVISOR_PASSWORD"]),
    "organiser": ("organiser@galgotias.edu", TEST_PASSWORDS["ORGANISER_PASSWORD"]),
    "data_manager": ("datamanager@galgotias.edu", TEST_PASSWORDS["DATA_MANAGER_PASSWORD"]),
    "participant": ("student@galgotias.edu", TEST_PASSWORDS["PARTICIPANT_PASSWORD"]),
}


def _login_as(role):
    client = TestClient(app)
    email, password = TEST_ACCOUNTS[role]
    response = client.post("/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


def _path_for_request(path):
    path = re.sub(r"\{[^}]+\}", "test-id", path)
    return path.replace(".csv", ".csv")


def _wrong_role_for_path(path):
    if path in {
        "/api/register",
        "/api/feedback/submit",
    } or path.startswith("/api/participant/"):
        return "organiser"
    if path == "/api/assistant/ask":
        return "data_manager"
    return "participant"


def _all_protected_api_operations():
    operations = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path == "/api/auth/firebase-login":
            continue
        for method in sorted(route.methods or ()):
            if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                operations.append((method, route.path))
    return operations


def test_every_protected_api_operation_rejects_anonymous_and_wrong_role():
    anonymous = TestClient(app)
    wrong_role_clients = {
        role: _login_as(role) for role in {"participant", "organiser", "data_manager"}
    }

    for method, route_path in _all_protected_api_operations():
        path = _path_for_request(route_path)
        params = {"reg_id": "test-registration"} if path == "/api/pass/scan" else None
        payload = {} if method in {"POST", "PUT", "PATCH"} else None

        anonymous_response = anonymous.request(
            method, path, params=params, json=payload
        )
        assert anonymous_response.status_code == 401, (method, route_path)

        wrong_role = _wrong_role_for_path(route_path)
        wrong_response = wrong_role_clients[wrong_role].request(
            method, path, params=params, json=payload
        )
        assert wrong_response.status_code == 403, (method, route_path, wrong_role)


def test_organiser_and_supervisor_can_use_operations_they_own():
    for role in ("organiser", "supervisor"):
        client = _login_as(role)
        assert client.get("/api/catalog").status_code == 200
        assert client.post("/api/schedule/solve", json={}).status_code == 200
        assert client.get("/api/outbox").status_code == 200


def test_participant_registration_is_bound_to_the_logged_in_account():
    client = _login_as("participant")
    response = client.post(
        "/api/register",
        json={
            "event_id": "ev_001",
            "name": "Forged Name",
            "email": "someone-else@example.invalid",
            "department": "Test Department",
            "year": 1,
            "interests": [],
        },
    )
    assert response.status_code == 403


def test_participant_feedback_cannot_be_submitted_for_another_student():
    client = _login_as("participant")
    response = client.post(
        "/api/feedback/submit",
        json={
            "event_id": "ev_001",
            "student_id": "stud_001",
            "rating": 5,
            "comment": "A useful session.",
        },
    )
    assert response.status_code == 403


def test_participant_can_register_and_submit_feedback_for_themselves():
    from backend.services.pass_service import get_or_create_student_profile

    client = _login_as("participant")
    email, _ = TEST_ACCOUNTS["participant"]
    profile = get_or_create_student_profile(email)

    registration = client.post(
        "/api/register",
        json={
            "event_id": "ev_001",
            "name": "Forged Name",
            "email": email,
            "department": "Test Department",
            "year": 1,
            "interests": ["AI"],
        },
    )
    assert registration.status_code == 200

    feedback = client.post(
        "/api/feedback/submit",
        json={
            "event_id": "ev_001",
            "student_id": profile["id"],
            "rating": 5,
            "comment": "A useful workshop.",
        },
    )
    assert feedback.status_code == 200
    assert feedback.json()["status"] == "saved"


def test_session_secret_uses_environment_or_random_value(monkeypatch, caplog):
    from backend.api import main

    monkeypatch.setenv("SECRET_KEY", "environment-test-session-secret")
    assert main.load_session_secret_key() == "environment-test-session-secret"

    monkeypatch.delenv("SECRET_KEY")
    monkeypatch.setattr(
        main.secrets, "token_urlsafe", lambda length: "generated-test-secret"
    )
    with caplog.at_level(logging.WARNING):
        assert main.load_session_secret_key() == "generated-test-secret"
    assert "random session secret" in caplog.text.lower()


def test_seeded_accounts_use_test_environment_passwords():
    from backend.services.auth_service import authenticate_user

    for role, (email, password) in TEST_ACCOUNTS.items():
        user, error = authenticate_user(email, password)
        assert error is None
        assert user["role"] == role


def test_public_tunnel_launcher_requires_explicit_opt_in(monkeypatch, capsys):
    import start_live_server

    monkeypatch.delenv("ALLOW_PUBLIC_TUNNEL", raising=False)
    monkeypatch.setattr(
        start_live_server.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("launcher started without opt-in"),
    )

    with pytest.raises(SystemExit) as exc:
        start_live_server.main()

    assert exc.value.code != 0
    assert "ALLOW_PUBLIC_TUNNEL=1" in capsys.readouterr().out
    monkeypatch.setenv("ALLOW_PUBLIC_TUNNEL", "1")
    login_page = TestClient(app).get("/login")
    assert "Demo account sign-in is disabled" in login_page.text


def test_batch_launcher_checks_public_tunnel_opt_in():
    launcher = Path(__file__).parents[1] / "start_public_app.bat"
    text = launcher.read_text(encoding="utf-8")
    assert 'if not "%ALLOW_PUBLIC_TUNNEL%"=="1"' in text
    assert "publicly accessible" in text.lower()


@pytest.mark.anyio
async def test_upload_rejects_svg_oversized_and_non_image_content(tmp_path, monkeypatch):
    from backend.services import inventory_service

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(inventory_service, "UPLOADS_DIR", upload_dir)

    async def upload(filename, content):
        import io

        return UploadFile(filename=filename, file=io.BytesIO(content))

    for filename, content, expected_status in [
        ("bad.svg", b"<svg></svg>", 400),
        ("large.png", b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024), 413),
        ("fake.png", b"not an image", 400),
    ]:
        with pytest.raises(HTTPException) as exc:
            await inventory_service.save_uploaded_photo(
                await upload(filename, content), "equipment"
            )
        assert exc.value.status_code == expected_status
    assert list(upload_dir.iterdir()) == []


@pytest.mark.anyio
async def test_upload_accepts_valid_png_content(tmp_path, monkeypatch):
    import base64
    import io

    from backend.services import inventory_service

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(inventory_service, "UPLOADS_DIR", upload_dir)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
        "W4kAAAAASUVORK5CYII="
    )
    uploaded = UploadFile(filename="pixel.png", file=io.BytesIO(png))

    image_url = await inventory_service.save_uploaded_photo(uploaded, "equipment")

    assert image_url.startswith("/static/uploads/equipment_")
    assert image_url.endswith(".png")
    saved_file = upload_dir / image_url.rsplit("/", 1)[-1]
    assert saved_file.read_bytes() == png


def test_upload_endpoint_preserves_size_limit_status(tmp_path, monkeypatch):
    client = _login_as("data_manager")
    large_image = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)
    response = client.post(
        "/api/inventory/venues",
        data={"name": "Upload Test Hall", "capacity": "20"},
        files={"photo": ("large.png", large_image, "image/png")},
    )
    assert response.status_code == 413


def test_only_login_and_certificate_verification_pages_are_public():
    client = TestClient(app)
    assert client.get("/login").status_code == 200
    assert client.get("/signup").status_code == 200
    assert client.get("/verify/invalid-certificate").status_code == 404
    assert client.get("/flyer/missing-event").status_code == 401


def test_readme_does_not_document_seed_passwords():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    for password in (
        "Admin@123",
        "Organiser@123",
        "Data@123",
        "Student@123",
    ):
        assert password not in readme


def test_google_login_rejects_unverified_email_claims():
    response = TestClient(app).post(
        "/api/auth/firebase-login",
        json={"email": "claimed@example.invalid", "name": "Claimed User"},
    )
    assert response.status_code == 401


def test_demo_google_login_is_disabled_for_public_tunnel(monkeypatch):
    monkeypatch.setenv("ALLOW_PUBLIC_TUNNEL", "1")
    response = TestClient(app).post(
        "/api/auth/firebase-login",
        json={
            "demo_google": True,
            "email": "admin@galgotias.edu",
            "name": "Pretend Supervisor",
            "role": "supervisor",
        },
    )
    assert response.status_code == 403


def test_google_signup_cannot_choose_an_privileged_role():
    from backend.services.auth_service import create_user_from_google

    user = create_user_from_google(
        email="new-user@example.invalid",
        full_name="New User",
        role="supervisor",
    )
    assert user["role"] == "participant"


def test_public_signup_cannot_create_a_privileged_role(monkeypatch):
    from backend.api import auth_routes
    from backend.core.database.connection import fetch_one
    import json

    monkeypatch.setattr(auth_routes, "is_smtp_configured", lambda: True)
    monkeypatch.setattr(auth_routes, "send_email_otp", lambda *args, **kwargs: (True, None))
    response = TestClient(app).post(
        "/signup",
        data={
            "full_name": "Test New User",
            "email": "new-signup@example.invalid",
            "password": "StrongTestPass@123",
            "confirm_password": "StrongTestPass@123",
            "role": "supervisor",
            "department": "Test",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    otp = fetch_one(
        "SELECT payload_json FROM otp_verifications WHERE email = ? AND purpose = 'signup'",
        ("new-signup@example.invalid",),
    )
    assert json.loads(otp["payload_json"])["role"] == "participant"


def test_pass_scanner_requires_an_organiser_or_supervisor():
    supervisor = _login_as("supervisor")
    assert supervisor.get(
        "/api/pass/scan", params={"reg_id": "missing-registration"}
    ).status_code == 404

    participant = _login_as("participant")
    assert participant.get(
        "/api/pass/scan", params={"reg_id": "missing-registration"}
    ).status_code == 403


def test_missing_seed_passwords_generate_credentials_once(monkeypatch, capsys):
    from backend.services import seed_users as seed_users_module

    for account in seed_users_module.SEEDED_ACCOUNTS:
        monkeypatch.delenv(account["password_env"], raising=False)
    seed_users_module._GENERATED_PASSWORDS.clear()
    seed_users_module._PRINTED_CREDENTIALS.clear()
    generated = iter(f"generated-{index}" for index in range(4))
    monkeypatch.setattr(
        seed_users_module.secrets, "token_urlsafe", lambda length: next(generated)
    )

    seed_users_module.seed_users(force=True)
    first_output = capsys.readouterr().out
    seed_users_module.seed_users(force=True)
    second_output = capsys.readouterr().out

    assert first_output.count("Generated seed password") == 4
    assert second_output.count("Generated seed password") == 0
