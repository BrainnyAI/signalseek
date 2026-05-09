"""SignalSeek — AI-powered Reddit lead monitoring.
Main FastAPI application.
"""
import csv
import io
import os
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import bcrypt
from jose import jwt

from models import get_db, init_db
from monitor import scan_all_keywords, ALL_SOURCES
from scorer import score_and_update_mentions
from alerts import dispatch_unread_mentions, format_mention_message
from onboarding import get_suggestions, get_onboarding_tips, KEYWORD_SUGGESTIONS

# Config
SECRET_KEY = os.environ.get("SECRET_KEY", "signalseek-dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 1 week


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
templates = Jinja2Templates(directory="/root/signalseek/templates")

# --- Auth helpers ---


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    from jose import jwt as jose_jwt
    return jose_jwt.encode(
        {"sub": str(user_id), "exp": expire},
        SECRET_KEY, algorithm=JWT_ALGORITHM
    )


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("signalseek_token")
    if not token:
        return None
    try:
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(user) if user else None
    except Exception:
        return None


# --- App ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SignalSeek", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="/root/signalseek/static"), name="static")


# --- Pages ---


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password"}
        )

    token = create_token(user["id"])
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("signalseek_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register(request: Request, email: str = Form(...), password: str = Form(...),
                   telegram_chat_id: str = Form(None)):
    if len(password) < 6:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Password must be at least 6 characters"}
        )

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Email already registered"}
        )

    password_hash = hash_password(password)
    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, telegram_chat_id) VALUES (?, ?, ?)",
        (email, password_hash, telegram_chat_id)
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    token = create_token(user_id)
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("signalseek_token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    conn = get_db()

    # Keywords
    keywords = conn.execute(
        "SELECT * FROM keywords WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()

    # Recent mentions
    mentions = conn.execute("""
        SELECT m.*, k.keyword FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        WHERE m.user_id = ?
        ORDER BY m.found_at DESC
        LIMIT 50
    """, (user["id"],)).fetchall()

    # Stats
    total_mentions = conn.execute(
        "SELECT COUNT(*) FROM mentions WHERE user_id = ?", (user["id"],)
    ).fetchone()[0]

    leads_found = conn.execute(
        "SELECT COUNT(*) FROM mentions WHERE user_id = ? AND is_lead = 1", (user["id"],)
    ).fetchone()[0]

    conn.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "keywords": [dict(k) for k in keywords],
        "mentions": [dict(m) for m in mentions],
        "total_mentions": total_mentions,
        "leads_found": leads_found,
        "is_new_user": len(keywords) == 0,
        "suggestions": get_suggestions(count=6),
        "tips": get_onboarding_tips(count=3),
        "categories": list(KEYWORD_SUGGESTIONS.keys()),
        "source_count": len(ALL_SOURCES),
    })


@app.post("/keywords/add")
async def add_keyword(request: Request, keyword: str = Form(...), subreddits: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    # Check keyword limit for free plan
    conn = get_db()
    kw_count = conn.execute(
        "SELECT COUNT(*) FROM keywords WHERE user_id = ?", (user["id"],)
    ).fetchone()[0]

    max_kw = 3 if user["plan"] == "free" else 20 if user["plan"] == "pro" else 100
    if kw_count >= max_kw:
        conn.close()
        return templates.TemplateResponse("dashboard.html", {
            "request": request, "user": user,
            "error": f"Keyword limit reached ({max_kw} for {user['plan']} plan). Upgrade for more."
        })

    conn.execute(
        "INSERT INTO keywords (user_id, keyword, subreddits) VALUES (?, ?, ?)",
        (user["id"], keyword.strip(), subreddits.strip() if subreddits.strip() else None)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/dashboard", status_code=303)


@app.post("/keywords/{kw_id}/delete")
async def delete_keyword(request: Request, kw_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    conn = get_db()
    conn.execute(
        "DELETE FROM keywords WHERE id = ? AND user_id = ?", (kw_id, user["id"])
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
async def logout():
    response = RedirectResponse("/")
    response.delete_cookie("signalseek_token")
    return response


# --- API ---


@app.get("/api/mentions")
async def api_mentions(request: Request, limit: int = Query(50, le=200),
                       min_score: float = Query(0, ge=0, le=1),
                       offset: int = Query(0, ge=0),
                       source: str = Query("", description="Filter by source: hackernews, stackexchange, hn_jobs, generic, all"),
                       lead_status: str = Query("all", description="Filter: all, leads, noise"),
                       date_from: str = Query("", description="ISO date YYYY-MM-DD or 'today','week','month'"),
                       date_to: str = Query("", description="ISO date YYYY-MM-DD")):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    conn = get_db()

    # Build WHERE clause
    conditions = ["m.user_id = ?", "m.relevance_score >= ?"]
    params = [user["id"], min_score]

    # Source filter
    if source and source != "all":
        if source == "hackernews":
            conditions.append("m.subreddit = 'HackerNews' AND m.reddit_id NOT LIKE 'hn-job-%'")
        elif source == "hn_jobs":
            conditions.append("m.subreddit = 'HackerNews' AND m.reddit_id LIKE 'hn-job-%'")
        elif source == "stackexchange":
            conditions.append("m.subreddit = 'StackOverflow'")
        elif source == "generic":
            conditions.append("m.subreddit NOT IN ('HackerNews', 'StackOverflow')")

    # Lead status filter
    if lead_status == "leads":
        conditions.append("m.is_lead = 1")
    elif lead_status == "noise":
        conditions.append("m.is_lead = 0")

    # Date range filter
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if date_from == "today":
        conditions.append("DATE(m.found_at) = ?")
        params.append(today)
    elif date_from == "week":
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        conditions.append("DATE(m.found_at) >= ?")
        params.append(week_ago)
    elif date_from == "month":
        month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        conditions.append("DATE(m.found_at) >= ?")
        params.append(month_ago)
    elif date_from:
        conditions.append("DATE(m.found_at) >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("DATE(m.found_at) <= ?")
        params.append(date_to)

    where_clause = " AND ".join(conditions)

    # Get total count (for pagination)
    count_row = conn.execute(
        f"SELECT COUNT(*) FROM mentions m JOIN keywords k ON m.keyword_id = k.id WHERE {where_clause}",
        params
    ).fetchone()
    total_count = count_row[0] if count_row else 0

    mentions = conn.execute(f"""
        SELECT m.*, k.keyword FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        WHERE {where_clause}
        ORDER BY m.found_at DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()

    return {
        "mentions": [dict(m) for m in mentions],
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total_count
    }


@app.get("/api/trends")
async def api_trends(request: Request):
    """Return mentions per day for the last 7 days."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    conn = get_db()
    today = datetime.utcnow()
    days = []
    trends = []

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        day_str = d.strftime("%Y-%m-%d")
        day_label = d.strftime("%a")  # Mon, Tue, etc.

        count = conn.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id = ? AND DATE(found_at) = ?",
            (user["id"], day_str)
        ).fetchone()[0]

        leads_count = conn.execute(
            "SELECT COUNT(*) FROM mentions WHERE user_id = ? AND DATE(found_at) = ? AND is_lead = 1",
            (user["id"], day_str)
        ).fetchone()[0]

        days.append(day_label)
        trends.append({"date": day_str, "label": day_label, "total": count, "leads": leads_count})

    conn.close()
    return {"trends": trends}


@app.get("/api/top-keywords")
async def api_top_keywords(request: Request):
    """Return top keywords by lead generation."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    conn = get_db()
    rows = conn.execute("""
        SELECT k.keyword, COUNT(*) as total_mentions,
               SUM(CASE WHEN m.is_lead = 1 THEN 1 ELSE 0 END) as leads,
               AVG(m.relevance_score) as avg_score
        FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        WHERE m.user_id = ?
        GROUP BY k.keyword
        ORDER BY leads DESC, total_mentions DESC
        LIMIT 10
    """, (user["id"],)).fetchall()
    conn.close()

    return {"keywords": [dict(r) for r in rows]}


@app.get("/api/export")
async def api_export(request: Request,
                     source: str = Query("all"),
                     lead_status: str = Query("all"),
                     date_from: str = Query(""),
                     date_to: str = Query("")):
    """Export mentions as CSV."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    conn = get_db()

    conditions = ["m.user_id = ?"]
    params = [user["id"]]

    if source and source != "all":
        if source == "hackernews":
            conditions.append("m.subreddit = 'HackerNews' AND m.reddit_id NOT LIKE 'hn-job-%'")
        elif source == "hn_jobs":
            conditions.append("m.subreddit = 'HackerNews' AND m.reddit_id LIKE 'hn-job-%'")
        elif source == "stackexchange":
            conditions.append("m.subreddit = 'StackOverflow'")
        elif source == "generic":
            conditions.append("m.subreddit NOT IN ('HackerNews', 'StackOverflow')")

    if lead_status == "leads":
        conditions.append("m.is_lead = 1")
    elif lead_status == "noise":
        conditions.append("m.is_lead = 0")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    if date_from == "today":
        conditions.append("DATE(m.found_at) = ?")
        params.append(today)
    elif date_from == "week":
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        conditions.append("DATE(m.found_at) >= ?")
        params.append(week_ago)
    elif date_from == "month":
        month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        conditions.append("DATE(m.found_at) >= ?")
        params.append(month_ago)
    elif date_from:
        conditions.append("DATE(m.found_at) >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("DATE(m.found_at) <= ?")
        params.append(date_to)

    where_clause = " AND ".join(conditions)

    mentions = conn.execute(f"""
        SELECT m.title, m.text, m.subreddit, m.author, m.reddit_score, m.num_comments,
               m.url, m.is_lead, m.lead_reason, m.relevance_score, m.found_at, k.keyword
        FROM mentions m
        JOIN keywords k ON m.keyword_id = k.id
        WHERE {where_clause}
        ORDER BY m.found_at DESC
    """, params).fetchall()
    conn.close()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Text", "Source", "Author", "Score", "Comments", "URL",
                     "Is Lead", "Lead Reason", "Relevance", "Keyword", "Found At"])
    for m in mentions:
        writer.writerow([
            m["title"] or "", m["text"] or "", m["subreddit"] or "", m["author"] or "",
            m["reddit_score"] or 0, m["num_comments"] or 0, m["url"] or "",
            "Yes" if m["is_lead"] else "No", m["lead_reason"] or "",
            m["relevance_score"] or 0, m["keyword"] or "", m["found_at"] or ""
        ])

    csv_content = output.getvalue()
    output.close()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=signalseek_export_{timestamp}.csv"}
    )


@app.get("/api/stats")
async def api_stats(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM mentions WHERE user_id = ?", (user["id"],)).fetchone()[0]
    leads = conn.execute("SELECT COUNT(*) FROM mentions WHERE user_id = ? AND is_lead = 1", (user["id"],)).fetchone()[0]
    keywords = conn.execute("SELECT COUNT(*) FROM keywords WHERE user_id = ?", (user["id"],)).fetchone()[0]
    conn.close()

    return {"total_mentions": total, "leads_found": leads, "keywords": keywords}


# --- Health ---


@app.get("/health")
async def health():
    return {"status": "ok", "service": "SignalSeek"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8420)
