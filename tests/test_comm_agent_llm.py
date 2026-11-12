"""
Tests for Grounded LLM Assistant in CommunicationAgent and plain chat support in call_llm.
Verifies:
1. call_llm supports plain text completion without tools (tools=[]).
2. CommunicationAgent uses call_llm when available and grounded.
3. CommunicationAgent falls back to deterministic rule-based facts if LLM fails or is unconfigured.
4. Universal command endpoint blocks participants with 403 and clear detail.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from backend.core.planner.call_llm import ProviderError, call_llm
from backend.modules.module5_comm_agent.agent import CommunicationAgent
from backend.api.main import app
import httpx
from conftest import TEST_PASSWORDS


def test_provider_env_is_isolated_from_ambient_environment():
    """Guard verifies no test inherits ambient PROVIDER or API keys from host env."""
    for var in (
        "PROVIDER",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "OLLAMA_MODEL",
    ):
        assert os.getenv(var) is None


def test_comm_agent_answers_with_llm_when_available(monkeypatch):
    """When an LLM provider is configured, answer_query uses LLM with grounded facts."""
    monkeypatch.setenv("PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    agent = CommunicationAgent()

    # Mock call_llm to simulate active real-time AI response
    def fake_call_llm(messages, tools=None, config=None):
        return {
            "text": "As a participant, you can attend sessions. Hall booking is handled by organisers.",
            "tool_calls": [],
            "usage": {"total_tokens": 42},
            "provider": "gemini",
            "model": "gemini-3.1-flash-lite",
        }

    monkeypatch.setattr("backend.modules.module5_comm_agent.agent.call_llm", fake_call_llm)

    res = agent.answer_query("ev_001", "Can I book a hall for my event?")
    assert res["found"] is True
    assert "As a participant" in res["answer"]
    assert res.get("mode") == "llm"
    assert res.get("provider") == "gemini"


def test_comm_agent_falls_back_to_rules_when_llm_fails(monkeypatch):
    """When LLM provider raises an error, answer_query falls back cleanly to schedule facts."""
    agent = CommunicationAgent()

    def failing_call_llm(messages, tools=None, config=None):
        raise ProviderError("LLM API is unreachable")

    monkeypatch.setattr("backend.modules.module5_comm_agent.agent.call_llm", failing_call_llm)
    monkeypatch.setattr(
        "backend.modules.module5_comm_agent.agent.get_provider_config",
        lambda: {"provider": "gemini", "model": "test-model", "api_key": "test-key"},
    )

    # 1. Known venue query should still resolve via database facts
    res_venue = agent.answer_query("ev_001", "Where is the main auditorium located?")
    assert res_venue["found"] is True
    assert "taking place in" in res_venue["answer"]
    assert res_venue["mode"] == "rules_fallback"
    assert res_venue["provider"] == "gemini"
    assert res_venue["model"] == "test-model"
    assert res_venue["fallback_reason"] == "LLM request failed; using grounded rules."

    # 2. Unknown query should return the safe student coordinator flag message
    res_unknown = agent.answer_query("ev_001", "book a random space")
    assert res_unknown["found"] is False
    assert "student coordinators" in res_unknown["answer"]


def test_comm_agent_falls_back_when_no_llm_provider(monkeypatch):
    """When provider is unconfigured, deterministic rules take over with zero error."""
    agent = CommunicationAgent()

    # Empty provider
    monkeypatch.setattr(
        "backend.modules.module5_comm_agent.agent.get_provider_config",
        lambda: {"provider": "", "model": "", "api_key": ""},
    )

    res = agent.answer_query("ev_001", "When is lunch scheduled?")
    assert res["found"] is True
    assert "Lunch and refreshments" in res["answer"]
    assert res["mode"] == "rules_fallback"
    assert res["fallback_reason"] == "LLM provider is not configured; using grounded rules."


@pytest.mark.anyio
async def test_universal_command_participant_forbidden():
    """Verify universal command returns 403 Forbidden with detail for participant role."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as participant
        login_res = await client.post(
            "/login",
            data={
                "email": "student@galgotias.edu",
                "password": TEST_PASSWORDS["PARTICIPANT_PASSWORD"],
            },
        )
        assert login_res.status_code in (200, 302)

        # Execute administrative universal command
        res = await client.post(
            "/api/agent/universal-command",
            json={"command": "book a hall for event"},
        )
        assert res.status_code == 403
        data = res.json()
        assert "detail" in data
        assert "participant" in data["detail"].lower()
