"""
Offline configuration, placeholder-key, and rollback-notification tests.
Covers:
1. A copy of .env.example runs core app endpoints offline with zero network calls.
2. Placeholder keys (e.g. 'your_gemini_api_key_here') count as unset and make zero calls.
3. Rolled-back Kavach requisitions insert zero notification rows into outbox.
"""

from pathlib import Path
from types import SimpleNamespace
import urllib.request

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.api.main import app
from backend.core.database.connection import fetch_all, fetch_one
from backend.core.planner import agent as fixed_agent
from backend.core.planner import call_llm
from backend.core.planner.tools import tool_requisition_campus_resources
from conftest import TEST_PASSWORDS


_LLM_ENV_KEYS = (
    "PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "OLLAMA_MODEL",
    "OLLAMA_HOST",
    "SEND_REAL_SMTP",
    "SMTP_USER",
    "SMTP_PASSWORD",
)


def _block_network_calls(monkeypatch):
    """Patch HTTP/SDK transports and return a call log enforcing zero outbound calls."""
    calls = []

    def fail_urlopen(*args, **kwargs):
        calls.append(("urllib.request.urlopen", args, kwargs))
        raise AssertionError(f"Unexpected network call via urllib.request.urlopen: {args[:1]}")

    class BlockedGenAIClient:
        def __init__(self, *args, **kwargs):
            calls.append(("google.genai.Client", args, kwargs))
            raise AssertionError("Unexpected Google GenAI network client initialization")

    def fail_httpx_sync(self, request):
        calls.append(("httpx.HTTPTransport", str(request.url)))
        raise AssertionError(f"Unexpected outbound HTTP call via httpx: {request.url}")

    async def fail_httpx_async(self, request):
        calls.append(("httpx.AsyncHTTPTransport", str(request.url)))
        raise AssertionError(f"Unexpected outbound async HTTP call via httpx: {request.url}")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail_httpx_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fail_httpx_async)
    try:
        import google.genai as genai

        monkeypatch.setattr(genai, "Client", BlockedGenAIClient)
    except ImportError:
        pass
    return calls


def _load_env_example(monkeypatch) -> dict:
    """Clear active LLM/SMTP env vars and apply values parsed from .env.example."""
    for key in _LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    env_path = Path(".env.example")
    assert env_path.exists(), ".env.example must exist at repository root"
    parsed = {k: (v or "") for k, v in dotenv_values(env_path).items()}
    for key, val in parsed.items():
        if key not in {"DATABASE_PATH", "DATABASE_URL", "TEST_CONSOLE", "ALLOW_DEMO_LOGIN"}:
            monkeypatch.setenv(key, val)
    return parsed


def _logged_in_client(email: str, password_key: str) -> TestClient:
    client = TestClient(app)
    resp = client.post(
        "/login",
        json={"email": email, "password": TEST_PASSWORDS[password_key]},
    )
    assert resp.status_code == 200
    return client


def test_env_example_copy_runs_offline_with_zero_network_calls(monkeypatch):
    """A copied .env.example configuration must run offline with zero outbound HTTP/SDK calls."""
    _load_env_example(monkeypatch)
    network_calls = _block_network_calls(monkeypatch)

    organiser = _logged_in_client("organiser@galgotias.edu", "ORGANISER_PASSWORD")
    r_run = organiser.post(
        "/api/autopilot/run",
        json={
            "prompt": "Organize an AI workshop for 60 students with mics.",
            "date": "2026-11-28",
        },
    )
    assert r_run.status_code == 200
    assert r_run.json()["mode"] in {"fixed", "fixed_fallback"}

    r_sess = organiser.post(
        "/api/autopilot/session/start",
        json={"prompt": "Organize a robotics seminar", "target_date": "2026-11-28"},
    )
    assert r_sess.status_code == 200

    r_gen = organiser.post(
        "/api/agent/genesis",
        json={"prompt": "Organize a coding bootcamp for 60 students"},
    )
    assert r_gen.status_code == 200

    participant = _logged_in_client("student@galgotias.edu", "PARTICIPANT_PASSWORD")
    r_qa = participant.post(
        "/api/assistant/ask",
        json={"event_id": "ev_001", "query": "Where is the venue?"},
    )
    assert r_qa.status_code == 200
    assert r_qa.json()["mode"] == "rules_fallback"
    assert network_calls == []


@pytest.mark.parametrize(
    "provider,key_env,placeholder",
    [
        ("gemini", "GEMINI_API_KEY", "your_gemini_api_key_here"),
        ("gemini", "GEMINI_API_KEY", "  YOUR_GEMINI_API_KEY_HERE "),
        ("groq", "GROQ_API_KEY", "your_groq_api_key_here"),
    ],
)
def test_placeholder_api_key_counts_as_unset_and_makes_no_network_calls(
    monkeypatch, provider, key_env, placeholder
):
    """Placeholder API keys must be treated as unset without calling provider HTTP/SDK layers."""
    for key in _LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PROVIDER", provider)
    monkeypatch.setenv(key_env, placeholder)
    if provider == "groq":
        monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    network_calls = _block_network_calls(monkeypatch)

    with pytest.raises(call_llm.ProviderError):
        call_llm.get_provider_config()

    organiser = _logged_in_client("organiser@galgotias.edu", "ORGANISER_PASSWORD")
    r_run = organiser.post(
        "/api/autopilot/run",
        json={"prompt": "Organize an AI workshop for 60 students", "date": "2026-11-28"},
    )
    assert r_run.status_code == 200
    assert r_run.json()["mode"] == "fixed_fallback"

    participant = _logged_in_client("student@galgotias.edu", "PARTICIPANT_PASSWORD")
    r_qa = participant.post(
        "/api/assistant/ask",
        json={"event_id": "ev_001", "query": "Where is the venue?"},
    )
    assert r_qa.status_code == 200
    assert r_qa.json()["mode"] == "rules_fallback"
    assert network_calls == []


def test_rolled_back_requisition_inserts_zero_notification_rows():
    """Rolling back a Kavach requisition or draft confirm must leave zero outbox rows for that event."""
    before_count = fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"]

    # 1. Direct tool requisition rollback due to capacity overrun
    event_id = "ev_rb_test_01"
    res = tool_requisition_campus_resources(
        event_id=event_id,
        room_id="room_comp_lab",
        attendance=999,
        items_json="[]",
        date="2026-11-28",
        start_time="09:00:00",
        end_time="17:00:00",
        budget=100000.0,
        event_details={
            "name": "Oversized Rollback Test",
            "brief": "Exceeds room capacity",
            "event_type": "workshop",
            "expected_participants": 999,
        },
    )
    assert res["status"] == "rolled_back"
    assert fetch_all("SELECT * FROM outbox WHERE event_id = ?", (event_id,)) == []
    assert fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"] == before_count

    # 2. Fixed pipeline rollback leaves outbox unchanged and skips step 5 dispatch
    before_fixed = fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"]
    fixed_res = fixed_agent.AutopilotAgent().run_autopilot(
        prompt="Organize a workshop for 80 students",
        date="2026-11-29",
        budget=-1.0,
    )
    assert fixed_res["success"] is False
    assert [step["tool"] for step in fixed_res["timeline"]][-1] == "requisition_campus_resources"
    assert fixed_res["timeline"][-1]["status"] == "rolled_back"
    assert fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"] == before_fixed

    # 3. Confirm endpoint (/api/autopilot/confirm) rollback inserts zero outbox notices
    organiser = _logged_in_client("organiser@galgotias.edu", "ORGANISER_PASSWORD")
    start_resp = organiser.post(
        "/api/autopilot/session/start",
        json={
            "prompt": "Organize a seminar for 900 students on 2026-12-01",
            "target_date": "2026-12-01",
        },
    )
    assert start_resp.status_code == 200
    sess_id = start_resp.json()["session_id"]

    draft_resp = organiser.post("/api/autopilot/draft", json={"session_id": sess_id})
    assert draft_resp.status_code == 200

    before_confirm = fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"]
    confirm_resp = organiser.post("/api/autopilot/confirm", json={"session_id": sess_id})
    assert confirm_resp.status_code == 400
    assert confirm_resp.json()["status"] == "rolled_back"
    assert fetch_one("SELECT COUNT(*) AS cnt FROM outbox")["cnt"] == before_confirm
