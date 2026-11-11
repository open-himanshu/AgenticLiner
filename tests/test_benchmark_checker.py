"""Tests for the independent benchmark checker and honest SQL baseline (Setup B)."""

from __future__ import annotations

import ast
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from eval.benchmark import run_evaluation
from eval.benchmark.independent_checker import IndependentDBChecker

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "eval" / "benchmark" / "independent_checker.py"
BASELINE_SCHEMA_PATH = ROOT / "eval" / "benchmark" / "schema_baseline.sql"


def _create_handmade_db(db_path: Path) -> sqlite3.Connection:
    """Create a small, self-contained SQLite DB matching core schema tables."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            brief TEXT NOT NULL,
            event_type TEXT DEFAULT 'general',
            expected_participants INTEGER DEFAULT 100,
            budget REAL NOT NULL DEFAULT 0,
            status TEXT DEFAULT 'planned'
        );
        CREATE TABLE rooms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            capacity INTEGER NOT NULL
        );
        CREATE TABLE speakers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE resources (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            stock INTEGER NOT NULL DEFAULT 1,
            allocated_stock INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            title TEXT NOT NULL,
            speaker_id TEXT,
            room_id TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            expected_attendance INTEGER DEFAULT 50,
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
            FOREIGN KEY(room_id) REFERENCES rooms(id),
            FOREIGN KEY(speaker_id) REFERENCES speakers(id)
        );
        CREATE TABLE bookings (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            resource_id TEXT,
            room_id TEXT,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            quantity INTEGER DEFAULT 1,
            status TEXT DEFAULT 'confirmed',
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
        );
        CREATE TABLE outbox (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'held',
            FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
        );
        """
    )
    return conn


def _seed_clean_entities(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO rooms (id, name, capacity) VALUES ('r1', 'Hall 1', 100)")
    conn.execute("INSERT INTO rooms (id, name, capacity) VALUES ('r2', 'Hall 2', 80)")
    conn.execute("INSERT INTO speakers (id, name) VALUES ('spk1', 'Dr. Ada')")
    conn.execute(
        "INSERT INTO resources (id, category, name, stock, allocated_stock) VALUES ('res_mic', 'equipment', 'Wireless Mic', 12, 2)"
    )
    conn.execute(
        "INSERT INTO events (id, name, brief, expected_participants, status) VALUES ('ev1', 'AI Talk', 'Brief', 60, 'allocated')"
    )
    conn.execute(
        """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, quantity, status)
           VALUES ('bk_room', 'ev1', 'r1', 'Hall 1', 'venue', '2026-12-01 09:00:00', '2026-12-01 12:00:00', 1, 'confirmed')"""
    )
    conn.execute(
        """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
           VALUES ('bk_mic', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-01 09:00:00', '2026-12-01 12:00:00', 2, 'confirmed')"""
    )
    conn.execute(
        """INSERT INTO sessions (id, event_id, title, speaker_id, room_id, start_time, end_time, expected_attendance)
           VALUES ('s1', 'ev1', 'Morning Session', 'spk1', 'r1', '2026-12-01 09:00:00', '2026-12-01 10:30:00', 60)"""
    )
    conn.execute(
        """INSERT INTO sessions (id, event_id, title, speaker_id, room_id, start_time, end_time, expected_attendance)
           VALUES ('s2', 'ev1', 'Late Session', 'spk1', 'r2', '2026-12-01 10:30:00', '2026-12-01 12:00:00', 50)"""
    )
    conn.execute(
        """INSERT INTO outbox (id, event_id, recipient, subject, message, status)
           VALUES ('msg1', 'ev1', 'user@example.invalid', 'Confirmed', 'Booked.', 'sent')"""
    )
    conn.commit()


def test_checker_does_not_import_kavach():
    source = CHECKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(
        "kavach" in mod.lower() or "safety" in mod.lower()
        for mod in imported_modules
    )

    code = (
        "import sys; "
        "import eval.benchmark.independent_checker; "
        "loaded = [m for m in sys.modules if 'kavach' in m.lower() or 'safety' in m.lower()]; "
        "assert not loaded, loaded"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_checker_clean_database_has_no_violations(tmp_path):
    db_path = tmp_path / "clean.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is True
    assert all(count == 0 for count in report["violations"].values())


def test_checker_flags_venue_overlap(tmp_path):
    db_path = tmp_path / "overlap.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            "INSERT INTO events (id, name, brief, expected_participants, status) VALUES ('ev2', 'Parallel Event', 'Brief', 50, 'allocated')"
        )
        conn.execute(
            """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_overlap', 'ev2', 'r1', 'Hall 1', 'venue', '2026-12-01 11:00:00', '2026-12-01 14:00:00', 1, 'confirmed')"""
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["room_overlaps_count"] == 1


def test_checker_flags_headcount_above_room_capacity(tmp_path):
    db_path = tmp_path / "capacity.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            "INSERT INTO events (id, name, brief, expected_participants, status) VALUES ('ev_big', 'Huge Event', 'Brief', 200, 'allocated')"
        )
        conn.execute(
            """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_big', 'ev_big', 'r2', 'Hall 2', 'venue', '2026-12-02 09:00:00', '2026-12-02 12:00:00', 1, 'confirmed')"""
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["capacity_overruns_count"] >= 1


def test_checker_flags_single_booking_equipment_oversell(tmp_path):
    db_path = tmp_path / "oversell_single.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_mics_too_many', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-03 09:00:00', '2026-12-03 12:00:00', 80, 'confirmed')"""
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["stock_violations_count"] >= 1


def test_checker_flags_concurrent_equipment_oversell_but_allows_non_overlapping(tmp_path):
    db_clean = tmp_path / "non_overlapping_stock.sqlite3"
    conn = _create_handmade_db(db_clean)
    try:
        _seed_clean_entities(conn)
        conn.execute("UPDATE resources SET allocated_stock = 0")
        conn.execute("DELETE FROM bookings WHERE id = 'bk_mic'")
        conn.execute(
            """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_day1', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-04 09:00:00', '2026-12-04 12:00:00', 8, 'confirmed')"""
        )
        conn.execute(
            """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_day2', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-05 09:00:00', '2026-12-05 12:00:00', 8, 'confirmed')"""
        )
        conn.commit()
    finally:
        conn.close()

    clean_report = IndependentDBChecker().run_full_audit(db_clean)
    assert clean_report["audit_passed"] is True
    assert clean_report["violations"]["stock_violations_count"] == 0

    db_clash = tmp_path / "overlapping_stock.sqlite3"
    conn2 = _create_handmade_db(db_clash)
    try:
        _seed_clean_entities(conn2)
        conn2.execute("UPDATE resources SET allocated_stock = 0")
        conn2.execute("DELETE FROM bookings WHERE id = 'bk_mic'")
        conn2.execute(
            """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_concurrent_1', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-04 09:00:00', '2026-12-04 12:00:00', 8, 'confirmed')"""
        )
        conn2.execute(
            """INSERT INTO bookings (id, event_id, resource_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_concurrent_2', 'ev1', 'res_mic', 'Wireless Mic', 'resource', '2026-12-04 11:00:00', '2026-12-04 14:00:00', 8, 'confirmed')"""
        )
        conn2.commit()
    finally:
        conn2.close()

    clash_report = IndependentDBChecker().run_full_audit(db_clash)
    assert clash_report["audit_passed"] is False
    assert clash_report["violations"]["stock_violations_count"] >= 1


def test_checker_flags_stock_below_zero(tmp_path):
    db_path = tmp_path / "negative_stock.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            "INSERT INTO resources (id, category, name, stock, allocated_stock) VALUES ('res_neg', 'equipment', 'Standee', -1, 0)"
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["stock_violations_count"] >= 1


def test_checker_flags_speaker_in_two_overlapping_sessions(tmp_path):
    db_path = tmp_path / "speaker_clash.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            """INSERT INTO sessions (id, event_id, title, speaker_id, room_id, start_time, end_time, expected_attendance)
               VALUES ('s_clash', 'ev1', 'Parallel Keynote', 'spk1', 'r2', '2026-12-01 09:30:00', '2026-12-01 10:15:00', 40)"""
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["speaker_clashes_count"] == 1


def test_checker_flags_sent_notice_without_committed_booking(tmp_path):
    db_path = tmp_path / "outbox_without_booking.sqlite3"
    conn = _create_handmade_db(db_path)
    try:
        _seed_clean_entities(conn)
        conn.execute(
            "INSERT INTO events (id, name, brief, expected_participants, status) VALUES ('ev_unbooked', 'Unbooked Event', 'Brief', 40, 'allocated')"
        )
        conn.execute(
            """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, quantity, status)
               VALUES ('bk_rolled', 'ev_unbooked', 'r2', 'Hall 2', 'venue', '2026-12-06 09:00:00', '2026-12-06 12:00:00', 1, 'rolled_back')"""
        )
        conn.execute(
            """INSERT INTO outbox (id, event_id, recipient, subject, message, status)
               VALUES ('msg_leaked', 'ev_unbooked', 'user@example.invalid', 'Confirmed', 'Should not be sent.', 'sent')"""
        )
        conn.commit()
    finally:
        conn.close()

    report = IndependentDBChecker().run_full_audit(db_path)
    assert report["audit_passed"] is False
    assert report["violations"]["outbox_leaks_count"] == 1


def test_setup_b_uses_plain_sql_baseline_without_kavach(tmp_path):
    assert BASELINE_SCHEMA_PATH.exists(), "schema_baseline.sql must exist"
    sql_text = BASELINE_SCHEMA_PATH.read_text(encoding="utf-8")
    assert "kavach" not in sql_text.lower()
    assert "--" in sql_text

    db_path = tmp_path / "baseline.sqlite3"
    run_evaluation.create_scenario_database(db_path, setup="setup_b")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        # 1. Trigger rejects overlapping bookings for same room
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, status)
                   VALUES ('bk_overlap', 'ev_001', 'room_audi_a', 'Main Audi', 'venue', '2026-11-25 10:00:00', '2026-11-25 12:00:00', 'confirmed')"""
            )

        # 2. Trigger rejects headcount above room capacity
        conn.execute(
            "INSERT INTO events (id, name, brief, expected_participants, status) VALUES ('ev_over', 'Too Big', 'Brief', 200, 'planned')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, status)
                   VALUES ('bk_over', 'ev_over', 'room_comp_lab', 'Lab 4', 'venue', '2026-12-10 09:00:00', '2026-12-10 12:00:00', 'confirmed')"""
            )

        # 3. CHECK(stock >= 0) rejects negative equipment stock
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO resources (id, category, name, stock) VALUES ('res_bad', 'equipment', 'Bad Mic', -1)"
            )

        # 4. CHECK(end > start) rejects invalid booking time windows
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO bookings (id, event_id, room_id, item_name, category, start_time, end_time, status)
                   VALUES ('bk_bad_time', 'ev_001', 'room_conf_room', 'Conf', 'venue', '2026-12-11 12:00:00', '2026-12-11 10:00:00', 'confirmed')"""
            )
    finally:
        conn.close()


def test_setup_b_evaluate_case_blocks_overlap_and_capacity_without_orphans(tmp_path):
    overlap_prompt = {
        "id": "b-overlap",
        "category": "high_conflict",
        "prompt": "Book Main Auditorium at the exact same hour as an already confirmed keynote.",
        "expected_result": "rolled_back_overlap",
    }
    capacity_prompt = {
        "id": "b-capacity",
        "category": "high_conflict",
        "prompt": "Book Computing Lab (capacity 45) for 250 students.",
        "expected_result": "rolled_back_capacity",
    }

    for idx, prompt in enumerate((overlap_prompt, capacity_prompt)):
        db_a = tmp_path / f"a-{idx}.sqlite3"
        _, measured_a = run_evaluation._evaluate_case(
            prompt, "setup_a", db_a, None, None, False
        )
        db_b = tmp_path / f"b-{idx}.sqlite3"
        case_b, measured_b = run_evaluation._evaluate_case(
            prompt, "setup_b", db_b, measured_a["plan"], None, False
        )
        assert case_b["actual_state"] == "error"
        assert measured_b["execution"]["status"] == "error"
        assert case_b["audit"]["audit_passed"] is True
        assert case_b["audit"]["violations"]["orphan_events_count"] == 0
