"""Multi-source monitoring engine — searches multiple platforms for keyword mentions.

Data sources (prioritized by accessibility):
1. HackerNews (Algolia API) — developer/SaaS discussions
2. StackExchange — Q&A with tool recommendations
3. Google News RSS — broader coverage
"""
import time
import urllib.request
import urllib.parse
import json
import logging
import os
from datetime import datetime
import xml.etree.ElementTree as ET

logger = logging.getLogger("signalseek.monitor")

USER_AGENT = "SignalSeek-Monitor/1.0"


# ============================================================
# Data Source 1: HackerNews (Algolia Search API)
# ============================================================

def search_hackernews(keyword: str, limit: int = 25) -> list[dict]:
    """Search HN via Algolia API. Returns list of post objects."""
    url = f"https://hn.algolia.com/api/v1/search_by_date?query={urllib.parse.quote(keyword)}&tags=story,comment&hitsPerPage={limit}&restrictSearchableAttributes=title,comment_text"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error(f"HN search failed for '{keyword}': {e}")
        return []

    posts = []
    for hit in data.get("hits", []):
        post_type = "comment" if hit.get("comment_text") else "post"
        obj_id = hit.get("objectID", "")
        source_url = f"https://news.ycombinator.com/item?id={hit.get('story_id') or obj_id}"

        posts.append({
            "reddit_id": f"hn-{obj_id}",  # Use same field for dedup, prefixed
            "subreddit": "HackerNews",
            "title": hit.get("title", "") or hit.get("story_title", ""),
            "text": (hit.get("comment_text", "") or hit.get("story_text", ""))[:2000],
            "url": source_url,
            "author": hit.get("author", "unknown"),
            "reddit_score": hit.get("points", 0) or 0,
            "num_comments": hit.get("num_comments", 0) or 0,
            "created_utc": hit.get("created_at_i", 0) or 0,
        })

    return posts


# ============================================================
# Data Source 2: StackExchange API
# ============================================================

STACKEXCHANGE_KEY = os.environ.get("STACKEXCHANGE_KEY", "")


def search_stackexchange(keyword: str, limit: int = 20) -> list[dict]:
    """Search StackExchange for questions mentioning the keyword."""
    params = {
        "order": "desc",
        "sort": "creation",
        "q": keyword,
        "site": "stackoverflow",
        "pagesize": min(limit, 100),
        "filter": "withbody",
    }
    if STACKEXCHANGE_KEY:
        params["key"] = STACKEXCHANGE_KEY

    url = f"https://api.stackexchange.com/2.3/search/advanced?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        # StackExchange requires gzip
        req.add_header("Accept-Encoding", "gzip")
        with urllib.request.urlopen(req, timeout=15) as resp:
            import gzip
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            data = json.loads(raw)
    except Exception as e:
        logger.error(f"StackExchange search failed for '{keyword}': {e}")
        return []

    posts = []
    for item in data.get("items", []):
        posts.append({
            "reddit_id": f"se-{item['question_id']}",
            "subreddit": "StackOverflow",
            "title": item.get("title", ""),
            "text": (item.get("body_markdown", "") or item.get("body", ""))[:2000],
            "url": item.get("link", ""),
            "author": item.get("owner", {}).get("display_name", "unknown"),
            "reddit_score": item.get("score", 0),
            "num_comments": item.get("answer_count", 0),
            "created_utc": item.get("creation_date", 0),
        })

    return posts


# ============================================================
# Data Source 3: HN Who Is Hiring / Freelancing threads
# ============================================================

def search_hn_whoishiring(keyword: str, limit: int = 10) -> list[dict]:
    """Search HN 'Who is hiring' and 'Freelancer' threads specifically.
    These are high-lead-value threads where people actively seek services."""
    # Search specifically in Ask HN posts
    url = (f"https://hn.algolia.com/api/v1/search_by_date?"
           f"query={urllib.parse.quote(keyword)}"
           f"&tags=story"
           f"&restrictSearchableAttributes=title"
           f"&hitsPerPage={limit}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    posts = []
    for hit in data.get("hits", []):
        title = (hit.get("title", "") or "").lower()
        # Filter to likely hiring/seeking threads
        if any(t in title for t in ["hiring", "freelancer", "looking for", "who is hiring",
                                      " seeking ", "want to hire", "wanted:"]):
            obj_id = hit.get("objectID", "")
            posts.append({
                "reddit_id": f"hn-job-{obj_id}",
                "subreddit": "HackerNews",
                "title": hit.get("title", ""),
                "text": (hit.get("story_text", "") or "")[:2000],
                "url": f"https://news.ycombinator.com/item?id={obj_id}",
                "author": hit.get("author", "unknown"),
                "reddit_score": hit.get("points", 0) or 0,
                "num_comments": hit.get("num_comments", 0) or 0,
                "created_utc": hit.get("created_at_i", 0) or 0,
            })

    return posts


# ============================================================
# Data Source 3: HN Show HN
# ============================================================

def search_hn_showhn(keyword: str, limit: int = 15) -> list[dict]:
    """Search HackerNews 'Show HN' posts specifically — people launching products,
    often looking for feedback or alternatives."""
    url = (f"https://hn.algolia.com/api/v1/search_by_date?"
           f"query={urllib.parse.quote(keyword)}"
           f"&tags=show_hn"
           f"&hitsPerPage={limit}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    posts = []
    for hit in data.get("hits", []):
        obj_id = hit.get("objectID", "")
        posts.append({
            "reddit_id": f"hn-show-{obj_id}",
            "subreddit": "Show HN",
            "title": hit.get("title", ""),
            "text": (hit.get("story_text", "") or "")[:2000],
            "url": f"https://news.ycombinator.com/item?id={obj_id}",
            "author": hit.get("author", "unknown"),
            "reddit_score": hit.get("points", 0) or 0,
            "num_comments": hit.get("num_comments", 0) or 0,
            "created_utc": hit.get("created_at_i", 0) or 0,
        })

    return posts


# ============================================================
# Data Source 4: Google News RSS
# ============================================================

def search_google_news(keyword: str, limit: int = 20) -> list[dict]:
    """Search Google News RSS for keyword mentions."""
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone
    
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keyword)}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Google News failed for '{keyword}': {e}")
        return []

    posts = []
    try:
        root = ET.fromstring(raw)
        for i, item in enumerate(root.findall(".//item")):
            if i >= limit:
                break
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "")[:2000]
            source = (item.findtext("source") or "Google News").strip()
            pubdate = item.findtext("pubDate") or ""
            
            # Parse pubDate to UTC timestamp
            created_utc = 0
            try:
                from email.utils import parsedate_to_datetime
                created_utc = parsedate_to_datetime(pubdate).timestamp()
            except Exception:
                pass

            posts.append({
                "reddit_id": f"news-{hash(link) & 0x7fffffff:x}",
                "subreddit": "Google News",
                "title": title,
                "text": desc,
                "url": link,
                "author": source,
                "reddit_score": 0,
                "num_comments": 0,
                "created_utc": created_utc,
            })
    except ET.ParseError as e:
        logger.error(f"Google News RSS parse error: {e}")

    return posts


# ============================================================
# Data Source 5: Lobsters
# ============================================================

def search_lobsters(keyword: str, limit: int = 20) -> list[dict]:
    """Search Lobsters (lobste.rs) for tech-focused discussions."""
    url = f"https://lobste.rs/search.json?q={urllib.parse.quote(keyword)}&what=stories&order=relevance"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error(f"Lobsters search failed for '{keyword}': {e}")
        return []

    posts = []
    for item in data[:limit]:
        posts.append({
            "reddit_id": f"lob-{item.get('short_id', '')}",
            "subreddit": "Lobsters",
            "title": item.get("title", ""),
            "text": (item.get("description", "") or "")[:2000],
            "url": item.get("url", f"https://lobste.rs/s/{item.get('short_id', '')}"),
            "author": item.get("submitter_user", {}).get("username", "unknown") if isinstance(item.get("submitter_user"), dict) else "unknown",
            "reddit_score": item.get("score", 0) or 0,
            "num_comments": item.get("comment_count", 0) or 0,
            "created_utc": item.get("created_at", "").replace("T", " ").replace("Z", "") if item.get("created_at") else "",
        })
        
        # Try to parse the ISO timestamp to UTC
        if isinstance(posts[-1]["created_utc"], str):
            try:
                from datetime import datetime
                posts[-1]["created_utc"] = datetime.fromisoformat(
                    item.get("created_at", "").replace("Z", "+00:00")
                ).timestamp()
            except Exception:
                posts[-1]["created_utc"] = 0

    return posts


# ============================================================
# Unified search
# ============================================================

ALL_SOURCES = [
    ("hackernews", search_hackernews),
    ("show_hn", search_hn_showhn),
    ("stackexchange", search_stackexchange),
    ("hn_jobs", search_hn_whoishiring),
    ("google_news", search_google_news),
    ("lobsters", search_lobsters),
]


def search_all_sources(keyword: str, subreddits: str = None, limit: int = 25) -> list[dict]:
    """Search all available sources for a keyword. Deduplicates by ID."""
    all_posts = []
    seen_ids = set()

    for source_name, search_fn in ALL_SOURCES:
        try:
            posts = search_fn(keyword, limit=limit)
            for post in posts:
                if post["reddit_id"] not in seen_ids:
                    seen_ids.add(post["reddit_id"])
                    post["source"] = source_name
                    all_posts.append(post)
            logger.debug(f"{source_name}: {len(posts)} results for '{keyword}'")
            time.sleep(0.5)  # Be polite to APIs
        except Exception as e:
            logger.error(f"Source {source_name} failed for '{keyword}': {e}")

    return all_posts


def find_new_mentions(keyword_id: int, user_id: int, keyword: str, subreddits: str = None,
                      db_conn=None, limit: int = 25) -> list[dict]:
    """Find new mentions for a keyword not already in database."""
    import sqlite3
    close_conn = False
    if db_conn is None:
        db_conn = sqlite3.connect(os.path.expanduser("~/.signalseek/signalseek.db"))
        db_conn.row_factory = sqlite3.Row
        close_conn = True

    all_posts = search_all_sources(keyword, subreddits, limit=limit)

    new_mentions = []
    for post in all_posts:
        existing = db_conn.execute(
            "SELECT id FROM mentions WHERE keyword_id = ? AND reddit_id = ?",
            (keyword_id, post["reddit_id"])
        ).fetchone()
        if not existing:
            post["keyword_id"] = keyword_id
            post["user_id"] = user_id
            new_mentions.append(post)

    if close_conn:
        db_conn.close()

    logger.info(f"Keyword '{keyword}': {len(all_posts)} found, {len(new_mentions)} new")
    return new_mentions


def scan_all_keywords(db_path: str = None) -> dict:
    """Scan all active keywords across all users."""
    import sqlite3
    if db_path is None:
        db_path = os.path.expanduser("~/.signalseek/signalseek.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    keywords = conn.execute("""
        SELECT k.*, u.plan FROM keywords k
        JOIN users u ON k.user_id = u.id
        WHERE k.active = 1 AND u.id IS NOT NULL
    """).fetchall()

    stats = {"scanned": len(keywords), "new_mentions": 0, "errors": 0}

    for kw in keywords:
        try:
            limit = 50 if kw["plan"] in ("pro", "business") else 15
            mentions = find_new_mentions(
                keyword_id=kw["id"], user_id=kw["user_id"],
                keyword=kw["keyword"], subreddits=kw["subreddits"],
                db_conn=conn, limit=limit,
            )

            for m in mentions:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO mentions
                        (keyword_id, user_id, reddit_id, subreddit, title, text, url,
                         author, reddit_score, num_comments, created_utc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        m["keyword_id"], m["user_id"], m["reddit_id"],
                        m["subreddit"], m["title"], m["text"], m["url"],
                        m["author"], m["reddit_score"], m["num_comments"],
                        m["created_utc"],
                    ))
                    stats["new_mentions"] += 1
                except Exception:
                    pass

            conn.commit()
            time.sleep(1.0)

        except Exception as e:
            logger.error(f"Error scanning '{kw['keyword']}': {e}")
            stats["errors"] += 1

    conn.close()
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Testing HN Search ===")
    posts = search_hackernews("saas tool recommendation", limit=3)
    for p in posts:
        print(f"  [{p['subreddit']}] {p['title'][:80]}")

    print("\n=== Testing StackExchange ===")
    posts = search_stackexchange("website monitoring tool", limit=2)
    for p in posts:
        print(f"  [{p['subreddit']}] {p['title'][:80]}")

    print("\n=== Full Scan ===")
    stats = scan_all_keywords()
    print(f"  Results: {stats}")