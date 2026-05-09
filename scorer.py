"""AI relevance scoring for Reddit mentions.

Analyzes each mention and determines if it's a lead, complaint, or noise.
Returns a relevance score (0-1) and classification.
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("signalseek.scorer")


@dataclass
class ScoreResult:
    relevance_score: float  # 0.0 to 1.0
    is_lead: bool
    lead_reason: str
    category: str  # lead, complaint, question, noise, competitor_mention


# Heuristic scoring based on text patterns — no API key needed for MVP
LEAD_PATTERNS = {
    "seeking_tool": [
        "looking for", "any recommendations", "suggest me", "recommend me",
        "need a tool", "any tool", "best tool", "best app", "which tool",
        "alternatives to", "alternative to", "anyone know", "help me find",
        "where can i find", "how do i", "is there a", "any app",
    ],
    "frustrated_with_competitor": [
        "tired of", "frustrated with", "sucks", "doesn't work", "too expensive",
        "switching from", "looking to switch", "not happy with", "disappointed",
        "garbage", "terrible", "hate", "worst", "never works",
    ],
    "buying_intent": [
        "worth it", "worth the money", "is it worth", "pricing", "how much",
        "free tier", "free plan", "vs", "compared to", "review", "honest review",
    ],
}

COMPLAINT_PATTERNS = [
    "bug", "broken", "error", "crash", "doesn't work", "glitch",
    "issue", "problem", "fix", "please fix", "when will you",
]

QUESTION_PATTERNS = [
    "how do i", "how to", "can someone", "does anyone", "question",
    "?", "help", "confused",
]


def score_mention(title: str, text: str, keyword: str = "",
                  subreddit: str = "", author: str = "", source: str = "") -> ScoreResult:
    """Score a mention for relevance as a lead.

    Uses heuristic pattern matching (no external API required for MVP).
    Designed to filter noise from signal.
    """
    content = f"{title} {text}".lower()
    title_lower = title.lower()

    # Track which patterns matched
    lead_signals = 0
    total_signal_weight = 0
    reasons = []
    category = "noise"

    # Check lead patterns
    for category_name, patterns in LEAD_PATTERNS.items():
        for pattern in patterns:
            if pattern in content:
                weight = 2.0 if pattern in title_lower else 1.0
                total_signal_weight += weight
                lead_signals += 1
                if category_name == "seeking_tool":
                    category = "lead"
                    reasons.append(f"seeking tool: '{pattern}'")
                elif category_name == "frustrated_with_competitor":
                    category = "competitor_mention"
                    reasons.append(f"frustrated: '{pattern}'")
                elif category_name == "buying_intent":
                    category = "lead"
                    reasons.append(f"buying intent: '{pattern}'")

    # Check complaints
    for pattern in COMPLAINT_PATTERNS:
        if pattern in content:
            if category == "noise":
                category = "complaint"
            reasons.append(f"complaint signal: '{pattern}'")
            total_signal_weight += 1.0
            break

    # Check questions
    for pattern in QUESTION_PATTERNS:
        if pattern in content:
            if category == "noise":
                category = "question"
            total_signal_weight += 1.0
            break

    # Calculate score based on signal weight
    # More signals = higher score, capped at 1.0
    if total_signal_weight == 0:
        relevance_score = 0.05  # Almost certainly noise
    elif total_signal_weight <= 1.0:
        relevance_score = 0.3
    elif total_signal_weight <= 2.0:
        relevance_score = 0.5
    elif total_signal_weight <= 4.0:
        relevance_score = 0.7
    else:
        relevance_score = min(0.95, 0.7 + (total_signal_weight - 4) * 0.05)

    # Boost: title contains keyword directly
    if keyword and keyword.lower() in title_lower:
        relevance_score = min(1.0, relevance_score + 0.15)

    # Penalty: StackOverflow bug reports aren't leads
    if subreddit == "StackOverflow" and category == "lead":
        # Check if it's really a tool recommendation vs a bug report
        bug_signals = ["error:", "traceback", "exception", "stack trace",
                       "undefined is not", "cannot read", "null pointer",
                       "segfault", "syntax error", "type error",
                       "npm install", "pip install", "package.json",
                       ".config", "docker compose", "kubernetes",
                       "http status", "status code"]
        bug_count = sum(1 for s in bug_signals if s in content)
        if bug_count >= 1:
            relevance_score = min(relevance_score, 0.3)
            category = "noise"

    is_lead = category == "lead" and relevance_score >= 0.5

    reason_str = "; ".join(reasons[:3]) if reasons else "no lead signals detected"

    return ScoreResult(
        relevance_score=round(relevance_score, 2),
        is_lead=is_lead,
        lead_reason=reason_str,
        category=category,
    )


def score_and_update_mentions(db_path: str = None) -> int:
    """Score all unscored mentions in the database."""
    import sqlite3
    import os
    if db_path is None:
        db_path = os.path.expanduser("~/.signalseek/signalseek.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    mentions = conn.execute("""
        SELECT m.*, k.keyword FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        WHERE m.relevance_score IS NULL
        ORDER BY m.found_at DESC
        LIMIT 200
    """).fetchall()

    scored = 0
    for m in mentions:
        result = score_mention(
            title=m["title"] or "",
            text=m["text"] or "",
            keyword=m["keyword"] or "",
            subreddit=m["subreddit"] or "",
            author=m["author"] or "",
        )

        conn.execute("""
            UPDATE mentions
            SET relevance_score = ?, is_lead = ?, lead_reason = ?
            WHERE id = ?
        """, (result.relevance_score, int(result.is_lead), result.lead_reason, m["id"]))
        scored += 1

    conn.commit()
    conn.close()
    logger.info(f"Scored {scored} mentions")
    return scored


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)

    # Demo scoring
    test_cases = [
        ("Looking for a tool to monitor Reddit mentions, any recommendations?",
         "I need something that can track keywords and alert me when my product is mentioned."),
        ("Just hit $10k MRR with my SaaS!",
         "Super excited to share this milestone with you all."),
        ("Tired of F5Bot sending me garbage alerts",
         "Half the alerts are totally irrelevant. Is there anything better?"),
        ("Check out this meme about programming",
         "lol so relatable [meme image]"),
    ]

    for title, text in test_cases:
        result = score_mention(title, text, keyword="monitor")
        print(f"Title: {title[:60]}...")
        print(f"  Score: {result.relevance_score} | Lead: {result.is_lead} | {result.category}")
        print(f"  Reason: {result.lead_reason}")
        print()
