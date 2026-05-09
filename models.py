"""SignalSeek database models."""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.signalseek/signalseek.db")


def get_db() -> sqlite3.Connection:
    """Get database connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database schema."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'free' CHECK(plan IN ('free','pro','business')),
            telegram_chat_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            keyword TEXT NOT NULL,
            subreddits TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reddit_id TEXT NOT NULL,
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

        CREATE TABLE IF NOT EXISTS alert_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            alert_type TEXT DEFAULT 'telegram' CHECK(alert_type IN ('telegram','email')),
            destination TEXT NOT NULL,
            min_relevance REAL DEFAULT 0.5,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_mentions_user ON mentions(user_id);
        CREATE INDEX IF NOT EXISTS idx_mentions_keyword ON mentions(keyword_id);
        CREATE INDEX IF NOT EXISTS idx_mentions_reddit_id ON mentions(reddit_id);
        CREATE INDEX IF NOT EXISTS idx_keywords_user ON keywords(user_id);
    """)
    conn.commit()
    conn.close()


# Initialize DB on import
init_db()
