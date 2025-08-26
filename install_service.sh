#!/bin/bash

set -e

PROJECT_DIR="/home/callmeplayxcpc/deploy/fengwen2"
SERVICE_NAME="fengwen2"

echo "🔮 Installing Fengwen2 as a systemd service..."

# Check if we're in the project directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: Must be run from project directory"
    exit 1
fi

# Check if service file exists
if [ ! -f "${SERVICE_NAME}.service" ]; then
    echo "❌ Error: ${SERVICE_NAME}.service file not found"
    exit 1
fi

# Copy service file to systemd directory
echo "📋 Installing systemd service..."
sudo cp "${SERVICE_NAME}.service" "/etc/systemd/system/"

# Reload systemd
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

# Enable service to start on boot
echo "🚀 Enabling service to start on boot..."
sudo systemctl enable "${SERVICE_NAME}"

echo "✅ Service installed successfully!"
echo ""
echo "Service management commands:"
echo "  sudo systemctl start ${SERVICE_NAME}     # Start the service"
echo "  sudo systemctl stop ${SERVICE_NAME}      # Stop the service"
echo "  sudo systemctl restart ${SERVICE_NAME}   # Restart the service"
echo "  sudo systemctl status ${SERVICE_NAME}    # Check service status"
echo ""
echo "Or use the management script:"
echo "  ./manage.sh start     # Start the service"
echo "  ./manage.sh stop      # Stop the service"
echo "  ./manage.sh status    # Check status"
echo "  ./manage.sh logs      # View logs"
echo ""
echo "To start the service now, run:"
echo "  sudo systemctl start ${SERVICE_NAME}"