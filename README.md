# 🎯 SignalSeek

**AI-powered lead monitoring** — find potential customers discussing products like yours on HackerNews, StackExchange, and more. Stop scrolling forums — start closing leads.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/BrainnyAI/signalseek)
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/signalseek)

---

## What it does

1. **Add keywords** — any product category, tool name, or problem (e.g. "website builder", "project management")
2. **We scan sources** — HackerNews, StackExchange, HN job threads — every 30 minutes
3. **AI qualifies leads** — each mention gets scored: 🔴 lead · 🟡 question · 🟣 competitor complaint · ⚪ noise
4. **Get Telegram alerts** — real leads land in your DMs, noise stays out

## Live Demo

| | |
|---|---|
| 🌐 App | ~~http://195.26.231.158~~ (deploy your own!) |
| 🧪 Demo login | Register at `/register` |

## Quick Start

```bash
git clone https://github.com/BrainnyAI/signalseek.git
cd signalseek

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Set Telegram bot token for alerts (optional)
export TELEGRAM_BOT_TOKEN=your_bot_token

python main.py
# → http://localhost:8420
```

## One-Click Deploy

### Render (easiest — free tier included)
Click the **Deploy to Render** button above, or:
1. Fork this repo
2. Connect to [Render](https://render.com)
3. Select "Blueprint" → picks up `render.yaml` automatically

### Railway
```bash
railway init
railway up
```
Or click the Railway button above.

### Fly.io
```bash
flyctl launch
flyctl deploy
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 · FastAPI |
| Database | SQLite (WAL mode) |
| Monitoring | HN Algolia API · StackExchange API · Reddit (OAuth) |
| Scoring | Heuristic + LLM (optional) |
| Alerts | Telegram Bot API |
| Frontend | Jinja2 · Vanilla CSS (dark theme) |

## Architecture

```
User adds keyword ──→ [HN Algolia] ──→ raw mention
                    [StackExchange] ──→ raw mention
                    [HN Jobs] ──→ raw mention
                                         │
                                    [AI Scorer]
                                      │  ↓   └── noise (discard)
                                      │  ↓
                                      │   └── lead (score ≥ 0.5)
                                      │        │
                              [Telegram Alert]  [Dashboard]
```

## Environment

| Variable | Required | Get it from |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | For alerts | [@BotFather](https://t.me/botfather) |
| `SECRET_KEY` | Production | `openssl rand -hex 32` |
| `STACKEXCHANGE_KEY` | Optional | [StackApps](https://stackapps.com) |

## Why this exists

I built SignalSeek because I was tired of manually scanning Reddit/HN for leads and finding the same tools doing keyword-only matching that generate 90% noise. SignalSeek uses AI (heuristic for free tier, LLM-powered for paid) to tell you *who is actually ready to buy*.

## License

MIT — build, fork, sell, enjoy.
