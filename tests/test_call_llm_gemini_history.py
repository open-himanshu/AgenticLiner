"""Tests for Gemini multi-turn native content / thought_signature replay."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from google.genai import errors, types

from backend.core.database.connection import execute_query
from backend.core.database.init_db import init_database
from backend.core.planner import agent_mode, call_llm


def _init_isolated_db(monkeypatch, tmp_path):
    db_path = tmp_path / "gemini_history_test.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    init_database()
    execute_query(
        "INSERT OR IGNORE INTO rooms (id, name, capacity, location) "
        "VALUES ('room_audi_test', 'Main Campus Auditorium', 300, 'Block A')"
    )


def _mock_response(content: types.Content):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=8,
            total_token_count=20,
        ),
    )


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


def test_gemini_multiturn_preserves_native_content_and_thought_signature_with_function_response(
    monkeypatch, tmp_path
):
    _init_isolated_db(monkeypatch, tmp_path)
    monkeypatch.setenv("PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    turn1_content = types.Content(
        role="model",
        parts=[
            types.Part(thought=True, text="Need to locate a suitable venue first."),
            types.Part(
                function_call=types.FunctionCall(
                    name="find_free_venues",
                    args={
                        "min_capacity": 150,
                        "date": "2026-11-20",
                        "start_time": "18:00:00",
                        "end_time": "20:00:00",
                    },
                ),
                thought_signature=b"sig-turn1-gemini3",
            ),
        ],
    )
    turn2_content = types.Content(
        role="model",
        parts=[types.Part(text="Checked Main Campus Auditorium for 150 students.")],
    )

    sdk_calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            sdk_calls.append(kwargs)
            if len(sdk_calls) == 1:
                return _mock_response(turn1_content)
            return _mock_response(turn2_content)

    monkeypatch.setattr("google.genai.Client", FakeClient)

    captured_messages = []
    real_call_llm = call_llm.call_llm

    def spy_call_llm(messages, tools=None, config=None):
        captured_messages.append([dict(m) for m in messages])
        return real_call_llm(messages, tools, config)

    result = agent_mode.run_agent_mode(
        prompt="Dance performance for 150 students on 2026-11-20 18:00-20:00",
        date="2026-11-20",
        start_time="18:00:00",
        end_time="20:00:00",
        budget=20000,
        call_llm_fn=spy_call_llm,
    )

    assert result["mode"] == "agent"
    assert len(sdk_calls) == 2

    # (a) Message history retains the exact native content returned in turn 1
    turn2_history = captured_messages[1]
    assistant_msgs = [m for m in turn2_history if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].get("raw_content") is turn1_content

    # (a) Turn-2 Gemini request sends the exact native Content/parts unchanged (including thought_signature)
    turn2_contents = sdk_calls[1]["contents"]
    assert len(turn2_contents) == 3
    assert turn2_contents[0].role == "user"
    assert turn2_contents[1] is turn1_content
    assert len(turn2_contents[1].parts) == 2
    assert turn2_contents[1].parts[0].thought is True
    assert turn2_contents[1].parts[1].function_call.name == "find_free_venues"
    assert turn2_contents[1].parts[1].thought_signature == b"sig-turn1-gemini3"

    # (b) Tool execution result follows as a function_response part
    tool_content = turn2_contents[2]
    assert tool_content.role == "user"
    assert len(tool_content.parts) == 1
    fn_resp = tool_content.parts[0].function_response
    assert fn_resp is not None
    assert fn_resp.name == "find_free_venues"
    assert isinstance(fn_resp.response, dict)
    assert "venues" in fn_resp.response


def test_gemini_contents_wraps_non_dict_tool_result_as_function_response():
    messages = [
        {"role": "user", "content": "Plan an event"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "ask_user", "arguments": {"question": "Date?"}}],
            "raw_content": types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            name="ask_user",
                            args={"question": "Date?"},
                        ),
                        thought_signature=b"sig-ask",
                    )
                ],
            ),
        },
        {
            "role": "tool",
            "name": "ask_user",
            "content": json.dumps("User was asked: Date?"),
        },
    ]

    contents = call_llm._gemini_contents(messages, types)
    assert len(contents) == 3
    assert contents[1].parts[0].thought_signature == b"sig-ask"
    assert contents[2].role == "user"
    fn_resp = contents[2].parts[0].function_response
    assert fn_resp is not None
    assert fn_resp.name == "ask_user"
    assert fn_resp.response == {"result": "User was asked: Date?"}


def test_groq_and_ollama_multiturn_behave_as_before(monkeypatch):
    sent_payloads = []

    def fake_urlopen(req, timeout=120):
        body = json.loads(req.data.decode("utf-8"))
        sent_payloads.append((req.full_url, body))
        if "groq.com" in req.full_url:
            return _FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Groq done.",
                                "tool_calls": [
                                    {
                                        "id": "call_g2",
                                        "type": "function",
                                        "function": {
                                            "name": "check_equipment",
                                            "arguments": '{"date":"2026-11-20"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
                }
            )
        return _FakeHTTPResponse(
            {
                "message": {
                    "content": "Ollama done.",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "check_equipment",
                                "arguments": {"date": "2026-11-20"},
                            },
                        }
                    ],
                },
                "prompt_eval_count": 6,
                "eval_count": 3,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "check rooms"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "find_free_venues", "arguments": {"min_capacity": 50}}
            ],
            "raw_content": types.Content(role="model", parts=[types.Part(text="native-ignored")]),
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "find_free_venues",
            "content": json.dumps({"venues": []}),
        },
    ]

    groq_res = call_llm.call_llm(
        history,
        tools=[],
        config={"provider": "groq", "model": "llama-3.3-70b-versatile", "api_key": "fake-groq-key"},
    )
    assert groq_res["text"] == "Groq done."
    assert groq_res["tool_calls"][0]["name"] == "check_equipment"
    assert groq_res["tool_calls"][0]["arguments"] == {"date": "2026-11-20"}
    groq_sent = sent_payloads[0][1]["messages"]
    assert groq_sent[2]["role"] == "assistant"
    assert "raw_content" not in groq_sent[2]
    assert groq_sent[2]["tool_calls"][0]["function"]["arguments"] == '{"min_capacity": 50}'
    assert groq_sent[3]["role"] == "tool" and groq_sent[3]["tool_call_id"] == "call_1"

    ollama_res = call_llm.call_llm(
        history,
        tools=[],
        config={"provider": "ollama", "model": "qwen3.5:9b", "api_key": ""},
    )
    assert ollama_res["text"] == "Ollama done."
    assert ollama_res["tool_calls"][0]["name"] == "check_equipment"
    assert ollama_res["tool_calls"][0]["arguments"] == {"date": "2026-11-20"}
    ollama_sent = sent_payloads[1][1]["messages"]
    assert ollama_sent[2]["role"] == "assistant"
    assert "raw_content" not in ollama_sent[2]
    assert ollama_sent[2]["tool_calls"][0]["function"]["arguments"] == {"min_capacity": 50}
    assert ollama_sent[3] == {"role": "tool", "tool_name": "find_free_venues", "content": '{"venues": []}'}


def test_gemini_turn2_api_error_triggers_fixed_fallback_with_real_error_text(
    monkeypatch, tmp_path
):
    _init_isolated_db(monkeypatch, tmp_path)
    monkeypatch.setenv("PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-fake-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    turn1_content = types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(
                    name="find_free_venues",
                    args={"min_capacity": 150, "date": "2026-11-20"},
                ),
                thought_signature=b"sig-turn1",
            )
        ],
    )

    call_count = {"n": 0}

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = self

        def generate_content(self, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_response(turn1_content)
            raise errors.APIError(
                400,
                {"error": {"message": "Function call is missing a thought_signature in functionCall parts"}},
            )

    monkeypatch.setattr("google.genai.Client", FakeClient)

    result = agent_mode.run_autopilot_with_fallback(
        prompt="Dance performance for 150 students on 2026-11-20 18:00-20:00",
        date="2026-11-20",
        start_time="18:00:00",
        end_time="20:00:00",
        budget=20000,
    )

    assert call_count["n"] == 2
    assert result["mode"] == "fixed_fallback"
    assert "HTTP 400" in result["fallback_reason"]
    assert "Function call is missing a thought_signature in functionCall parts" in result["fallback_reason"]
