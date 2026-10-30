from datetime import date, timedelta

from backend.planner import test_tool_calling as planner


def test_rejected_planner_booking_leaves_database_business_state_unchanged(
    monkeypatch,
):
    connection = planner.create_demo_checkout_database()
    monkeypatch.setattr(planner, "CHECKOUT_CONNECTION", connection)
    request = {
        "venue_id": "STG-C",
        "date": (date.today() + timedelta(days=1)).isoformat(),
        "start_hour": 18,
        "end_hour": 20,
        "equipment": {"stage lights": 9},
        "headcount": 150,
    }

    def business_state():
        return (
            connection.execute(
                "SELECT * FROM bookings ORDER BY id"
            ).fetchall(),
            connection.execute(
                "SELECT * FROM equipment ORDER BY name"
            ).fetchall(),
            connection.execute(
                "SELECT * FROM outbox ORDER BY id"
            ).fetchall(),
        )

    try:
        before = business_state()

        result = planner.book_items(**request)

        assert result["status"] == "rejected"
        assert business_state() == before
        assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
    finally:
        connection.close()
