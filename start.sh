#!/bin/bash
# Start FastAPI server in the background
uvicorn dashboard_server:app --host 0.0.0.0 --port "${PORT:-8090}" &

# Start the Discord bot in the foreground
python main.py
