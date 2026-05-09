"""Unit tests for SignalSeek monitor."""
import sys
import os
import sqlite3
import tempfile
sys.path.insert(0, '/root/signalseek')

from unittest.mock import patch, MagicMock
from monitor import find_new_mentions, ALL_SOURCES


class TestFindNewMentions:
    """Test mention deduplication and DB integration."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                keyword TEXT,
                subreddits TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword_id INTEGER,
                user_id INTEGER,
                reddit_id TEXT,
                subreddit TEXT,
                title TEXT,
                text TEXT,
                url TEXT,
                author TEXT,
                reddit_score INTEGER DEFAULT 0,
                num_comments INTEGER DEFAULT 0,
                created_utc REAL,
                relevance_score REAL,
                is_lead INTEGER DEFAULT 0,
                lead_reason TEXT,
                found_at TEXT DEFAULT (datetime('now')),
                sent_at TEXT,
                UNIQUE(keyword_id, reddit_id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT,
                plan TEXT DEFAULT 'free'
            );
            INSERT INTO users (id, email, plan) VALUES (1, 'test@test.com', 'free');
            INSERT INTO keywords (id, user_id, keyword) VALUES (1, 1, 'test keyword');
        """)
        self.conn.commit()

    def teardown_method(self):
        self.conn.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deduplication(self):
        """find_new_mentions should not return already-saved mentions."""
        # Pre-insert a mention
        self.conn.execute("""
            INSERT INTO mentions (keyword_id, user_id, reddit_id, subreddit, title)
            VALUES (1, 1, 'hn-existing', 'HackerNews', 'Existing post')
        """)
        self.conn.commit()

        # Mock search to return the existing post + new one
        def mock_search(*args, **kwargs):
            return [
                {"reddit_id": "hn-existing", "subreddit": "HackerNews",
                 "title": "Existing post", "text": "", "url": "",
                 "author": "a", "reddit_score": 0, "num_comments": 0,
                 "created_utc": 0},
                {"reddit_id": "hn-new", "subreddit": "HackerNews",
                 "title": "New post", "text": "", "url": "",
                 "author": "b", "reddit_score": 0, "num_comments": 0,
                 "created_utc": 0},
            ]

        with patch('monitor.search_all_sources', mock_search):
            new = find_new_mentions(1, 1, "test", db_conn=self.conn)
            assert len(new) == 1, f"Expected 1 new, got {len(new)}"
            assert new[0]["reddit_id"] == "hn-new"


class TestAllSources:
    """Test source registration."""

    def test_all_sources_non_empty(self):
        assert len(ALL_SOURCES) >= 3, f"Expected >= 3 sources, got {len(ALL_SOURCES)}"

    def test_sources_have_names(self):
        for name, fn in ALL_SOURCES:
            assert isinstance(name, str)
            assert callable(fn)


if __name__ == "__main__":
    test_classes = [TestFindNewMentions, TestAllSources]
    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        setup = getattr(instance, 'setup_method', None)
        teardown = getattr(instance, 'teardown_method', None)

        for name in dir(cls):
            if name.startswith('test_'):
                try:
                    if setup:
                        setup()
                    getattr(instance, name)()
                    if teardown:
                        teardown()
                    print(f"  ✓ {cls.__name__}.{name}")
                    passed += 1
                except Exception as e:
                    print(f"  ✗ {cls.__name__}.{name}: {e}")
                    failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
