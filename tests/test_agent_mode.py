"""
Tests for the Autopilot Agent Mode.

All tests use a fake call_llm that returns scripted tool calls — NO network
or LLM calls.  Covers:
  1. Clean booking (agent picks tools, requisition commits)
  2. Rejected booking that the model retries
  3. Step cap (agent loops until MAX_STEPS)
  4. Fallback to fixed pipeline when provider fails
  5. Destructive prompt ("cancel everything") is blocked
"""

import json
import pytest

from backend.core.planner.agent_mode import (
    run_agent_mode,
    run_autopilot_with_fallback,
    MAX_STEPS,
    MAX_ASK_USER,
    ProviderError,
)


# ---------------------------------------------------------------------------
# Helpers — fake call_llm builders
# ---------------------------------------------------------------------------

def _make_fake_llm(script):
    """
    Build a fake call_llm from a list of scripted responses.

    Each item in *script* is a dict with 'text' and 'tool_calls'.
    The fake returns responses in order, cycling the last one if the agent
    keeps calling beyond the script length.
    """
    call_count = {"n": 0}

    def fake_call_llm(messages, tools, config=None):
        idx = min(call_count["n"], len(script) - 1)
        call_count["n"] += 1
        resp = script[idx]
        return {
            "text": resp.get("text", ""),
            "tool_calls": resp.get("tool_calls", []),
            "usage": resp.get("usage", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
            "provider": "fake",
            "model": "test-model",
        }

    return fake_call_llm


def _make_failing_llm():
    """Fake call_llm that always raises ProviderError."""
    def failing_call_llm(messages, tools, config=None):
        raise ProviderError("Provider unavailable for testing")
    return failing_call_llm


# ---------------------------------------------------------------------------
# 1. Clean booking — model calls find_free_venues, recommend_from_history,
#    then requisition, and Kavach commits.
# ---------------------------------------------------------------------------

class TestCleanBooking:
    def test_agent_clean_booking_commits(self):
        """The agent calls tools in order and the requisition commits successfully."""
        script = [
            # Step 1: model calls find_free_venues
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "find_free_venues",
                        "arguments": {
                            "min_capacity": 150,
                            "date": "2026-12-20",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                        },
                    }
                ],
            },
            # Step 2: model calls recommend_from_history
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "recommend_from_history",
                        "arguments": {"event_type": "hackathon", "headcount": 150},
                    }
                ],
            },
            # Step 3: model calls requisition
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "requisition",
                        "arguments": {
                            "room_id": "room_auto_test",
                            "attendance": 150,
                            "items_json": "[]",
                            "date": "2026-12-20",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                            "budget": 25000,
                            "event_name": "AI Hackathon",
                            "event_type": "hackathon",
                        },
                    }
                ],
            },
            # Step 4: model finishes with summary text
            {
                "text": "Booking confirmed for AI Hackathon at Main Campus Auditorium.",
                "tool_calls": [],
            },
        ]
        fake_llm = _make_fake_llm(script)

        # Ensure the test room exists
        from backend.core.database.connection import execute_query
        execute_query(
            "INSERT OR IGNORE INTO rooms (id, name, capacity, location) "
            "VALUES ('room_auto_test', 'Main Campus Auditorium', 300, 'Block A')"
        )

        result = run_agent_mode(
            prompt="Organize a hackathon for 150 students",
            date="2026-12-20",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        assert result["mode"] == "agent"
        assert result["success"] is True
        assert result["provider"] == "fake"
        assert result["model"] == "test-model"
        assert result["tokens_used"]["total_tokens"] > 0

        # Verify timeline recorded the tools
        tool_names = [s["tool"] for s in result["timeline"]]
        assert "find_free_venues" in tool_names
        assert "recommend_from_history" in tool_names
        assert "requisition" in tool_names

        # Verify a step was committed
        committed = [s for s in result["timeline"] if s["status"] == "committed"]
        assert len(committed) >= 1


# ---------------------------------------------------------------------------
# 2. Rejected booking that the model retries
# ---------------------------------------------------------------------------

class TestRejectedRetry:
    def test_agent_retries_after_rejection(self):
        """After a requisition violation, the model tries a different room."""
        # Use a room that doesn't exist to trigger a Kavach violation,
        # then use a room that does exist.
        from backend.core.database.connection import execute_query
        execute_query(
            "INSERT OR IGNORE INTO rooms (id, name, capacity, location) "
            "VALUES ('room_retry_test', 'Retry Hall', 300, 'Block B')"
        )

        script = [
            # Step 1: model tries to book a non-existent room
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "requisition",
                        "arguments": {
                            "room_id": "room_does_not_exist",
                            "attendance": 100,
                            "items_json": "[]",
                            "date": "2026-12-21",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                            "budget": 25000,
                            "event_name": "Retry Test",
                            "event_type": "seminar",
                        },
                    }
                ],
            },
            # Step 2: after seeing the rejection, model calls find_free_venues
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "find_free_venues",
                        "arguments": {
                            "min_capacity": 100,
                            "date": "2026-12-21",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                        },
                    }
                ],
            },
            # Step 3: model retries requisition with valid room
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "requisition",
                        "arguments": {
                            "room_id": "room_retry_test",
                            "attendance": 100,
                            "items_json": "[]",
                            "date": "2026-12-21",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                            "budget": 25000,
                            "event_name": "Retry Test Success",
                            "event_type": "seminar",
                        },
                    }
                ],
            },
            # Step 4: model finishes
            {
                "text": "Booked after retry.",
                "tool_calls": [],
            },
        ]
        fake_llm = _make_fake_llm(script)

        result = run_agent_mode(
            prompt="Organize a seminar for 100 students",
            date="2026-12-21",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        assert result["mode"] == "agent"
        # There should be at least one rolled_back and one committed step
        statuses = [s["status"] for s in result["timeline"]]
        assert "rolled_back" in statuses, "Expected at least one rolled_back step"
        assert "committed" in statuses, "Expected a committed step after retry"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 3. Step cap — agent hits MAX_STEPS without finishing
# ---------------------------------------------------------------------------

class TestStepCap:
    def test_agent_stops_at_max_steps(self):
        """Agent is stopped when it reaches the step limit without booking."""
        # Model keeps calling check_equipment forever
        infinite_script = [
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "check_equipment",
                        "arguments": {},
                    }
                ],
            }
        ]
        fake_llm = _make_fake_llm(infinite_script)

        result = run_agent_mode(
            prompt="Plan a seminar for 50 students",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        assert result["mode"] == "agent"
        assert result["success"] is False
        # Should have a step_limit entry
        step_limit_entries = [s for s in result["timeline"] if s["tool"] == "step_limit"]
        assert len(step_limit_entries) == 1
        assert step_limit_entries[0]["status"] == "stopped"
        # Total steps must not exceed MAX_STEPS
        assert len(result["timeline"]) <= MAX_STEPS + 1  # +1 for the step_limit entry itself


# ---------------------------------------------------------------------------
# 4. Fallback to fixed pipeline
# ---------------------------------------------------------------------------

class TestFallback:
    def test_fallback_to_fixed_pipeline(self):
        """When call_llm raises ProviderError, we fall back to fixed pipeline."""
        from backend.core.database.connection import execute_query
        execute_query(
            "INSERT OR IGNORE INTO rooms (id, name, capacity, location) "
            "VALUES ('room_auto_test', 'Main Campus Auditorium', 300, 'Block A')"
        )

        failing_llm = _make_failing_llm()

        result = run_autopilot_with_fallback(
            prompt="Organize a hackathon for 150 students",
            date="2026-12-22",
            budget=25000,
            call_llm_fn=failing_llm,
        )

        assert result["mode"] == "fixed_fallback"
        assert "timeline" in result
        assert result["tokens_used"]["total_tokens"] == 0
        # The fixed pipeline should still produce a result
        assert "event_id" in result


# ---------------------------------------------------------------------------
# 5. Destructive prompt blocked
# ---------------------------------------------------------------------------

class TestDestructivePromptBlocked:
    def test_cancel_everything_blocked(self):
        """'Cancel everything' prompt is blocked before any LLM call."""
        # Should not need a real LLM at all
        script = [{"text": "I will cancel all.", "tool_calls": []}]
        fake_llm = _make_fake_llm(script)

        result = run_agent_mode(
            prompt="cancel everything and delete all events",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        assert result["mode"] == "agent"
        assert result["success"] is False
        assert result["error"] == "Destructive prompt blocked."
        # Verify no tokens were used (LLM was never called)
        assert result["tokens_used"]["total_tokens"] == 0
        # Timeline should show the safety block
        assert result["timeline"][0]["status"] == "blocked"

    def test_purge_blocked(self):
        """'Purge' is also caught by the destructive filter."""
        result = run_agent_mode(
            prompt="purge the entire database",
            budget=25000,
            call_llm_fn=_make_fake_llm([{"text": "", "tool_calls": []}]),
        )
        assert result["success"] is False
        assert result["error"] == "Destructive prompt blocked."

    def test_normal_prompt_not_blocked(self):
        """A normal prompt should NOT trigger the destructive filter."""
        script = [{"text": "Got it, planning your event.", "tool_calls": []}]
        fake_llm = _make_fake_llm(script)

        result = run_agent_mode(
            prompt="Organize a cultural fest for 200 students",
            budget=25000,
            call_llm_fn=fake_llm,
        )
        # Should not be blocked
        assert result.get("error") != "Destructive prompt blocked."


# ---------------------------------------------------------------------------
# 6. ask_user cap enforced in code
# ---------------------------------------------------------------------------

class TestAskUserCap:
    def test_ask_user_limited_to_max(self):
        """ask_user is limited to MAX_ASK_USER calls, extras are auto-answered."""
        questions = [
            {
                "text": "",
                "tool_calls": [{"name": "ask_user", "arguments": {"question": f"Question {i+1}?"}}],
            }
            for i in range(MAX_ASK_USER + 2)
        ]
        questions.append({"text": "Done.", "tool_calls": []})
        fake_llm = _make_fake_llm(questions)

        result = run_agent_mode(
            prompt="Plan an event for 100 students",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        ask_steps = [s for s in result["timeline"] if s["tool"] == "ask_user"]
        # At least some should have hit the limit
        limit_hit = [s for s in ask_steps if "limit reached" in s.get("summary", "").lower()]
        assert len(limit_hit) >= 1, "ask_user cap should be enforced in code"


# ---------------------------------------------------------------------------
# 7. Budget enforced in code (not just prompt)
# ---------------------------------------------------------------------------

class TestBudgetEnforcement:
    def test_over_budget_blocked_in_code(self):
        """A requisition over the hard budget limit is rejected in code."""
        script = [
            {
                "text": "",
                "tool_calls": [
                    {
                        "name": "requisition",
                        "arguments": {
                            "room_id": "room_auto_test",
                            "attendance": 100,
                            "items_json": "[]",
                            "date": "2026-12-23",
                            "start_time": "09:00:00",
                            "end_time": "17:00:00",
                            "budget": 999999,  # Way over the allowed 5000
                            "event_name": "Over Budget Event",
                            "event_type": "seminar",
                        },
                    }
                ],
            },
            {"text": "Budget exceeded.", "tool_calls": []},
        ]
        fake_llm = _make_fake_llm(script)

        from backend.core.database.connection import execute_query
        execute_query(
            "INSERT OR IGNORE INTO rooms (id, name, capacity, location) "
            "VALUES ('room_auto_test', 'Main Campus Auditorium', 300, 'Block A')"
        )

        result = run_agent_mode(
            prompt="Plan something small",
            date="2026-12-23",
            budget=5000,  # Hard limit
            call_llm_fn=fake_llm,
        )

        req_steps = [s for s in result["timeline"] if s["tool"] == "requisition"]
        assert len(req_steps) >= 1
        assert req_steps[0]["status"] == "rolled_back"
        assert "budget" in req_steps[0]["summary"].lower()


# ---------------------------------------------------------------------------
# 8. Mode and metadata in response
# ---------------------------------------------------------------------------

class TestResponseMetadata:
    def test_agent_mode_metadata(self):
        """Response includes mode, provider, model, tokens, and timeline."""
        script = [{"text": "All done.", "tool_calls": []}]
        fake_llm = _make_fake_llm(script)

        result = run_agent_mode(
            prompt="Organize a workshop for 50 students",
            budget=25000,
            call_llm_fn=fake_llm,
        )

        assert result["mode"] == "agent"
        assert "provider" in result
        assert "model" in result
        assert "tokens_used" in result
        assert "timeline" in result
        assert isinstance(result["timeline"], list)
        assert "event_id" in result

