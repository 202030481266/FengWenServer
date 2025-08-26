#!/bin/bash
echo "Stopping Fengwen2 server..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
echo "Server stopped."