# SignalSeek 🎯

**AI-powered lead monitoring** — find potential customers discussing your product on HackerNews, StackExchange, and more.

### How it works

1. Add keywords related to your product (e.g. "project management tool", "website monitoring")
2. SignalSeek continuously scans HackerNews & StackExchange for mentions
3. AI scores each mention: is it a lead, complaint, or noise?
4. Get Telegram alerts when real leads appear

### Tech Stack

- **Backend:** Python · FastAPI · SQLite
- **Monitoring:** HN Algolia API · StackExchange API
- **Scoring:** Heuristic pattern-matching (LLM-powered in Pro plan)
- **Alerts:** Telegram Bot API

### Quick Start

```bash
# Clone
git clone https://github.com/BrainnyAI/signalseek.git
cd signalseek

# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run
python main.py
# → http://localhost:8420
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | For alerts | Bot token from @BotFather |
| `SECRET_KEY` | Production | JWT signing secret |
| `STACKEXCHANGE_KEY` | Optional | Higher API rate limits |

### Project Structure

```
signalseek/
├── main.py          # FastAPI server
├── models.py        # SQLite database
├── monitor.py       # Multi-source search engine
├── scorer.py        # AI lead qualification
├── alerts.py        # Telegram dispatch
├── run_pipeline.py  # Cron entrypoint
├── templates/       # Jinja2 HTML
└── static/          # CSS/JS assets
```

### License

MIT
