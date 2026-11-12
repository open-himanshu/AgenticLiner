"""
Unit & Integration Tests for Pillar 4: Netflix / Flipkart-Style Historical Recommendation Engine.
Tests:
1. Nearest-Neighbor Event Blueprint Matching (Netflix-style vector distance & match %).
2. Market Basket Association Mining (Flipkart-style Frequently Booked Together items).
3. Curated Turnkey Logistics Bundles synthesis.
4. Kavach budget guardrail filtering on recommendations.
5. Dialogue Engine bundle fusion.
6. REST API endpoints (/api/autopilot/recommendations & /apply-bundle).
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.planner.recommendation_engine import (
    find_similar_historical_events,
    compute_frequently_booked_together,
    synthesize_turnkey_bundles,
    generate_campus_recommendations,
)
from backend.core.planner.dialogue_engine import (
    get_or_create_session,
    fuse_dialogue_reply,
    reset_session,
)
from conftest import TEST_PASSWORDS


def _organiser_client() -> TestClient:
    """Helper returning authenticated TestClient for organiser."""
    client = TestClient(app)
    res = client.post(
        "/login",
        json={
            "email": "organiser@galgotias.edu",
            "password": TEST_PASSWORDS["ORGANISER_PASSWORD"],
        },
    )
    assert res.status_code == 200
    return client


def test_nearest_neighbor_historical_event_match():
    """Verifies Netflix-style blueprint matching against past campus events."""
    # Match a medium scale hackathon
    match_hack = find_similar_historical_events(event_type="hackathon", headcount=150, duration_hours=24.0)
    assert match_hack is not None
    assert match_hack.event_type == "hackathon"
    assert match_hack.match_percentage >= 80
    assert match_hack.student_rating >= 4.5
    assert "Technojam" in match_hack.title or "RoboWars" in match_hack.title

    # Match a cultural fest
    match_cult = find_similar_historical_events(event_type="cultural", headcount=250, duration_hours=4.0)
    assert match_cult is not None
    assert match_cult.event_type == "cultural"
    assert "Cultural Fest" in match_cult.title
    assert match_cult.match_percentage >= 85


def test_frequently_booked_together_association_mining():
    """Verifies Flipkart-style Frequently Booked Together items with confidence and social proof."""
    fbt_items = compute_frequently_booked_together(
        event_type="hackathon",
        headcount=120,
        current_items=["Wireless Handheld Mic Set (Pair)"]  # already has mic
    )
    assert len(fbt_items) >= 2

    # Verify that Extension Spike Boards is top recommended and mic is excluded
    item_names = [i.item_name for i in fbt_items]
    assert "Heavy Duty Extension Spike Boards" in item_names
    assert "Wireless Handheld Mic Set (Pair)" not in item_names

    top_item = next(i for i in fbt_items if i.resource_id == "res_ext_boards")
    assert top_item.confidence_score >= 0.90
    assert "hackathon" in top_item.social_proof.lower()
    assert top_item.total_cost > 0


def test_synthesize_turnkey_bundles():
    """Verifies generation of curated 1-click packages for specific event formats."""
    # Hackathon Bundle
    hack_bundles = synthesize_turnkey_bundles(event_type="hackathon", headcount=150)
    assert len(hack_bundles) >= 1
    power_bundle = next((b for b in hack_bundles if "Power" in b.bundle_name), None)
    assert power_bundle is not None
    assert power_bundle.confidence_score >= 0.90
    assert power_bundle.match_percentage >= 90
    assert len(power_bundle.items) >= 2

    # Cultural Bundle
    cult_bundles = synthesize_turnkey_bundles(event_type="cultural", headcount=200)
    stage_bundle = next((b for b in cult_bundles if "Stage" in b.bundle_name or "Cultural" in b.bundle_name), None)
    assert stage_bundle is not None
    assert any("Sound" in i.item_name for i in stage_bundle.items)
    assert any("LED" in i.item_name for i in stage_bundle.items)


def test_budget_guardrail_filters_expensive_bundles():
    """Verifies that Kavach budget limits mark oversized bundles as exceeding budget."""
    # Strict low budget of ₹500
    bundles = synthesize_turnkey_bundles(
        event_type="cultural",
        headcount=200,
        budget_limit=500.0,
        current_allocated_cost=0.0
    )
    assert len(bundles) >= 1
    # Grand stage pack costs > ₹5,000, so it must be marked fits_budget=False
    stage_bundle = bundles[0]
    assert stage_bundle.fits_budget is False

    # FBT items should also filter out items exceeding remaining ₹500
    fbt = compute_frequently_booked_together(
        event_type="cultural",
        headcount=200,
        budget_limit=500.0,
        current_allocated_cost=0.0
    )
    for item in fbt:
        assert item.total_cost <= 500.0


def test_dialogue_integration_recognizes_bundle_phrasing():
    """Verifies that saying 'add power bundle' in dialogue merges turnkey items into the brief."""
    session, _ = get_or_create_session(
        prompt="Hackathon karwana hai this Friday",
        user_id="test_rec_user"
    )

    # User replies adding the turnkey bundle
    session = fuse_dialogue_reply(session, "Please add the hackathon power bundle and 100 students")

    requested = session.accumulated_entities.requested_items
    assert any("Extension" in i for i in requested)
    assert any("Projector" in i for i in requested)
    assert any("bundle" in a.lower() for a in session.assumptions_made)

    reset_session(session.session_id)


def test_recommendation_api_endpoints():
    """Verifies POST /api/autopilot/recommendations & /apply-bundle endpoints with auth."""
    client = _organiser_client()

    # 1. Fetch recommendations
    res_rec = client.post(
        "/api/autopilot/recommendations",
        json={
            "event_type": "hackathon",
            "headcount": 150,
            "duration_hours": 24.0,
            "budget_limit": 50000.0
        }
    )
    assert res_rec.status_code == 200
    data_rec = res_rec.json()
    assert data_rec["success"] is True
    recs = data_rec["recommendations"]
    assert recs["matched_event"] is not None
    assert len(recs["curated_bundles"]) >= 1
    assert len(recs["individual_fbt"]) >= 1
    assert "conversational_pitch" in recs

    # 2. Apply bundle
    res_apply = client.post(
        "/api/autopilot/recommendations/apply-bundle",
        json={
            "bundle_id": "bundle_hackathon_power",
            "event_type": "hackathon",
            "headcount": 150
        }
    )
    assert res_apply.status_code == 200
    data_apply = res_apply.json()
    assert data_apply["success"] is True
    assert "Hackathon Developer & Power Pack" in data_apply["bundle_applied"]
    assert len(data_apply["items_added"]) >= 2
