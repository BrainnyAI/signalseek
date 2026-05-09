"""Alert dispatch — sends scored mentions to users via Telegram/Email."""
import logging
import urllib.request
import urllib.parse
import json
import os
import sqlite3

logger = logging.getLogger("signalseek.alerts")


def send_telegram_alert(chat_id: str, message: str) -> bool:
    """Send a message via Telegram Bot API."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — cannot send Telegram alerts")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def format_mention_message(title: str, url: str, subreddit: str, author: str,
                           relevance_score: float, lead_reason: str,
                           reddit_score: int, num_comments: int,
                           keyword: str, source: str = None) -> str:
    """Format a mention as a Telegram message."""
    # Determine source icon
    source_icon = {"HackerNews": "🔶", "StackOverflow": "🟧", "hn_jobs": "💼"}.get(source or subreddit, "🔵")
    lead_emoji = "🔴" if relevance_score >= 0.7 else "🟡" if relevance_score >= 0.5 else "⚪️"

    source_label = subreddit if subreddit not in ("HackerNews", "StackOverflow") else subreddit

    lines = [
        f"{source_icon} {lead_emoji} <b>New mention</b> for '<i>{keyword}</i>'",
        f"",
        f"<b>{title}</b>",
        f"",
        f"📊 Relevance: {relevance_score:.0%} — <i>{lead_reason}</i>",
        f"📍 {source_label} | 👤 {author}",
        f"⬆️ {reddit_score} | 💬 {num_comments} comments",
        f"",
        f"🔗 <a href=\"{url}\">{url}</a>",
    ]
    return "\n".join(lines)


def dispatch_unread_mentions(db_path: str = None) -> dict:
    """Find unscored mentions, score them, and dispatch to users."""
    if db_path is None:
        db_path = os.path.expanduser("~/.signalseek/signalseek.db")

    # First, score any unscored mentions
    from scorer import score_and_update_mentions
    score_and_update_mentions(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get mentions that haven't been sent yet and meet relevance threshold
    mentions = conn.execute("""
        SELECT m.*, k.keyword, u.telegram_chat_id, u.email
        FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        JOIN users u ON m.user_id = u.id
        WHERE m.sent_at IS NULL
          AND m.relevance_score IS NOT NULL
          AND m.relevance_score >= 0.4
        ORDER BY m.relevance_score DESC
    """).fetchall()

    stats = {"total": len(mentions), "sent_telegram": 0, "errors": 0}

    for m in mentions:
        chat_id = m["telegram_chat_id"]
        if not chat_id:
            continue

        message = format_mention_message(
            title=m["title"] or "(no title)",
            url=m["url"] or "",
            subreddit=m["subreddit"] or "unknown",
            author=m["author"] or "unknown",
            relevance_score=m["relevance_score"] or 0,
            lead_reason=m["lead_reason"] or "unknown",
            reddit_score=m["reddit_score"] or 0,
            num_comments=m["num_comments"] or 0,
            keyword=m["keyword"] or "",
            source=m["subreddit"] or "",
        )

        if send_telegram_alert(chat_id, message):
            conn.execute(
                "UPDATE mentions SET sent_at = datetime('now') WHERE id = ?",
                (m["id"],)
            )
            stats["sent_telegram"] += 1
        else:
            stats["errors"] += 1

    conn.commit()
    conn.close()

    logger.info(f"Dispatched: {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stats = dispatch_unread_mentions()
    print(f"Dispatch: {stats}")
