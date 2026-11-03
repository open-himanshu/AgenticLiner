"""
Module 6: Lexicon-Based Feedback Sentiment Scoring & Thematic Classifier
Implements:
1. Sentiment analysis with Negation Inversion and Hinglish support
2. Thematic classification (Venue/Infra, Speaker/Content, Food/Hospitality, Organization)
3. Actionable executive insights summary (Strengths, Weaknesses, Improvements)
"""

from typing import List, Dict, Any, Optional
import re

THEME_KEYWORDS = {
    "venue": [
        "room", "audi", "hall", "seat", "ac", "air conditioning", "projector", "screen",
        "mic", "sound", "speaker system", "stage", "lighting", "kamra", "thand", "garmi",
        "seating", "ventilation"
    ],
    "content": [
        "topic", "workshop", "pytorch", "code", "lecture", "presentation", "hands-on",
        "learning", "knowledge", "session", "tutorial", "depth", "content", "speaker",
        "slides", "concept"
    ],
    "hospitality": [
        "food", "lunch", "refreshment", "snack", "tea", "coffee", "water", "juice",
        "buffet", "meal", "khana", "chai", "nashta", "paani"
    ],
    "organization": [
        "time", "delay", "registration", "queue", "volunteer", "management", "coordinator",
        "schedule", "certificate", "start", "end", "bheed", "line", "entry", "crowd"
    ]
}

NEGATION_WORDS = {
    "not", "no", "never", "hardly", "barely", "scarcely", "neither", "nor", "without",
    "dont", "don't", "doesnt", "doesn't", "didnt", "didn't", "isnt", "isn't",
    "arent", "aren't", "wasnt", "wasn't", "werent", "weren't", "wont", "won't",
    "cant", "can't"
}

POSITIVE_WORDS = {
    "great", "excellent", "awesome", "good", "loved", "enjoyed", "smooth", "informative", "helpful", "amazing",
    "clear", "insightful", "best", "satisfied", "well", "fantastic", "superb", "brilliant", "outstanding", "impressive",
    "perfect", "nice", "decent", "punctual", "valuable", "inspiring", "engaging", "productive",
    # Hinglish
    "badhiya", "mast", "shaandar", "zabardast", "lajawab", "gazab", "accha", "achha", "sahi"
}

NEGATIVE_WORDS = {
    "bad", "terrible", "poor", "issue", "problem", "broken", "delay", "delayed", "late", "crowded", "suffocating",
    "inaudible", "cold", "hot", "waste", "disappointed", "low", "worst", "mess", "slow", "fail", "failed", "shortage",
    "blurry", "unclear", "noisy", "glitch", "confusing", "horrible", "difficult", "pathetic", "disaster", "cramped",
    "rushed", "bekaar", "bakwas", "kharab", "pareshan", "ghatiya", "kachra", "boring", "faltu", "ganda"
}

SPECIAL_PHRASES = {
    "not bad": 0.5,
    "theek thak": 0.2,
    "time waste": -1.0,
    "maza aa gaya": 1.0,
    "no problem": 0.5,
    "no issue": 0.5,
    "without any issue": 1.0,
    "without any delay": 1.0,
}

class FeedbackAnalyzer:
    def __init__(self):
        pass

    def analyze_sentiment(self, text: str, rating: Optional[int] = None) -> Dict[str, Any]:
        """
        Classifies text sentiment into positive, neutral, or negative,
        supporting negation inversion (e.g. 'not bad', 'not good') and Hinglish expressions.
        """
        text_lower = text.lower()
        pos_hits = 0.0
        neg_hits = 0.0

        # 1. Check special phrases
        for phrase, val in SPECIAL_PHRASES.items():
            if phrase in text_lower:
                if val > 0:
                    pos_hits += val
                else:
                    neg_hits += abs(val)

        # 2. Token-level analysis with negation lookback
        tokens = re.findall(r"[a-z']+", text_lower)
        for i, tok in enumerate(tokens):
            is_negated = False
            if i > 0 and tokens[i-1] in NEGATION_WORDS:
                is_negated = True
            elif i > 1 and tokens[i-2] in NEGATION_WORDS:
                is_negated = True

            if tok in POSITIVE_WORDS:
                if is_negated:
                    neg_hits += 1.0
                else:
                    pos_hits += 1.0
            elif tok in NEGATIVE_WORDS:
                if is_negated:
                    pos_hits += 0.5
                else:
                    neg_hits += 1.0

        score = pos_hits - neg_hits
        if rating is not None:
            if rating >= 4:
                score += 1.0
            elif rating <= 2:
                score -= 1.0

        if score > 0:
            sentiment = "positive"
        elif score < 0:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        normalized_score = max(-1.0, min(1.0, score / max(1.0, (pos_hits + neg_hits + (1.0 if rating else 0.0)))))

        return {
            "sentiment": sentiment,
            "score": float(round(normalized_score, 2)),
            "positive_hits": int(pos_hits),
            "negative_hits": int(neg_hits)
        }

    def detect_themes(self, text: str) -> List[str]:
        """Detects operational event themes mentioned in the feedback comment."""
        text_lower = text.lower()
        matched_themes = []
        for theme, kws in THEME_KEYWORDS.items():
            for kw in kws:
                if kw in text_lower:
                    matched_themes.append(theme)
                    break
        return matched_themes or ["general"]

    def analyze_batch(self, comments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyzes a batch of feedback comments and compiles comprehensive metrics:
        - Sentiment distribution
        - Theme breakdowns
        - Key strengths & critical concerns
        """
        total = len(comments)
        if total == 0:
            return {
                "total_feedbacks": 0,
                "sentiment_distribution": {"positive": 0, "neutral": 0, "negative": 0},
                "theme_counts": {},
                "strengths": [],
                "concerns": []
            }

        sent_counts = {"positive": 0, "neutral": 0, "negative": 0}
        theme_counts = {}
        analyzed_items = []

        for c in comments:
            raw_text = c.get("comment", "")
            rating = c.get("rating")
            sent = self.analyze_sentiment(raw_text, rating=rating)
            themes = self.detect_themes(raw_text)

            sent_counts[sent["sentiment"]] += 1
            for t in themes:
                theme_counts[t] = theme_counts.get(t, 0) + 1

            analyzed_items.append({
                "id": c.get("id"),
                "rating": c.get("rating"),
                "comment": raw_text,
                "sentiment": sent["sentiment"],
                "score": sent["score"],
                "themes": themes
            })

        # Synthesize Strengths and Concerns
        strengths = []
        concerns = []

        for item in analyzed_items:
            if item["sentiment"] == "positive" and item.get("rating", 3) >= 4:
                strengths.append(item["comment"])
            elif item["sentiment"] == "negative" or item.get("rating", 3) <= 2:
                concerns.append(item["comment"])

        return {
            "total_feedbacks": total,
            "sentiment_distribution": sent_counts,
            "positive_ratio": round(sent_counts["positive"] / total, 2),
            "theme_counts": theme_counts,
            "top_strengths": strengths[:4],
            "top_concerns": concerns[:4],
            "analyzed_items": analyzed_items
        }
