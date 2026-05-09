"""Unit tests for SignalSeek scorer."""
import sys
sys.path.insert(0, '/root/signalseek')

from scorer import score_mention, ScoreResult


class TestScoreMention:
    """Core scoring logic tests."""

    def test_clear_lead(self):
        """Someone actively looking for a tool = lead."""
        result = score_mention(
            title="Looking for a project management tool for my team",
            text="I need something that handles kanban, sprints, and time tracking. Any recommendations?",
            keyword="project management",
            subreddit="HackerNews"
        )
        assert result.is_lead, f"Should be lead: {result}"
        assert result.relevance_score >= 0.7, f"Score too low: {result.relevance_score}"
        assert result.category == "lead"

    def test_noise_milestone_post(self):
        """Milestone announcement = noise."""
        result = score_mention(
            title="Just hit $10k MRR with my SaaS!",
            text="Super excited to share this milestone with you all.",
            keyword="saas",
            subreddit="HackerNews"
        )
        assert not result.is_lead
        assert result.relevance_score < 0.3

    def test_competitor_complaint(self):
        """Someone frustrated with a competitor = competitor_mention."""
        result = score_mention(
            title="Tired of F5Bot sending me garbage alerts",
            text="Half the alerts are totally irrelevant. Is there anything better?",
            keyword="monitor",
            subreddit="HackerNews"
        )
        assert result.relevance_score >= 0.5
        assert result.category in ("lead", "competitor_mention")

    def test_stackoverflow_bug_not_lead(self):
        """StackOverflow error traces should NOT be leads."""
        result = score_mention(
            title="TypeError: Cannot read properties of undefined",
            text="I get this error when running npm install. Here's my package.json and stack trace...",
            keyword="monitoring",
            subreddit="StackOverflow"
        )
        assert not result.is_lead
        assert result.relevance_score <= 0.3, f"Bug report scored too high: {result.relevance_score}"

    def test_comparison_is_lead(self):
        """Someone comparing tools = lead signal."""
        result = score_mention(
            title="Best project management tool for small teams?",
            text="Comparing Monday vs Asana vs ClickUp. Anyone used all three?",
            keyword="project management",
            subreddit="HackerNews"
        )
        assert result.is_lead
        assert result.relevance_score >= 0.7

    def test_keyword_in_title_boost(self):
        """Keyword in title should boost score."""
        without = score_mention(
            title="What do you use for task tracking?",
            text="Looking for recommendations",
            keyword="",
            subreddit="HackerNews"
        )
        with_kw = score_mention(
            title="What do you use for task tracking?",
            text="Looking for recommendations for task tracking software",
            keyword="task tracking",
            subreddit="HackerNews"
        )
        assert with_kw.relevance_score >= without.relevance_score

    def test_empty_input(self):
        """Empty strings should be noise."""
        result = score_mention(title="", text="", keyword="test")
        assert result.relevance_score <= 0.3
        assert not result.is_lead

    def test_score_range(self):
        """Scores must be within [0.0, 1.0]."""
        tests = [
            ("Looking for a tool", "any recommendations?", "HackerNews"),
            ("Just hit $10k MRR", "milestone!", "HackerNews"),
            ("", "", "HackerNews"),
        ]
        for title, text, source in tests:
            result = score_mention(title, text, subreddit=source)
            assert 0.0 <= result.relevance_score <= 1.0, f"Score out of range: {result.relevance_score}"

    def test_hn_jobs_detection(self):
        """HN who is hiring posts are questions, not leads."""
        result = score_mention(
            title="Ask HN: Who is hiring? (May 2026)",
            text="Please state location and remote status",
            keyword="hiring",
            subreddit="HackerNews"
        )
        assert result.relevance_score <= 0.3

    def test_price_sensitivity(self):
        """Price-sensitive language = lead signal."""
        result = score_mention(
            title="Cheaper alternative to Intercom?",
            text="Looking for a free alternative that does basic chat and email",
            keyword="chat",
            subreddit="HackerNews"
        )
        assert result.relevance_score >= 0.4


class TestScoreResult:
    """ScoreResult dataclass tests."""

    def test_dataclass_fields(self):
        result = score_mention("Test", "Test text")
        assert hasattr(result, 'relevance_score')
        assert hasattr(result, 'is_lead')
        assert hasattr(result, 'lead_reason')
        assert hasattr(result, 'category')
        assert isinstance(result.relevance_score, float)
        assert isinstance(result.is_lead, bool)


if __name__ == "__main__":
    # Run tests manually
    import traceback
    tests = [
        (name, obj) for name in dir()
        if name.startswith('test_') and callable(obj := eval(name))
    ] if False else []

    test_classes = [TestScoreMention, TestScoreResult]
    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        for name in dir(cls):
            if name.startswith('test_'):
                try:
                    getattr(instance, name)()
                    print(f"  ✓ {cls.__name__}.{name}")
                    passed += 1
                except Exception as e:
                    print(f"  ✗ {cls.__name__}.{name}: {e}")
                    failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
