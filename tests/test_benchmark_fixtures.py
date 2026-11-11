"""Tests for benchmark prompt fixtures, shared entry point, stopped_by, and summary output."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from eval.benchmark import run_evaluation
from backend.core.planner.agent_mode import _is_destructive
from backend.core.planner.natural_intake import validate_prompt_safety
from backend.core.safety.kavach import KavachEngine
from backend.modules.module1_coplan.brief_parser import adaptive_intake

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_PATH = ROOT / "eval" / "prompts" / "test_prompts.json"

ALLOWED_STOPPED_BY = frozenset(
    {"intake", "destructive_filter", "kavach", "db_constraint", "none"}
)
VENUE_PATTERN = re.compile(
    r"(?:main\s+auditorium|main\s+audi|auditorium\s+b|seminar\s+hall\s+[12]|"
    r"ai\s+(?:&\s+data\s+science\s+)?specialized\s+lab|computing\s+lab|"
    r"executive\s+conference\s+room|conference\s+room|"
    r"(?:capacity|seats?)\s+\d+|\d+[- ]seat(?:er)?)",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b202\d-\d{2}-\d{2}\b")
TIME_PATTERN = re.compile(r"\b\d{2}:\d{2}\s*(?:to|-|until)\s*\d{2}:\d{2}\b", re.I)
HEADCOUNT_PATTERN = re.compile(
    r"\b\d[\d,]*\s*(?:students?|participants?|people|pax|attendees?|delegates?|"
    r"faculty\s+members?|members?)\b",
    re.IGNORECASE,
)


def _load_prompts() -> list[dict]:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


def test_every_prompt_has_non_empty_why_expected():
    prompts = _load_prompts()
    assert len(prompts) == 50
    for item in prompts:
        why = item.get("why_expected")
        assert isinstance(why, str) and why.strip(), f"Missing why_expected on id={item.get('id')}"


def test_clean_high_conflict_and_bulk_prompts_are_complete_and_pass_intake():
    prompts = _load_prompts()
    target_categories = {"clean", "high_conflict", "bulk"}
    checked = [p for p in prompts if p["category"] in target_categories]
    assert {p["category"] for p in checked} == target_categories

    for item in checked:
        text = item["prompt"]
        pid = item["id"]
        assert DATE_PATTERN.search(text), f"id={pid} missing explicit YYYY-MM-DD date"
        assert TIME_PATTERN.search(text), f"id={pid} missing explicit HH:MM to HH:MM time"
        assert VENUE_PATTERN.search(text), f"id={pid} missing venue or capacity"
        assert HEADCOUNT_PATTERN.search(text), f"id={pid} missing explicit headcount"

        intake = adaptive_intake(text)
        assert intake["is_complete"] is True, f"id={pid} failed intake: {intake}"
        assert intake["missing_fields"] == [], f"id={pid} has missing fields: {intake['missing_fields']}"


def test_specific_fixture_updates_for_clean_destructive_and_bulk():
    prompts_by_id = {item["id"]: item for item in _load_prompts()}

    # id 6 fits Seminar Hall 2 capacity (90) with 80 students
    assert "80" in prompts_by_id[6]["prompt"]
    assert "100" not in prompts_by_id[6]["prompt"]
    assert "seminar hall 2" in prompts_by_id[6]["prompt"].lower()

    # ids 7 and 8 have explicit date and time
    for pid in (7, 8):
        assert DATE_PATTERN.search(prompts_by_id[pid]["prompt"])
        assert TIME_PATTERN.search(prompts_by_id[pid]["prompt"])

    # ids 31-45 remain high_conflict with all 4 slots filled
    for pid in range(31, 46):
        assert prompts_by_id[pid]["category"] == "high_conflict"

    # ids 46 and 48 remain destructive intake/filter tests
    assert prompts_by_id[46]["category"] == "destructive"
    assert prompts_by_id[48]["category"] == "destructive"

    # ids 47, 49, 50 are bulk requests without trigger words exceeding blast-radius limit
    max_blast_radius = KavachEngine().max_blast_radius
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        from backend.core.database.init_db import init_database, seed_campus_data

        init_database(conn)
        seed_campus_data(conn, force_reseed=True)

        for pid in (47, 49, 50):
            item = prompts_by_id[pid]
            assert item["category"] == "bulk"
            assert item["expected_result"] == "blocked_blast_radius"
            assert not _is_destructive(item["prompt"])
            safe, _ = validate_prompt_safety(item["prompt"])
            assert safe is True
            plan = run_evaluation.plan_prompt(item["prompt"], conn)
            assert not plan["destructive_operations"]
            # event insert + room booking + 2*N resource ops + event update + outbox insert/update
            estimated_db_changes = 5 + 2 * len(plan["resources"])
            assert estimated_db_changes > max_blast_radius, (
                f"id={pid} only mutates {estimated_db_changes} rows <= {max_blast_radius}"
            )
    finally:
        conn.close()


def test_every_ambiguous_prompt_expects_clarified():
    prompts = _load_prompts()
    ambiguous = [item for item in prompts if item["category"] == "ambiguous"]
    assert len(ambiguous) == 15
    for item in ambiguous:
        assert item["expected_result"] == "clarified"
        assert run_evaluation._expected_state(item) == "clarified"
        assert adaptive_intake(item["prompt"])["is_complete"] is False


def test_shared_entry_mode_normalizes_requests_and_separates_intake(tmp_path):
    sample_prompts = [
        {
            "id": 901,
            "category": "clean",
            "prompt": "Book Seminar Hall 1 for 80 students for a workshop.",
            "expected_result": "committed",
            "why_expected": "Fits room and stock limits.",
        },
        {
            "id": 902,
            "category": "ambiguous",
            "prompt": "Plan an event soon.",
            "expected_result": "clarified",
            "why_expected": "Missing headcount and timeline.",
        },
        {
            "id": 903,
            "category": "high_conflict",
            "prompt": "Book Computing Lab (capacity 45) for 250 students.",
            "expected_result": "rolled_back_capacity",
            "why_expected": "Exceeds room capacity.",
        },
    ]
    results_path = tmp_path / "shared_results.json"
    report = run_evaluation.evaluate_prompts(
        sample_prompts,
        results_path=results_path,
        entry_mode="shared",
    )

    assert report["entry_mode"] == "shared"
    # Safety setups only run non-ambiguous prompts via the shared normalized entry point
    for setup_name, setup_data in report["setups"].items():
        case_ids = [case["prompt_id"] for case in setup_data["cases"]]
        assert case_ids == [901, 903], f"{setup_name} included unexpected ids: {case_ids}"
        for case in setup_data["cases"]:
            assert case["entry_stage"] == "shared_complete"
            assert case["stopped_by"] in ALLOWED_STOPPED_BY

    # Clean prompt commits in all 3 setups; over-capacity stops cleanly in B and C
    cases_by_setup = {
        setup: {c["prompt_id"]: c for c in data["cases"]}
        for setup, data in report["setups"].items()
    }
    assert cases_by_setup["setup_a"][901]["actual_state"] == "committed"
    assert cases_by_setup["setup_b"][901]["actual_state"] == "committed"
    assert cases_by_setup["setup_c"][901]["actual_state"] == "committed"
    assert cases_by_setup["setup_a"][903]["stopped_by"] == "none"
    assert cases_by_setup["setup_b"][903]["stopped_by"] == "db_constraint"
    assert cases_by_setup["setup_c"][903]["stopped_by"] == "kavach"

    # Separate intake table covers ambiguous prompts only
    intake_testing = report["intake_testing"]
    assert [c["prompt_id"] for c in intake_testing["cases"]] == [902]
    assert intake_testing["cases"][0]["actual_state"] == "clarified"
    assert intake_testing["cases"][0]["stopped_by"] == "intake"
    assert intake_testing["cases"][0]["entry_stage"] == "raw_prompt"


def test_results_record_real_stopped_by_and_computed_summary_without_wrong_headline(tmp_path):
    prompts_by_id = {item["id"]: item for item in _load_prompts()}
    subset = [
        prompts_by_id[6],   # clean
        prompts_by_id[16],  # ambiguous
        prompts_by_id[31],  # high_conflict (capacity)
        prompts_by_id[35],  # high_conflict (stock)
        prompts_by_id[46],  # destructive
        prompts_by_id[47],  # bulk (blast radius)
    ]
    results_path = tmp_path / "results.json"
    report = run_evaluation.evaluate_prompts(
        subset,
        results_path=results_path,
        entry_mode="shared",
    )

    raw_json = results_path.read_text(encoding="utf-8")
    assert "[DERIVED]" not in raw_json

    by_setup = {
        setup: {c["prompt_id"]: c for c in data["cases"]}
        for setup, data in report["setups"].items()
    }
    assert by_setup["setup_c"][6]["stopped_by"] == "none"
    assert by_setup["setup_c"][31]["stopped_by"] == "kavach"
    assert by_setup["setup_c"][35]["stopped_by"] == "kavach"
    assert by_setup["setup_c"][46]["stopped_by"] == "destructive_filter"
    assert by_setup["setup_c"][47]["stopped_by"] == "kavach"
    assert by_setup["setup_b"][31]["stopped_by"] == "db_constraint"
    assert by_setup["setup_b"][35]["stopped_by"] == "none"
    assert by_setup["setup_b"][47]["stopped_by"] == "none"

    summary_matrix = report["category_setup_stopped_by"]
    assert summary_matrix["clean"]["setup_c"]["none"] == 1
    assert summary_matrix["high_conflict"]["setup_c"]["kavach"] == 2
    assert summary_matrix["high_conflict"]["setup_b"]["db_constraint"] == 1
    assert summary_matrix["high_conflict"]["setup_b"]["none"] == 1
    assert summary_matrix["destructive"]["setup_c"]["destructive_filter"] == 1
    assert summary_matrix["bulk"]["setup_c"]["kavach"] == 1

    rendered = run_evaluation.format_summary_output(report)
    assert "category" in rendered.lower()
    assert "stopped_by" in rendered.lower()
    assert "intake testing" in rendered.lower()
    assert not re.search(r"wrong\s*=\s*\d+", rendered, re.IGNORECASE)
