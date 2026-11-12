"""
Unit tests for Module 6: Automated Feedback Intelligence Engine.
"""
import pytest
from backend.modules.module6_feedback.analyzer import FeedbackAnalyzer
from backend.core.database.demo_people import HERO_SPEAKER

def test_sentiment_analysis():
    analyzer = FeedbackAnalyzer()

    pos_res = analyzer.analyze_sentiment("The PyTorch hands-on session was amazing and very informative!")
    assert pos_res["sentiment"] == "positive"
    assert pos_res["score"] > 0

    neg_res = analyzer.analyze_sentiment("The room was crowded, projector had an issue and AC was broken.")
    assert neg_res["sentiment"] == "negative"
    assert neg_res["score"] < 0

def test_negation_and_hinglish_sentiment():
    analyzer = FeedbackAnalyzer()

    # Negation inversion: "not bad" should not be negative
    not_bad = analyzer.analyze_sentiment("The keynote was not bad at all, actually quite decent.")
    assert not_bad["sentiment"] == "positive"
    assert not_bad["score"] > 0

    # Negated positive: "not good" should be negative
    not_good = analyzer.analyze_sentiment("The mic was not good, audio was unclear.")
    assert not_good["sentiment"] == "negative"
    assert not_good["score"] < 0

    # Hinglish expressions
    hinglish_pos = analyzer.analyze_sentiment("Maza aa gaya, session bohot badhiya tha!")
    assert hinglish_pos["sentiment"] == "positive"

    hinglish_neg = analyzer.analyze_sentiment("Bilkul bakwas arrangement, time waste ho gaya.")
    assert hinglish_neg["sentiment"] == "negative"

def test_thematic_detection():
    analyzer = FeedbackAnalyzer()

    themes_infra = analyzer.detect_themes("The AC was off and sound in the audi was too low.")
    assert "venue" in themes_infra

    themes_food = analyzer.detect_themes("Loved the lunch boxes and tea refreshments.")
    assert "hospitality" in themes_food

def test_batch_feedback_aggregation():
    analyzer = FeedbackAnalyzer()
    sample_comments = [
        {"id": 1, "comment": f"Great session, learned a lot from {HERO_SPEAKER['name']}!", "rating": 5},
        {"id": 2, "comment": "Food was delayed and water was not available.", "rating": 2},
        {"id": 3, "comment": "Excellent coding contest and well organized.", "rating": 5},
        {"id": 4, "comment": "Projector screen was blurry in the seminar hall.", "rating": 2}
    ]

    report = analyzer.analyze_batch(sample_comments)
    assert report["total_feedbacks"] == 4
    assert report["sentiment_distribution"]["positive"] == 2
    assert report["sentiment_distribution"]["negative"] == 2
    assert len(report["top_strengths"]) >= 1
    assert len(report["top_concerns"]) >= 1
    assert "venue" in report["theme_counts"]
    assert "hospitality" in report["theme_counts"]
