"""AI relevance scoring for monitored mentions.

A source-aware, context-aware heuristic scoring engine that distinguishes
real leads from noise with high precision. Works across HackerNews,
StackExchange, and other sources without external API dependencies.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("signalseek.scorer")


@dataclass
class ScoreResult:
    relevance_score: float  # 0.0 to 1.0
    is_lead: bool
    lead_reason: str
    category: str  # lead, complaint, question, noise, competitor_mention


# ================================================================
# SIGNAL DETECTION PATTERNS
# ================================================================
# Each signal group has: patterns (list of regex patterns),
# weight (positive = lead signal, negative = noise/penalty),
# category (what category to assign if matched)

LEAD_SIGNALS = [
    # --- High-value seeking/intent signals ---
    {
        "name": "seeking_tool",
        "patterns": [
            r"\brecommend(?:\s+me)?\b",
            r"\bwhat\s+(?:do|does|are)\s+you\s+(?:use|using|recommend)\s+for\b",
            r"\bhas\s+anyone\s+(?:tried|used|compared)\b",
            r"\bcomparing\s+\w+\s+(?:vs|versus|and|&)\b",
            r"\bswitched?\s+from\s+\w+\s+to\b",
            r"\b(?:looking|searching|hunting)\s+for\b",
            r"\b(?:any|need|seeking)\s+(?:recommendations?|suggestions?|alternatives?)\b",
            r"\bsuggest\s+(?:me|a|some|any)\b",
            r"\b(?:best|better|top|favorite)\s+(?:tool|app|service|software|platform|solution)\b",
            r"\bwhich\s+(?:tool|app|service|software|platform|solution)\b",
            r"\bhelp\s+me\s+(?:find|choose|decide|pick)\b",
            r"\bwhere\s+(?:can|do)\s+(?:I|you|we)\s+find\b",
            r"\bis\s+there\s+(?:a|an|any)\s+(?:tool|app|service|software|alternative)\b",
            r"\banyone\s+(?:know|using|familiar)\b",
            r"\b(?:opinions?|thoughts?|experiences?)\s+(?:on|about|with)\s+\w",
        ],
        "weight": 2.5,
        "category": "lead",
    },
    {
        "name": "frustration_with_competitor",
        "patterns": [
            r"\b(?:tired|sick|fed\s+up)\s+(?:of|with)\b",
            r"\bfrustrated\s+(?:with|by)\b",
            r"\b(?:sucks|horrible|terrible|garbage|awful|worst|hate)\b",
            r"\bswitching\s+(?:from|away\s+from)\b",
            r"\b(?:looking|want|trying)\s+to\s+switch\b",
            r"\bnot\s+happy\s+with\b",
            r"\bdisappointed\s+(?:with|in|by)\b",
            r"\bnever\s+works?\b",
            r"\b(?:migrating|moving)\s+(?:away\s+)?from\b",
            r"\b(?:ditch|ditching|drop|dropping)\s+\w+\s+(?:for|in\s+favor)",
        ],
        "weight": 2.0,
        "category": "competitor_mention",
    },
    {
        "name": "buying_intent",
        "patterns": [
            r"\b(?:is\s+it\s+)?worth\s+(?:it|the\s+money|the\s+price|paying\s+for)\b",
            r"\bpricing\b",
            r"\bhow\s+much\s+(?:is|does|do)\b",
            r"\b(?:free|cheap|affordable)\s+(?:alternative|option|version|tier|plan)\b",
            r"\bcheaper\s+than\b",
            r"\b(?:vs|versus|compared?\s+to|alternative\s+to)\b",
            r"\b(?:honest\s+)?review\b",
            r"\b(?:anyone|who)\s+(?:using|uses?|tried)\s+\w+\s*\?\s*$",
            r"\b(?:worth|good|decent)\s+(?:alternative|replacement|substitute)\b",
            r"\b(?:costs?|price|expensive|overpriced)\b",
            r"\b(?:paid|premium|enterprise)\s+(?:plan|tier|version|pricing)\b",
            r"\b(?:trial|demo|freemium)\b",
        ],
        "weight": 1.5,
        "category": "lead",
    },
    {
        "name": "urgency",
        "patterns": [
            r"\bneed\s+(?:this|it|one|something|a\s+solution)\s+(?:ASAP|urgently|now|immediately|soon|today|this\s+week)\b",
            r"\bdeadline\b",
            r"\blaunching\s+(?:next|this|in\s+a)\s+(?:week|month|quarter)\b",
            r"\b(?:need|want)\s+(?:to|a)\s+(?:buy|purchase|get|acquire)\b",
            r"\btime[\s-]sensitive\b",
            r"\b(?:evaluating|trialing|testing)\s+(?:currently|now|right\s+now)\b",
            r"\bmy\s+(?:boss|team|company)\s+(?:wants|needs|is\s+looking)\b",
            r"\b(?:ready|about)\s+to\s+(?:buy|pull\s+the\s+trigger|commit|sign\s+up)\b",
        ],
        "weight": 1.0,
        "category": "lead",
    },
]

NOISE_SIGNALS = [
    # --- Strong noise: error traces / technical debugging ---
    {
        "name": "error_trace",
        "patterns": [
            r"\b(?:traceback|stack\s+trace|backtrace)\b",
            r"\b(?:exception|TypeError|ValueError|KeyError|AttributeError|NameError|SyntaxError|RuntimeError|ImportError)\b",
            r"\b(?:segfault|segmentation\s+fault|core\s+dump|memory\s+leak)\b",
            r"\b(?:undefined\s+is\s+not|Cannot\s+read\s+property|uncaught\s+TypeError|null\s+pointer|nil\s+pointer)\b",
            r"\bError\s+(?:code|message|response|status)\b",
            r"\b(?:failed|failing|failure)\s+(?:with|due\s+to)\b.*\berror\b",
            r"\b(?:HTTP|http)\s+(?:4\d{2}|5\d{2})\b",
            r"\bstatus\s+code\s+\d{3}\b",
            r"\b(?:docker|kubernetes|k8s|helm)\s+(?:compose|deploy|install|error)\b",
            r"\b(?:\.config|config\.(?:json|yaml|yml|toml|js))\b",
        ],
        "weight": -4.0,
        "category": "complaint",
    },
    # --- Medium noise: bug reports / complaints about specific software issues ---
    {
        "name": "bug_report",
        "patterns": [
            r"\b(?:bug|bugs|buggy)\b",
            r"\bdoesn'?t\s+work\b",
            r"\b(?:broken|broke|breaking)\b",
            r"\b(?:glitch|glitches|glitchy)\b",
            r"\bplease\s+fix\b",
            r"\bwhen\s+(?:will|are)\s+you\b",
            r"\b(?:issue|issues|problem|problems)\s+(?:with|in)\b",
            r"\b(?:not\s+working|stopped\s+working)\b",
            r"\b(?:crash|crashing|crashes|crashed)\b",
            r"\b(?:unable|can'?t)\s+(?:to\s+)?(?:get|make|figure\s+out|install|run|start|connect)\b",
            r"\bhow\s+(?:do|can|would)\s+(?:I|you|we)\s+(?:fix|solve|resolve|debug|troubleshoot)\b",
            r"\bis\s+there\s+a\s+(?:fix|workaround|solution)\s+(?:for|to)\s+this\s+(?:bug|issue|problem|error)\b",
        ],
        "weight": -2.5,
        "category": "complaint",
    },
    # --- Light noise: trivial/low-effort questions ---
    {
        "name": "trivial_question",
        "patterns": [
            r"^\s*(?:how\s+(?:do|can|would|should)\s+(?:I|you|we))\b",
            r"\b(?:n00b|noob|newbie|beginner)\s+question\b",
            r"\b(?:anyone|someone)\s+(?:can|could|able\s+to)\s+(?:help|explain)\b",
            r"\bwhat\s+(?:is|are)\s+\w+\s*\?\s*$",
            r"\b(?:confused|don'?t\s+understand|makes?\s+no\s+sense)\b",
        ],
        "weight": -0.5,
        "category": "question",
    },
]

# ================================================================
# SOURCE-SPECIFIC BOOST / PENALTY RULES
# ================================================================

SOURCE_RULES = {
    "hackernews": {
        "high_points_threshold": 30,
        "high_points_boost": 0.12,
        "many_comments_threshold": 15,
        "many_comments_boost": 0.08,
        "ask_hn_title_pattern": r"^Ask\s+HN[:\s]",
        "ask_hn_boost": 0.10,
        "show_hn_penalty": -0.05,  # Show HN is self-promotion, not a lead
        "show_hn_title_pattern": r"^Show\s+HN[:\s]",
        "base_context_mult": 1.1,  # HN is generally higher quality context
    },
    "hn_jobs": {
        "high_points_threshold": 5,  # Jobs threads get less engagement
        "high_points_boost": 0.08,
        "many_comments_threshold": 5,
        "many_comments_boost": 0.10,
        "hiring_title_pattern": r"(?:hiring|freelancer?|looking\s+for|seeking|wanted:|who\s+is\s+hiring)",
        "hiring_boost": 0.25,  # Jobs threads are VERY likely leads
        "base_context_mult": 1.3,  # Jobs threads deserve high baseline
    },
    "stackexchange": {
        # StackExchange needs much more scrutiny
        "accepted_answer_boost": 0.05,  # Having an answer = more likely real question
        "high_score_threshold": 3,
        "high_score_boost": 0.04,
        "error_trace_hard_cap": 0.20,  # Error traces on SE = NOT a lead, hard cap
        "bug_pattern_hard_cap": 0.30,   # Bug reports get capped low
        "base_context_mult": 0.80,  # SO is generally lower quality for leads
        "recommendation_close_patterns": [
            r"\bclosed\b.*\b(?:opinion|recommendation|off.topic)\b",
        ],
        "closed_question_penalty": -0.30,
    },
    "generic": {
        "base_context_mult": 1.0,
    },
}

# ================================================================
# SCORING ENGINE
# ================================================================


def _match_signals(content: str, title: str, signal_groups: list[dict]) -> tuple[float, list[str], str]:
    """Match text against signal patterns with title-aware weighting.

    Returns: (total_weight, reasons_list, best_category)
    """
    total_weight = 0.0
    reasons = []
    best_category = "noise"
    best_category_weight = -999.0

    for group in signal_groups:
        group_weight_sum = 0.0
        group_matches = []

        for pattern_str in group["patterns"]:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            title_match = pattern.search(title)
            body_match = pattern.search(content)

            if title_match:
                # Title match: 2x weight
                match_weight = group["weight"] * 2.0
                group_matches.append(f"title:'{title_match.group(0).strip()}'")

            elif body_match:
                # Body-only match: 1x weight
                match_weight = group["weight"] * 1.0
                group_matches.append(f"body:'{body_match.group(0).strip()}'")

            else:
                continue  # No match

            group_weight_sum += match_weight

        if group_matches:
            # Cap per-group contribution so one category doesn't dominate
            capped = group_weight_sum
            abs_cap = abs(group["weight"]) * 3.0
            if abs(capped) > abs_cap:
                capped = abs_cap * (1.0 if capped > 0 else -1.0)

            total_weight += capped
            reasons.extend(group_matches[:2])  # Max 2 matches per group

            # Track best category (prefer positive signals)
            cat = group.get("category", "noise")
            if group["weight"] > 0 and group_weight_sum > best_category_weight:
                best_category = cat
                best_category_weight = group_weight_sum
            elif best_category == "noise" and group["weight"] < 0:
                best_category = cat if cat != "noise" else "complaint"

    return total_weight, reasons, best_category


def _detect_source(subreddit: str, reddit_id: str) -> str:
    """Infer the actual data source from subreddit and reddit_id."""
    if subreddit == "StackOverflow":
        return "stackexchange"
    if subreddit == "HackerNews":
        if reddit_id and reddit_id.startswith("hn-job-"):
            return "hn_jobs"
        return "hackernews"
    return "generic"


def _compute_source_boost(source: str, subreddit: str, title: str,
                          reddit_score: int, num_comments: int) -> tuple[float, list[str]]:
    """Compute source-specific boost/penalty based on platform heuristics."""
    rules = SOURCE_RULES.get(source, SOURCE_RULES["generic"])
    boost = 0.0
    reasons = []

    # --- HN-specific signals ---
    if source == "hackernews":
        # High engagement = more credible/valuable
        if reddit_score >= rules["high_points_threshold"]:
            boost += rules["high_points_boost"]
            reasons.append(f"HN +{reddit_score} points")

        if num_comments >= rules["many_comments_threshold"]:
            boost += rules["many_comments_boost"]
            reasons.append(f"HN {num_comments} comments")

        # Ask HN threads are very likely to be genuine seeking
        if re.search(rules["ask_hn_title_pattern"], title, re.IGNORECASE):
            boost += rules["ask_hn_boost"]
            reasons.append("Ask HN thread")

        # Show HN is self-promotion, slightly penalize
        if re.search(rules["show_hn_title_pattern"], title, re.IGNORECASE):
            boost += rules["show_hn_penalty"]
            reasons.append("Show HN (self-promo)")

    # --- HN Jobs-specific signals ---
    elif source == "hn_jobs":
        # Jobs threads almost always signal genuine demand
        if re.search(rules["hiring_title_pattern"], title, re.IGNORECASE):
            boost += rules["hiring_boost"]
            reasons.append("HN hiring thread")

        if reddit_score >= rules["high_points_threshold"]:
            boost += rules["high_points_boost"]

        if num_comments >= rules["many_comments_threshold"]:
            boost += rules["many_comments_boost"]

    # --- StackExchange-specific signals ---
    elif source == "stackexchange":
        # More engagement on a question = more real interest
        if reddit_score >= rules["high_score_threshold"]:
            boost += rules["high_score_boost"]
            reasons.append(f"SE score +{reddit_score}")

        # Having answers = legitimate question (not spam/trash)
        if num_comments >= 1:
            boost += rules["accepted_answer_boost"]
            reasons.append(f"SE {num_comments} answers")

        # Closed questions (opinion/recommendation) are noise
        for close_pat in rules.get("recommendation_close_patterns", []):
            if re.search(close_pat, title, re.IGNORECASE):
                boost += rules["closed_question_penalty"]
                reasons.append("Closed question")
                break

    # Apply base context multiplier
    boost *= rules.get("base_context_mult", 1.0)

    return boost, reasons


def _compute_noise_penalty(source: str, content: str) -> tuple[float, list[str]]:
    """Apply source-specific noise penalties (hard caps)."""
    rules = SOURCE_RULES.get(source, SOURCE_RULES["generic"])
    penalty = 0.0
    reasons = []

    if source == "stackexchange":
        # Check for error traces → hard cap on SE
        error_trace_pats = [
            r"\b(?:traceback|stack\s+trace|backtrace)\b",
            r"\b(?:TypeError|ValueError|KeyError|AttributeError)\b",
            r"\b(?:undefined\s+is\s+not|Cannot\s+read\s+property|null\s+pointer)\b",
            r"\b(?:segfault|segmentation\s+fault)\b",
            r"\bError\s+(?:code|message|response)\b",
            r"\b(?:HTTP|http)\s+(?:4\d{2}|5\d{2})\b",
        ]
        for pat in error_trace_pats:
            if re.search(pat, content, re.IGNORECASE):
                penalty = -10.0  # Will trigger the hard cap
                reasons.append("SE error trace detected")
                break

        # Bug-heavy content on SE = not a lead
        if penalty == 0.0:
            bug_pats = [
                r"\b(?:bug|buggy)\b",
                r"\bdoesn'?t\s+work\b",
                r"\b(?:broken|broke)\b",
                r"\b(?:crash|crashing)\b",
            ]
            bug_count = sum(1 for p in bug_pats if re.search(p, content, re.IGNORECASE))
            if bug_count >= 2:
                penalty = -5.0  # Will trigger bug cap
                reasons.append("SE multiple bug signals")

    return penalty, reasons


def _keyword_signal(keyword: str, title: str, text: str) -> tuple[float, list[str]]:
    """Evaluate keyword match quality in title vs body."""
    if not keyword:
        return 0.0, []

    kw_lower = keyword.lower().strip()
    title_lower = title.lower()
    text_lower = text.lower()

    boost = 0.0
    reasons = []

    # Exact/phrase match in title is very strong
    if kw_lower in title_lower:
        boost += 0.18
        reasons.append(f"keyword in title")

    # Partial word match in title
    kw_words = re.findall(r'\w+', kw_lower)
    title_words = re.findall(r'\w+', title_lower)
    title_matches = sum(1 for w in kw_words if w in title_words and len(w) > 2)
    if title_matches >= len(kw_words) * 0.5 and len(kw_words) > 1:
        boost += 0.08
        reasons.append("partial keyword in title")

    # Multiple keyword mentions in body
    body_count = len(re.findall(re.escape(kw_lower), text_lower))
    if body_count >= 2:
        boost += 0.06
        reasons.append(f"keyword x{body_count} in body")

    return boost, reasons


def score_mention(title: str, text: str, keyword: str = "",
                  subreddit: str = "", author: str = "", source: str = "",
                  reddit_score: int = 0, num_comments: int = 0,
                  reddit_id: str = "") -> ScoreResult:
    """Score a mention for relevance as a lead.

    Uses sophisticated heuristic pattern matching with:
    - Source-aware rules (HN vs StackExchange vs other)
    - Title-vs-body weighted signal detection
    - Engagement metrics (points, comments)
    - Error/bug pattern detection for noise filtering
    - Score normalization for realistic distributions

    Args:
        title: Post title
        text: Post body text
        keyword: The tracked keyword that matched
        subreddit: Platform name (HackerNews, StackOverflow, etc.)
        author: Post author
        source: Original source identifier (hackernews, stackexchange, hn_jobs)
        reddit_score: Upvotes/points
        num_comments: Number of comments/answers
        reddit_id: Unique post ID (used to detect HN jobs by prefix)

    Returns:
        ScoreResult with normalized relevance_score 0.0-1.0
    """
    content = f"{title} {text}".strip()
    title_clean = title.strip()

    # ----- Detect actual source -----
    inferred_source = _detect_source(subreddit, reddit_id)
    if not source and inferred_source != "generic":
        source = inferred_source

    # ================================================================
    # Phase 1: Match lead and noise signals (title-aware)
    # ================================================================
    lead_weight, lead_reasons, lead_category = _match_signals(
        content, title_clean, LEAD_SIGNALS
    )
    noise_weight, noise_reasons, noise_category = _match_signals(
        content, title_clean, NOISE_SIGNALS
    )

    # ================================================================
    # Phase 2: Source-specific boost/penalty
    # ================================================================
    source_boost, source_reasons = _compute_source_boost(
        source, subreddit, title_clean, reddit_score, num_comments
    )

    # ================================================================
    # Phase 3: Source-specific noise penalties (hard caps)
    # ================================================================
    noise_penalty, noise_penalty_reasons = _compute_noise_penalty(source, content)

    # ================================================================
    # Phase 4: Keyword match quality
    # ================================================================
    kw_boost, kw_reasons = _keyword_signal(keyword, title_clean, text)

    # ================================================================
    # Phase 5: Score calculation & normalization
    # ================================================================
    # Raw score: weighted sum of all signals
    raw_score = lead_weight + noise_weight + source_boost + noise_penalty + kw_boost

    # Apply source-specific hard caps for noise
    rules = SOURCE_RULES.get(source, SOURCE_RULES["generic"])
    if source == "stackexchange":
        if noise_penalty <= -10.0:
            # Error trace: hard cap
            raw_score = min(raw_score, rules["error_trace_hard_cap"] * 5.0 - 3.0)
        elif noise_penalty <= -5.0:
            # Bug-heavy: hard cap
            raw_score = min(raw_score, rules["bug_pattern_hard_cap"] * 5.0 - 3.0)

    # Sigmoid-based normalization to 0-1 range
    # Center at ~0.23 for raw_score=0, asymptotically approach 0 and 1
    # raw_score = -2.0 → ~0.08
    # raw_score =  0.0 → ~0.23 (baseline noise)
    # raw_score =  1.5 → ~0.43 (weak signal)
    # raw_score =  3.0 → ~0.65 (moderate lead)
    # raw_score =  5.0 → ~0.86 (strong lead)
    # raw_score =  7.0 → ~0.95 (very strong lead)
    # raw_score = 10.0 → ~0.99

    # Use a logistic function: 1 / (1 + exp(-k * (x - x0)))
    # k=0.6, x0=2.0 gives good separation across the 0-1 range
    import math
    k = 0.6   # gentler steepness
    x0 = 2.0  # higher midpoint — most posts cluster in 0.1-0.5
    try:
        sigmoid = 1.0 / (1.0 + math.exp(-k * (raw_score - x0)))
    except OverflowError:
        sigmoid = 1.0 if raw_score > x0 else 0.0

    # Scale to fill more of the 0-1 range
    # sigmoid range with these params: raw -5 → 0.01, raw 0 → 0.15, raw 1 → 0.35,
    # raw 3 → 0.74, raw 5 → 0.92, raw 7 → 0.98
    normalized = sigmoid

    # Floor for noise and ceiling
    if raw_score <= -2.0:
        normalized = min(normalized, 0.08)
    if raw_score <= -1.0:
        normalized = min(normalized, 0.15)
    if raw_score <= 0.0:
        normalized = max(normalized, 0.03)

    # Round for clean output
    relevance_score = round(min(1.0, max(0.0, normalized)), 2)

    # ================================================================
    # Phase 6: Determine category and lead status
    # ================================================================
    # Best category: prioritize positive signal categories
    if lead_category != "noise":
        category = lead_category
    elif noise_category != "noise":
        category = noise_category
    else:
        category = "noise"

    # Lead determination: strong category + sufficient score
    if category == "lead" and relevance_score >= 0.55:
        is_lead = True
    elif category == "competitor_mention" and relevance_score >= 0.50:
        is_lead = True
    else:
        is_lead = False

    # ================================================================
    # Phase 7: Build reason string
    # ================================================================
    all_reasons = []
    if lead_reasons:
        all_reasons.extend(lead_reasons[:4])
    if noise_reasons:
        all_reasons.extend(noise_reasons[:2])
    if source_reasons:
        all_reasons.extend(source_reasons[:2])
    if noise_penalty_reasons:
        all_reasons.extend(noise_penalty_reasons)
    if kw_reasons:
        all_reasons.extend(kw_reasons[:1])

    if not all_reasons:
        reason_str = "no lead signals detected"
    else:
        reason_str = "; ".join(all_reasons[:5])

    return ScoreResult(
        relevance_score=relevance_score,
        is_lead=is_lead,
        lead_reason=reason_str,
        category=category,
    )


def score_and_update_mentions(db_path: str = None) -> int:
    """Score all unscored mentions in the database.

    Fetches mentions with their engagement metrics and source info,
    then applies the heuristic scoring engine.
    """
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
            reddit_score=m["reddit_score"] or 0,
            num_comments=m["num_comments"] or 0,
            reddit_id=m["reddit_id"] or "",
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

    # Comprehensive demo scoring across multiple scenarios
    test_cases = [
        # --- STRONG LEADS ---
        {
            "title": "Ask HN: What do you use for monitoring SaaS mentions on social media?",
            "text": "I'm currently evaluating several options and need something reliable. My boss wants a recommendation by Friday.",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 42,
            "num_comments": 28,
            "reddit_id": "hn-12345",
            "label": "HN Ask HN: seeking tool + urgency",
        },
        {
            "title": "Who is hiring? (May 2026)",
            "text": "Looking for: monitoring engineers, SRE, full-stack devs who know observability tools.",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 150,
            "num_comments": 320,
            "reddit_id": "hn-job-99999",
            "label": "HN Jobs: hiring thread",
        },
        {
            "title": "Switching from Datadog — any recommendations for cheaper monitoring?",
            "text": "We're tired of Datadog's pricing. Currently evaluating Grafana, New Relic, and open source alternatives. Has anyone compared these?",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 65,
            "num_comments": 42,
            "reddit_id": "hn-67890",
            "label": "HN: frustration + buying intent",
        },
        # --- NOISE (should NOT be leads) ---
        {
            "title": "TypeError: cannot read property 'monitoring' of undefined",
            "text": "I'm getting this error when trying to start my monitoring agent. Here's the traceback:\n\nTypeError: Cannot read property 'monitoring' of undefined\n    at Object.<anonymous> (/app/index.js:42:15)",
            "keyword": "monitoring",
            "subreddit": "StackOverflow",
            "reddit_score": 0,
            "num_comments": 1,
            "reddit_id": "se-11111",
            "label": "SE: error trace — should be noise",
        },
        {
            "title": "Bug: monitoring dashboard not loading after update",
            "text": "After the latest update, my monitoring dashboard is broken. Anyone else experiencing this? Please fix this ASAP!",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 3,
            "num_comments": 2,
            "reddit_id": "hn-22222",
            "label": "HN: bug report — should be noise",
        },
        {
            "title": "How do I install monitoring tools on Ubuntu?",
            "text": "sudo apt install monitoring-tools doesn't work. What command should I use?",
            "keyword": "monitoring",
            "subreddit": "StackOverflow",
            "reddit_score": 0,
            "num_comments": 2,
            "reddit_id": "se-33333",
            "label": "SE: trivial install question — noise",
        },
        # --- MODERATE LEADS ---
        {
            "title": "Comparing PagerDuty vs OpsGenie vs open source monitoring",
            "text": "We need something for our small team. Budget is tight. What's the best free alternative?",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 18,
            "num_comments": 12,
            "reddit_id": "hn-44444",
            "label": "HN: comparison + price sensitivity",
        },
        {
            "title": "Looking for monitoring alternatives, tired of false positives from our current tool",
            "text": "We've been using XYZ for 2 years and the noise is killing us. Need something better. Any recommendations?",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 22,
            "num_comments": 15,
            "reddit_id": "hn-55555",
            "label": "HN: frustration + seeking",
        },
        # --- EDGE CASES ---
        {
            "title": "Show HN: I built a new monitoring dashboard",
            "text": "Check out my new open source monitoring tool. Would love feedback!",
            "keyword": "monitoring",
            "subreddit": "HackerNews",
            "reddit_score": 80,
            "num_comments": 45,
            "reddit_id": "hn-66666",
            "label": "HN: Show HN self-promo — should NOT be lead",
        },
        {
            "title": "Monitoring my server — which tool has the best free tier?",
            "text": "I'm a solo dev and can't afford Datadog. Need something with a good free plan.",
            "keyword": "monitoring",
            "subreddit": "StackOverflow",
            "reddit_score": 5,
            "num_comments": 3,
            "reddit_id": "se-77777",
            "label": "SE: legitimate tool question — moderate lead",
        },
    ]

    print("=" * 70)
    print("SIGNALSEEK SCORER — COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    leads_found = 0
    noise_correct = 0
    noise_wrong = 0

    for i, tc in enumerate(test_cases):
        result = score_mention(
            title=tc["title"],
            text=tc["text"],
            keyword=tc["keyword"],
            subreddit=tc["subreddit"],
            reddit_score=tc["reddit_score"],
            num_comments=tc["num_comments"],
            reddit_id=tc["reddit_id"],
        )

        expected = "lead" if "should NOT be lead" not in tc["label"] and "should be noise" not in tc["label"] else "noise"
        if "Show HN" in tc["title"]:
            expected = "noise"

        status = "✓" if (result.is_lead and expected == "lead") or (not result.is_lead and expected == "noise") else "✗"
        if status == "✓" and expected == "lead":
            leads_found += 1
        elif status == "✓" and expected == "noise":
            noise_correct += 1
        elif status == "✗" and expected == "noise":
            noise_wrong += 1

        print(f"\n[{i+1}] {tc['label']}")
        print(f"    Title: {tc['title'][:80]}")
        print(f"    Score: {result.relevance_score:.2f} | Lead: {result.is_lead} | {result.category} {status}")
        print(f"    Reason: {result.lead_reason}")

    print("\n" + "=" * 70)
    print(f"RESULTS: {leads_found} leads found, {noise_correct} noise correctly filtered, {noise_wrong} false positives")
    print(f"Total: {len(test_cases)} tests, {sum(1 for tc in test_cases if 'should NOT be lead' in tc['label'] or 'should be noise' in tc['label'])} expected noise")
    print("=" * 70)
