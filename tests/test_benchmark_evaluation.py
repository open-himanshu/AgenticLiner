import json
import sqlite3
import subprocess
import sys

from eval.benchmark import run_evaluation
from eval.benchmark.independent_checker import IndependentDBChecker


def test_evaluation_script_cli_imports_from_the_repository_root():
    completed = subprocess.run(
        [sys.executable, str(run_evaluation.ROOT / "eval" / "benchmark" / "run_evaluation.py"), "--help"],
        cwd=run_evaluation.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--real-provider" in completed.stdout


def test_evaluation_uses_a_fresh_seeded_database_per_setup_and_prompt(
    monkeypatch, tmp_path
):
    database_paths = []
    created_database_states = []
    create_database = run_evaluation.create_scenario_database

    def track_database(path, **kwargs):
        created_path = create_database(path, **kwargs)
        database_paths.append(created_path)
        created_database_states.append(created_path.exists())
        return created_path

    monkeypatch.setattr(run_evaluation, "create_scenario_database", track_database)

    def offline_provider(messages, tools, config):
        return {
            "text": "No action taken.",
            "tool_calls": [],
            "provider": "scripted-test",
            "model": "offline-fixture",
            "usage": {},
        }

    prompts = [
        {
            "id": "first",
            "category": "clean",
            "prompt": "Book Seminar Hall 1 for 80 students for a workshop.",
            "expected_result": "committed",
        },
        {
            "id": "second",
            "category": "ambiguous",
            "prompt": "Plan a campus event soon.",
            "expected_result": "adaptive_clarification",
        },
    ]
    results_path = tmp_path / "results.json"

    result = run_evaluation.evaluate_prompts(
        prompts,
        results_path=results_path,
        call_llm_fn=offline_provider,
    )

    assert len(database_paths) == len(prompts) * 3
    assert len(set(database_paths)) == len(database_paths)
    assert all(path != run_evaluation.APP_DATABASE_PATH for path in database_paths)
    assert all(created_database_states)

    assert result["date"]
    assert result["provider"] == "scripted-test"
    assert result["model"] == "offline-fixture"
    assert result["limitations"]
    assert any("weekday" in item.lower() for item in result["limitations"])
    assert any(
        "expected_result" in item for item in result["limitations"]
    )
    for setup in result["setups"].values():
        assert {
            "wrong_final_states",
            "errors_caught",
            "errors_missed",
            "valid_requests_wrongly_blocked",
            "retries",
            "latency_seconds",
        } <= setup.keys()
    assert json.loads(results_path.read_text(encoding="utf-8")) == result


def test_independent_checker_reads_the_scenario_database_and_detects_orphans(tmp_path):
    database_path = tmp_path / "scenario.sqlite3"
    run_evaluation.create_scenario_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO events (id, name, brief, expected_participants)
            VALUES (?, ?, ?, ?)
            """,
            ("orphan", "Orphan event", "No booking was created.", 1),
        )
        connection.execute(
            """
            INSERT INTO events (id, name, brief, expected_participants)
            VALUES (?, ?, ?, ?)
            """,
            ("over-capacity", "Over capacity", "Too many attendees.", 90),
        )
        connection.execute(
            """
            INSERT INTO bookings
                (id, event_id, room_id, item_name, category, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "over-capacity-booking",
                "over-capacity",
                "room_comp_lab",
                "Computing lab",
                "venue",
                "2026-12-01 09:00:00",
                "2026-12-01 10:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO bookings
                (id, event_id, room_id, item_name, category, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "overlap-booking",
                "over-capacity",
                "room_sem_101",
                "Seminar Hall 1",
                "venue",
                "2026-11-25 16:00:00",
                "2026-11-25 18:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO outbox (id, event_id, recipient, subject, message, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "held-notice",
                "over-capacity",
                "recipient@example.invalid",
                "Held notice",
                "This should not remain held after the operation.",
                "held",
            ),
        )

    report = IndependentDBChecker().run_full_audit(database_path=database_path)

    assert report["violations"]["orphan_events_count"] == 1
    assert report["details"]["orphan_events"][0]["id"] == "orphan"
    assert any(
        violation.get("booking_id") == "over-capacity-booking"
        for violation in report["details"]["capacity_violations"]
    )
    assert report["violations"]["room_overlaps_count"] == 1
    assert report["violations"]["outbox_leaks_count"] == 1


def test_setup_c_catches_capacity_violation_and_direct_setups_persist_it(tmp_path):
    results = run_evaluation.evaluate_prompts(
        [
            {
                "id": "capacity",
                "category": "high_conflict",
                "prompt": "Book Computing Lab for 250 students for a workshop tomorrow.",
                "expected_result": "rolled_back_capacity",
            }
        ],
        results_path=tmp_path / "results.json",
    )

    setups = results["setups"]
    assert setups["setup_a"]["cases"][0]["audit"]["violations"][
        "capacity_overruns_count"
    ] > 0
    assert setups["setup_b"]["cases"][0]["audit"]["violations"][
        "capacity_overruns_count"
    ] > 0
    assert setups["setup_c"]["cases"][0]["actual_state"] == "blocked"
    assert setups["setup_c"]["cases"][0]["audit"]["violations"][
        "capacity_overruns_count"
    ] == 0


def test_scripted_agent_uses_safe_defaults_but_clarifies_missing_requirements(
    tmp_path,
):
    results = run_evaluation.evaluate_prompts(
        [
            {
                "id": "complete",
                "category": "clean",
                "prompt": "Organize a cybersecurity CTF for 120 students with extension power strips.",
                "expected_result": "committed",
            },
            {
                "id": "ambiguous",
                "category": "ambiguous",
                "prompt": "Plan a campus event soon.",
                "expected_result": "adaptive_clarification",
            },
        ],
        results_path=tmp_path / "results.json",
    )

    setup_c = results["setups"]["setup_c"]
    assert setup_c["cases"][0]["actual_state"] == "committed"
    assert setup_c["cases"][1]["actual_state"] == "clarified"


def test_committed_but_invalid_final_data_is_a_wrong_state_and_missed_error(
    tmp_path,
):
    results = run_evaluation.evaluate_prompts(
        [
            {
                "id": "capacity-data",
                "category": "clean",
                "prompt": "Book Seminar Hall 2 for 100 students for a seminar tomorrow.",
                "expected_result": "committed",
            }
        ],
        results_path=tmp_path / "results.json",
    )

    setup_a = results["setups"]["setup_a"]
    assert setup_a["cases"][0]["actual_state"] == "violated"
    assert setup_a["wrong_final_states"] > 0
    assert setup_a["errors_missed"] > 0
