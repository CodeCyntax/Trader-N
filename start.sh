#!/usr/bin/env bash
set -e

# Navigate to script directory
cd "$(dirname "$0")"

echo "============================================================"
echo " 🚀 Starting Trader-N Autonomous Trading Agent & Web App..."
echo " 🌐 Dashboard URL: http://localhost:8080"
echo " 🛑 Press Ctrl + C in this terminal to stop cleanly"
echo "============================================================"

# Execute the agent with the web dashboard on port 8080
exec .venv/bin/python main.py --port 8080 "$@"
