"""
Integration tests for FastAPI application endpoints using modern httpx ASGI transport.
"""
import pytest
import httpx
from conftest import TEST_PASSWORDS
from backend.api.main import app
from backend.core.database.demo_people import HERO_SPEAKER
from backend.services.pass_service import get_or_create_student_profile

@pytest.mark.anyio
async def test_page_routes():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        # First verify login page is available
        login_resp = await ac.get("/login")
        assert login_resp.status_code == 200
        assert "Sign In" in login_resp.text

        # Authenticate as supervisor to test protected pages
        auth_resp = await ac.post("/login", data={"email": "admin@galgotias.edu", "password": TEST_PASSWORDS["SUPERVISOR_PASSWORD"]})
        assert auth_resp.status_code in (200, 302)

        response = await ac.get("/autopilot")
        assert response.status_code == 200
        assert "Autopilot" in response.text

        response = await ac.get("/schedule")
        assert response.status_code == 200
        assert "OR-Tools" in response.text

        response = await ac.get("/analytics")
        assert response.status_code == 200

@pytest.mark.anyio
async def test_api_catalog():
    from backend.core.database.connection import execute_query
    execute_query("INSERT OR IGNORE INTO resources (id, category, name, stock) VALUES ('res_test', 'equipment', 'Mic Set', 10)")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        response = await ac.get("/api/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "catalog" in data
        assert len(data["catalog"]) > 0

@pytest.mark.anyio
async def test_api_schedule_solver():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        response = await ac.post("/api/schedule/solve", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["schedule"]) > 0

@pytest.mark.anyio
async def test_hero_speaker_cancellation():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        response = await ac.post("/api/schedule/hero-speaker-cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "re_planned"
        assert data["substitute_allocated"] == (
            f"{HERO_SPEAKER['substitute_name']} "
            f"({HERO_SPEAKER['substitute_department']})"
        )
        assert len(data["new_schedule"]) > 0

@pytest.mark.anyio
async def test_api_feedback_submission():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/login",
            data={
                "email": "student@galgotias.edu",
                "password": TEST_PASSWORDS["PARTICIPANT_PASSWORD"],
            },
        )
        student = get_or_create_student_profile("student@galgotias.edu")
        response = await ac.post("/api/feedback/submit", json={
            "event_id": "ev_001",
            "student_id": student["id"],
            "rating": 5,
            "comment": "The hands-on coding session was outstanding and very insightful!"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "saved"
        assert data["analysis"]["sentiment"] == "positive"
        assert "content" in data["themes"]
