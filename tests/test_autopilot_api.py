from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner import agent as fixed_agent
from backend.core.planner import agent_mode
from conftest import TEST_PASSWORDS


def _organiser_client():
    client = TestClient(app)
    response = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert response.status_code == 200
    return client


def _fake_result(text, tool_calls=None):
    return {
        "text": text,
        "tool_calls": tool_calls or [],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        "provider": "scripted-test",
        "model": "scripted-model",
    }


def test_autopilot_api_returns_agent_result_metadata(monkeypatch):
    monkeypatch.setenv("PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "configured-model")
    monkeypatch.setitem(
        agent_mode.TOOL_DISPATCH,
        "check_equipment",
        lambda args: {"count": 0, "items": []},
    )
    responses = iter([
        _fake_result(
            "",
            [{"name": "check_equipment", "arguments": {}, "id": "call-1"}],
        ),
        _fake_result("Plan complete."),
    ])
    monkeypatch.setattr(agent_mode, "call_llm", lambda *args, **kwargs: next(responses))

    client = _organiser_client()
    response = client.post(
        "/api/autopilot/run",
        json={"prompt": "Plan a workshop", "budget": 12000},
    )
    page_response = client.get("/autopilot")

    assert response.status_code == 200
    assert page_response.status_code == 200
    assert 'id="agentBudget"' in page_response.text
    assert 'id="executionMetadata"' in page_response.text
    result = response.json()
    assert result["mode"] == "agent"
    assert result["provider"] == "scripted-test"
    assert result["model"] == "scripted-model"
    assert result["tokens_used"] == {
        "prompt_tokens": 14,
        "completion_tokens": 6,
        "total_tokens": 20,
    }
    assert [step["tool"] for step in result["timeline"]] == [
        "check_equipment",
        "llm_response",
    ]


def test_autopilot_api_falls_back_with_provider_failure_reason(monkeypatch):
    monkeypatch.setenv("PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "groq-test-model")

    def fail_provider(*args, **kwargs):
        raise agent_mode.ProviderError("scripted provider outage")

    def fixed_result(self, prompt, date, start_time, end_time, budget):
        assert budget == 9400
        return {
            "success": True,
            "event_id": "fixed-event",
            "timeline": [{"step": 1, "tool": "fixed_step", "status": "completed", "summary": "Done"}],
        }

    monkeypatch.setattr(agent_mode, "call_llm", fail_provider)
    monkeypatch.setattr(fixed_agent.AutopilotAgent, "run_autopilot", fixed_result)

    client = _organiser_client()
    response = client.post(
        "/agent/run",
        json={"prompt": "Plan a workshop", "budget": 9400},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "fixed_fallback"
    assert result["fallback_reason"] == "scripted provider outage"
    assert result["provider"] == "groq"
    assert result["model"] == "groq-test-model"
    assert result["tokens_used"]["total_tokens"] == 0
    assert result["timeline"][0]["tool"] == "fixed_step"


def test_autopilot_api_uses_fixed_pipeline_when_provider_unset(monkeypatch):
    monkeypatch.delenv("PROVIDER", raising=False)
    captured = {}

    def fixed_result(self, prompt, date, start_time, end_time, budget):
        captured["budget"] = budget
        return {
            "success": True,
            "event_id": "fixed-event",
            "timeline": [{"step": 1, "tool": "fixed_step", "status": "completed", "summary": "Done"}],
        }

    def should_not_call_llm(*args, **kwargs):
        raise AssertionError("The fixed mode must not call an LLM provider.")

    monkeypatch.setattr(fixed_agent.AutopilotAgent, "run_autopilot", fixed_result)
    monkeypatch.setattr(agent_mode, "call_llm", should_not_call_llm)

    client = _organiser_client()
    response = client.post(
        "/api/autopilot/run",
        json={"prompt": "Plan a workshop", "budget": 7300},
    )

    assert response.status_code == 200
    result = response.json()
    assert captured["budget"] == 7300
    assert result["mode"] == "fixed"
    assert result["provider"] == ""
    assert result["model"] == ""
    assert result["tokens_used"]["total_tokens"] == 0
    assert result["timeline"][0]["tool"] == "fixed_step"


def test_autopilot_api_blocks_requisition_over_request_budget(monkeypatch):
    monkeypatch.setenv("PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "configured-model")
    responses = iter([
        _fake_result(
            "",
            [{
                "name": "requisition",
                "arguments": {
                    "room_id": "unused-room",
                    "attendance": 20,
                    "items_json": "[]",
                    "date": "2026-12-10",
                    "start_time": "09:00:00",
                    "end_time": "17:00:00",
                    "budget": 501,
                    "event_name": "Over-budget workshop",
                    "event_type": "workshop",
                },
            }],
        ),
        _fake_result("The request exceeded the budget."),
    ])
    monkeypatch.setattr(agent_mode, "call_llm", lambda *args, **kwargs: next(responses))

    client = _organiser_client()
    response = client.post(
        "/agent/run",
        json={"prompt": "Plan a workshop", "budget": 500},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["timeline"][0]["status"] == "rolled_back"
    assert "exceeds allowed budget 500" in result["timeline"][0]["summary"]


def test_autopilot_api_keeps_role_check():
    client = TestClient(app)
    login = client.post(
        "/login",
        json={
            "email": "student@galgotias.edu",
            "password": TEST_PASSWORDS["PARTICIPANT_PASSWORD"],
        },
    )
    assert login.status_code == 200

    response = client.post(
        "/agent/run",
        json={"prompt": "Plan a workshop", "budget": 5000},
    )

    assert response.status_code == 403
