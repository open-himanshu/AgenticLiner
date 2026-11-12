"""Tests for Gemini timeout extension and 504 / network deadline retry handling."""

from __future__ import annotations

from types import SimpleNamespace
import httpx
import pytest
from google.genai import errors, types

from backend.core.planner import call_llm


def _mock_response(text: str = "ok"):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(text=text)]))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            total_token_count=15,
        ),
    )


def test_gemini_client_uses_extended_timeout_and_respects_env_var(monkeypatch):
    captured_client_kwargs = []

    class FakeClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.append(kwargs)
            self.models = self

        def generate_content(self, **_kwargs):
            return _mock_response()

    monkeypatch.setattr("google.genai.Client", FakeClient)

    # 1. Default timeout should be at least 60_000 ms (not old 20_000)
    monkeypatch.delenv("GEMINI_TIMEOUT_MS", raising=False)
    call_llm._call_gemini(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gemini-3.1-flash-lite",
        api_key="fake-key",
    )
    assert len(captured_client_kwargs) == 1
    http_opts = captured_client_kwargs[0].get("http_options")
    assert http_opts is not None
    assert http_opts.timeout >= 60_000

    # 2. Configurable via GEMINI_TIMEOUT_MS
    monkeypatch.setenv("GEMINI_TIMEOUT_MS", "120000")
    call_llm._call_gemini(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gemini-3.1-flash-lite",
        api_key="fake-key",
    )
    assert len(captured_client_kwargs) == 2
    http_opts2 = captured_client_kwargs[1].get("http_options")
    assert http_opts2 is not None
    assert http_opts2.timeout == 120_000


def test_gemini_504_deadline_expired_is_retried_as_temporary(monkeypatch):
    call_count = {"n": 0}
    sleep_calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First attempt raises 504 Deadline expired before operation could complete
                raise errors.APIError(
                    504,
                    {"error": {"code": 504, "message": "Deadline expired before operation could complete.", "status": "DEADLINE_EXCEEDED"}},
                )
            return _mock_response("recovered after 504 retry")

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    res = call_llm._call_gemini(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gemini-3.1-flash-lite",
        api_key="fake-key",
    )

    assert call_count["n"] == 2
    assert res["text"] == "recovered after 504 retry"
    assert len(sleep_calls) >= 1


def test_gemini_httpx_timeout_is_retried_as_temporary(monkeypatch):
    call_count = {"n": 0}
    sleep_calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.ReadTimeout("The read operation timed out")
            return _mock_response("recovered after read timeout")

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    res = call_llm._call_gemini(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gemini-3.1-flash-lite",
        api_key="fake-key",
    )

    assert call_count["n"] == 2
    assert res["text"] == "recovered after read timeout"
    assert len(sleep_calls) >= 1
