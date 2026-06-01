# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A two-part app that checks UK immigration status via [view-immigration-status.service.gov.uk](https://view-immigration-status.service.gov.uk). The frontend collects a share code and date of birth; the backend uses Playwright to automate the GOV.UK multi-step form in a headless browser and returns the result HTML.

## Running the project

```bash
# First time / setup
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Start backend (from backend/ with venv active)
uvicorn main:app --reload --port 8000

# Open frontend
open frontend/index.html
```

Or use the convenience script from the project root:
```bash
./start.sh
```

## Architecture

```
visa_website/
├── backend/
│   ├── main.py          # FastAPI app — single POST endpoint
│   └── requirements.txt
└── frontend/
    └── index.html       # Self-contained UI, no build step
```

**Request flow:** `frontend/index.html` → `POST localhost:8000/api/check-immigration-status` → Playwright automates `view-immigration-status.service.gov.uk` → returns result HTML back to frontend.

## Key details

- **Endpoint:** `POST /api/check-immigration-status` — body: `{ share_code: string, date_of_birth: "YYYY-MM-DD" }`
- **Why Playwright:** The GOV.UK checker uses CSRF tokens on every page step, so a headless browser is required (no simple API to call).
- **Frontend API base:** hardcoded to `http://localhost:8000` in `frontend/index.html` — update `API_BASE` if deploying.
- The backend renders in `headless=True` mode; switch to `headless=False` in `main.py` to debug selector issues visually.
