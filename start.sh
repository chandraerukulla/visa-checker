#!/bin/bash
set -e

echo "Setting up backend..."
cd backend
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -q -r requirements.txt
playwright install chromium

echo "Starting backend on http://localhost:8000"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

echo "Backend PID: $BACKEND_PID"
echo ""
echo "Open frontend/index.html in your browser to use the checker."
echo "Press Ctrl+C to stop."

wait $BACKEND_PID
