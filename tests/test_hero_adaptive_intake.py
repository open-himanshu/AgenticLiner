"""
Tests for adaptive_intake, natural date/time extraction, and hero prompt handling.
Runs completely offline with mocked/injected `today` and zero LLM/network calls.
"""

from datetime import date as CalendarDate, timedelta
import pytest
import httpx

from conftest import TEST_PASSWORDS
from backend.core.planner import natural_intake, agent as planner_agent, agent_mode
from backend.core.planner.natural_intake import (
    resolve_natural_datetime,
    _extract_entities_deterministic,
)
from backend.modules.module1_coplan.brief_parser import adaptive_intake
from backend.api.main import app


HERO_PROMPT = "Dance performance, 150 students, next Friday 6 PM, budget 20000"


def _expected_next_friday(today: CalendarDate) -> str:
    """Reference rule matching fixed_pipeline.next_friday."""
    days_until_friday = (4 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_until_friday)).isoformat()


@pytest.fixture
def block_all_llm_calls(monkeypatch):
    """Ensure tests make zero live LLM or network calls."""
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def _forbid_llm(*args, **kwargs):
        raise AssertionError("Unexpected live LLM call during offline intake test")

    monkeypatch.setattr("backend.core.planner.call_llm.call_llm", _forbid_llm)
    monkeypatch.setattr(agent_mode, "call_llm", _forbid_llm)
    monkeypatch.setattr(natural_intake, "call_llm", _forbid_llm)


@pytest.fixture
def fixed_today_2026_11_11(monkeypatch):
    """Pin `today` to Wednesday 2026-11-11 across intake modules."""
    class _FixedDate(CalendarDate):
        @classmethod
        def today(cls):
            return cls(2026, 11, 11)

    monkeypatch.setattr(natural_intake, "CalendarDate", _FixedDate)
    monkeypatch.setattr(agent_mode, "CalendarDate", _FixedDate)
    if hasattr(planner_agent, "CalendarDate"):
        monkeypatch.setattr(planner_agent, "CalendarDate", _FixedDate)
    return CalendarDate(2026, 11, 11)


def test_next_friday_matches_fixed_pipeline_rule(fixed_today_2026_11_11, block_all_llm_calls):
    # 2026-11-11 is Wednesday -> upcoming Friday is 2026-11-13
    resolved_date, _, _, _ = resolve_natural_datetime("next Friday", "6 PM")
    assert resolved_date == _expected_next_friday(fixed_today_2026_11_11) == "2026-11-13"

    # Rollover edge case: when today IS Friday (2026-11-13), next Friday is +7 days (2026-11-20)
    friday = CalendarDate(2026, 11, 13)
    rollover_date, _, _, _ = resolve_natural_datetime("next Friday", "6 PM", ref_date=friday)
    assert rollover_date == _expected_next_friday(friday) == "2026-11-20"


@pytest.mark.parametrize(
    "time_phrase,expected_start,expected_end,expected_duration",
    [
        ("6 PM", "18:00:00", "20:00:00", 2.0),
        ("6 to 8 PM", "18:00:00", "20:00:00", 2.0),
        ("6:30 pm", "18:30:00", "20:30:00", 2.0),
        ("18:00", "18:00:00", "20:00:00", 2.0),
        ("evening", "18:00:00", "20:00:00", 2.0),
    ],
)
def test_time_expressions_and_two_hour_default(
    fixed_today_2026_11_11,
    block_all_llm_calls,
    time_phrase,
    expected_start,
    expected_end,
    expected_duration,
):
    resolved_date, start_time, end_time, duration = resolve_natural_datetime(
        "next Friday", time_phrase, ref_date=fixed_today_2026_11_11
    )
    assert resolved_date == "2026-11-13"
    assert start_time == expected_start
    assert end_time == expected_end
    assert duration == expected_duration


def test_explicit_iso_date_preserved(fixed_today_2026_11_11, block_all_llm_calls):
    resolved_date, start_time, end_time, _ = resolve_natural_datetime(
        "2026-11-28", "6 to 8 PM", ref_date=fixed_today_2026_11_11
    )
    assert resolved_date == "2026-11-28"
    assert start_time == "18:00:00"
    assert end_time == "20:00:00"

    res = planner_agent.AutopilotAgent().run_autopilot(
        "Dance performance, 150 students, 2026-12-04 6:30 pm, budget 20000"
    )
    intake_step = next(s for s in res["timeline"] if s["tool"] == "adaptive_intake")
    assert "2026-12-04" in intake_step["summary"]
    assert "18:30:00 - 20:30:00" in intake_step["summary"]


def test_dance_performance_maps_to_cultural_never_hackathon(
    fixed_today_2026_11_11, block_all_llm_calls
):
    brief = adaptive_intake("dance performance on next Friday 6 PM for 150 students")
    assert brief["is_complete"] is True
    assert brief["event_type"] == "cultural"
    assert brief["event_type"] != "hackathon"

    entities = _extract_entities_deterministic(HERO_PROMPT)
    assert entities.event_type == "cultural"

    hero_brief = adaptive_intake(HERO_PROMPT)
    assert hero_brief["is_complete"] is True
    assert hero_brief["event_type"] == "cultural"

    res = planner_agent.AutopilotAgent().run_autopilot(HERO_PROMPT)
    intake_step = next(s for s in res["timeline"] if s["tool"] == "adaptive_intake")
    assert "Event Type='Cultural'" in intake_step["summary"]
    assert "hackathon" not in intake_step["summary"].lower()


def test_adaptive_intake_timeline_documents_two_hour_and_evening_assumptions(
    fixed_today_2026_11_11, block_all_llm_calls
):
    # Single start time -> 2-hour default documented as an assumption
    res_6pm = planner_agent.AutopilotAgent().run_autopilot(HERO_PROMPT)
    step_6pm = next(s for s in res_6pm["timeline"] if s["tool"] == "adaptive_intake")
    summary_6pm = step_6pm["summary"]
    assert "2026-11-13" in summary_6pm
    assert "18:00:00 - 20:00:00" in summary_6pm
    assert "assumption" in summary_6pm.lower()
    assert "2-hour" in summary_6pm.lower()

    # "evening" alone -> 18:00-20:00 documented as an assumption
    res_evening = planner_agent.AutopilotAgent().run_autopilot(
        "Dance performance, 150 students, next Friday evening, budget 20000"
    )
    step_evening = next(s for s in res_evening["timeline"] if s["tool"] == "adaptive_intake")
    summary_evening = step_evening["summary"]
    assert "2026-11-13" in summary_evening
    assert "18:00:00 - 20:00:00" in summary_evening
    assert "assumption" in summary_evening.lower()
    assert "evening" in summary_evening.lower()

    # Explicit range -> no defaulted end-time assumption needed
    res_range = planner_agent.AutopilotAgent().run_autopilot(
        "Dance performance, 150 students, next Friday 6 to 8 PM, budget 20000"
    )
    step_range = next(s for s in res_range["timeline"] if s["tool"] == "adaptive_intake")
    assert "2026-11-13" in step_range["summary"]
    assert "18:00:00 - 20:00:00" in step_range["summary"]
    assert "2-hour default" not in step_range["summary"].lower()


def test_hero_prompt_seeded_db_reaches_find_free_venues_18_to_20(
    fixed_today_2026_11_11, block_all_llm_calls
):
    # Direct AutopilotAgent on isolated seeded DB (provided by autouse fixture in conftest)
    res = planner_agent.AutopilotAgent().run_autopilot(HERO_PROMPT)
    assert res["success"] is True

    venue_step = next(s for s in res["timeline"] if s["tool"] == "find_free_venues")
    assert venue_step["status"] == "completed"
    assert venue_step["arguments"]["date"] == "2026-11-13"
    assert venue_step["arguments"]["start_time"] == "18:00:00"
    assert venue_step["arguments"]["end_time"] == "20:00:00"
    assert venue_step["arguments"]["min_capacity"] == 150

    # Offline fallback runner without passing date/start_time/end_time
    fallback_res = agent_mode.run_autopilot_with_fallback(HERO_PROMPT)
    assert fallback_res["success"] is True
    fb_venue = next(s for s in fallback_res["timeline"] if s["tool"] == "find_free_venues")
    assert fb_venue["arguments"]["date"] == "2026-11-13"
    assert fb_venue["arguments"]["start_time"] == "18:00:00"
    assert fb_venue["arguments"]["end_time"] == "20:00:00"


@pytest.mark.anyio
async def test_api_autopilot_run_hero_prompt_offline(
    fixed_today_2026_11_11, block_all_llm_calls
):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/login",
            data={
                "email": "organiser@galgotias.edu",
                "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
            },
        )
        assert login.status_code in (200, 302)

        resp = await client.post("/api/autopilot/run", json={"prompt": HERO_PROMPT})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        intake_step = next(s for s in data["timeline"] if s["tool"] == "adaptive_intake")
        assert "Event Type='Cultural'" in intake_step["summary"]
        assert "2026-11-13" in intake_step["summary"]
        assert "18:00:00 - 20:00:00" in intake_step["summary"]

        venue_step = next(s for s in data["timeline"] if s["tool"] == "find_free_venues")
        assert venue_step["arguments"]["date"] == "2026-11-13"
        assert venue_step["arguments"]["start_time"] == "18:00:00"
        assert venue_step["arguments"]["end_time"] == "20:00:00"
