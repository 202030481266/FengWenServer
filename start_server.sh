#!/bin/bash

set -e

# Change to project directory
cd /home/ubuntu/FengWenServer/

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found. Please create .env file with required credentials."
    exit 1
fi

# Install/update dependencies
echo "📦 Installing/updating dependencies..."
uv sync

# Set up database
echo "🗄️ Setting up database..."
uv run python -c "
import sys
sys.path.append('src')
from fengwen2.database import Base, engine
print('Creating database tables...')
Base.metadata.create_all(bind=engine)
print('Database setup complete!')
"

# Start server in background
echo "🚀 Starting server in background..."
nohup uv run uvicorn src.fengwen2.main:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
echo "Server started in background. PID: $!"
echo "Logs: tail -f server.log"
echo "🌐 Server accessible at: http://localhost:8000"
