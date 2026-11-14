import os
import re
import pytest
import httpx
from conftest import TEST_PASSWORDS
from backend.api.main import app

pytestmark = pytest.mark.anyio


async def test_no_budget_in_rendered_autopilot_planner_and_organiser_pages():
    """Verify that rendered autopilot, planner, and organiser pages contain no budget input,
    label, placeholder, or visible word 'budget'.
    Also verify rendered pages contain none of: "Diya's Module", "Guarantees", "Screen #".
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as organiser
        login_res = await client.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        assert login_res.status_code == 302

        for endpoint in [
            "/autopilot",
            "/organiser/planner",
            "/organiser",
            "/attendees",
            "/notices",
        ]:
            res = await client.get(endpoint)
            assert res.status_code == 200, f"Failed to fetch {endpoint}"
            html = res.text

            # Assert no budget input element or id
            assert 'id="agentbudget"' not in html.lower(), f"Found agentBudget id in {endpoint}"
            assert 'name="budget"' not in html.lower(), f"Found budget name in {endpoint}"

            # Assert no visible 'budget' word in rendered HTML
            assert "budget" not in html.lower(), f"Found 'budget' in rendered HTML of {endpoint}"

            # Assert rendered pages contain none of: "Diya's Module", "Guarantees", "Screen #"
            assert "Diya's Module" not in html, f"Found \"Diya's Module\" in {endpoint}"
            assert "Guarantees" not in html, f"Found 'Guarantees' in {endpoint}"
            assert "Screen #" not in html, f"Found 'Screen #' in {endpoint}"


def test_no_budget_in_readme_and_user_docs():
    """Verify README.md, docs/user_manual.md, and docs/slides_outline.md contain no 'budget'."""
    files_to_check = [
        "README.md",
        os.path.join("docs", "user_manual.md"),
        os.path.join("docs", "slides_outline.md"),
    ]
    for file_path in files_to_check:
        assert os.path.exists(file_path), f"File {file_path} does not exist"
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        matches = re.findall(r"budget", content, re.IGNORECASE)
        assert len(matches) == 0, f"Found {len(matches)} occurrences of 'budget' in {file_path}"


async def test_autopilot_run_without_budget_field_succeeds(monkeypatch):
    """POST /api/autopilot/run without a budget field still succeeds on a seeded DB in fixed mode."""
    monkeypatch.setenv("PROVIDER", "none")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as organiser
        login_res = await client.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        assert login_res.status_code == 302

        # Send run request omitting the budget key entirely
        payload = {
            "prompt": "Dance performance, 150 students, next Friday 6 PM",
            "date": "2026-11-28",
        }
        res = await client.post("/api/autopilot/run", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        assert data.get("mode") in ("fixed", "agent", "fixed_fallback")
