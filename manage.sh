#!/bin/bash

# Management Script for fengwen2 Astrology Project
# This script provides common management tasks

set -e

PROJECT_NAME="fengwen2"
PROJECT_USER="callmeplayxcpc" 
PROJECT_HOME="/home/callmeplayxcpc/deploy/fengwen2"
SERVICE_NAME="${PROJECT_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}$1${NC}"
}

# Function to check if service is running
check_service_status() {
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        return 0
    else
        return 1
    fi
}

# Function to show service status
show_status() {
    print_header "🔮 Fengwen2 Service Status"
    echo "=========================="
    
    if check_service_status; then
        print_status "Service is ${GREEN}RUNNING${NC}"
    else
        print_warning "Service is ${RED}STOPPED${NC}"
    fi
    
    echo ""
    echo "Detailed status:"
    sudo systemctl status ${SERVICE_NAME} --no-pager -l
    
    echo ""
    echo "Recent logs:"
    sudo journalctl -u ${SERVICE_NAME} --no-pager -n 10
}

# Function to start service
start_service() {
    print_header "🚀 Starting Fengwen2 Service"
    print_status "Starting ${SERVICE_NAME}..."
    sudo systemctl start ${SERVICE_NAME}
    sleep 3
    
    if check_service_status; then
        print_status "Service started successfully!"
    else
        print_error "Failed to start service"
        sudo journalctl -u ${SERVICE_NAME} --no-pager -n 20
        exit 1
    fi
}

# Function to stop service
stop_service() {
    print_header "⏹️ Stopping Fengwen2 Service"
    print_status "Stopping ${SERVICE_NAME}..."
    sudo systemctl stop ${SERVICE_NAME}
    sleep 2
    print_status "Service stopped"
}

# Function to restart service
restart_service() {
    print_header "🔄 Restarting Fengwen2 Service"
    print_status "Restarting ${SERVICE_NAME}..."
    sudo systemctl restart ${SERVICE_NAME}
    sleep 3
    
    if check_service_status; then
        print_status "Service restarted successfully!"
    else
        print_error "Failed to restart service"
        sudo journalctl -u ${SERVICE_NAME} --no-pager -n 20
        exit 1
    fi
}

# Function to show logs
show_logs() {
    print_header "📋 Fengwen2 Service Logs"
    echo "Press Ctrl+C to stop following logs"
    echo "=========================="
    sudo journalctl -u ${SERVICE_NAME} -f
}

# Function to show recent logs
show_recent_logs() {
    local lines=${1:-50}
    print_header "📋 Fengwen2 Recent Logs (${lines} lines)"
    echo "=========================="
    sudo journalctl -u ${SERVICE_NAME} --no-pager -n ${lines}
}

# Function to backup database
backup_database() {
    print_header "💾 Database Backup"
    local backup_dir="${PROJECT_HOME}/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="${backup_dir}/astrology_${timestamp}.db"
    
    # Create backup directory
    sudo -u ${PROJECT_USER} mkdir -p "${backup_dir}"
    
    if [ -f "${PROJECT_HOME}/astrology.db" ]; then
        print_status "Creating backup: ${backup_file}"
        sudo -u ${PROJECT_USER} cp "${PROJECT_HOME}/astrology.db" "${backup_file}"
        print_status "Backup created successfully!"
        
        # Keep only last 7 backups
        print_status "Cleaning old backups (keeping last 7)..."
        sudo -u ${PROJECT_USER} ls -t "${backup_dir}"/astrology_*.db 2>/dev/null | tail -n +8 | xargs -r rm -f
    else
        print_warning "Database file not found: ${PROJECT_HOME}/astrology.db"
    fi
}

# Function to update project
update_project() {
    print_header "📦 Project Update"
    print_warning "This will update the project code. Make sure you have a backup!"
    
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Update cancelled"
        exit 0
    fi
    
    # Backup database first
    backup_database
    
    # Stop service
    print_status "Stopping service for update..."
    sudo systemctl stop ${SERVICE_NAME}
    
    # Look for new package
    PACKAGE_FILE=$(ls ${PROJECT_NAME}_*.tar.gz 2>/dev/null | tail -1 || echo "")
    
    if [ -z "$PACKAGE_FILE" ]; then
        print_error "No package file found. Please upload the new package first."
        exit 1
    fi
    
    print_status "Found package: $PACKAGE_FILE"
    
    # Backup current installation
    print_status "Backing up current installation..."
    sudo tar -czf "${PROJECT_HOME}_backup_$(date +%Y%m%d_%H%M%S).tar.gz" -C /opt "${PROJECT_NAME}"
    
    # Extract new version
    print_status "Extracting new version..."
    sudo tar -xzf "$PACKAGE_FILE" -C /tmp/
    sudo cp -r /tmp/${PROJECT_NAME}/* "${PROJECT_HOME}/"
    sudo chown -R ${PROJECT_USER}:${PROJECT_USER} "${PROJECT_HOME}"
    
    # Update dependencies
    print_status "Updating dependencies..."
    sudo -u ${PROJECT_USER} bash -c "cd ${PROJECT_HOME} && ~/.local/bin/uv sync"
    
    # Update database schema if needed
    print_status "Updating database..."
    sudo -u ${PROJECT_USER} bash -c "cd ${PROJECT_HOME} && ~/.local/bin/uv run python -c 'import sys; sys.path.append(\"src\"); from fengwen2.database import Base, engine; Base.metadata.create_all(bind=engine); print(\"Database updated!\")'"
    
    # Start service
    print_status "Starting service..."
    sudo systemctl start ${SERVICE_NAME}
    
    sleep 3
    if check_service_status; then
        print_status "Update completed successfully!"
    else
        print_error "Service failed to start after update"
        sudo journalctl -u ${SERVICE_NAME} --no-pager -n 20
        exit 1
    fi
}

# Function to check system health
check_health() {
    print_header "🏥 System Health Check"
    echo "======================"
    
    # Check service status
    if check_service_status; then
        print_status "✅ Service is running"
    else
        print_error "❌ Service is not running"
    fi
    
    # Check API health
    print_status "Checking API health..."
    if curl -s http://localhost:8000/health > /dev/null; then
        print_status "✅ API is responding"
    else
        print_error "❌ API is not responding"
    fi
    
    # Check database
    print_status "Checking database..."
    if [ -f "${PROJECT_HOME}/astrology.db" ]; then
        print_status "✅ Database file exists"
        db_size=$(du -h "${PROJECT_HOME}/astrology.db" | cut -f1)
        print_status "   Database size: ${db_size}"
    else
        print_error "❌ Database file not found"
    fi
    
    # Check disk space
    print_status "Checking disk space..."
    df -h "${PROJECT_HOME}" | tail -1 | while read filesystem size used avail percent mount; do
        print_status "   Disk usage: ${used}/${size} (${percent})"
    done
    
    # Check memory usage
    print_status "Checking memory usage..."
    free -h | grep Mem | awk '{print "   Memory: " $3 "/" $2 " (" $3/$2*100 "%)"}'
    
    # Check recent errors
    print_status "Checking recent errors..."
    error_count=$(sudo journalctl -u ${SERVICE_NAME} --since "1 hour ago" --no-pager | grep -i error | wc -l)
    if [ "$error_count" -eq 0 ]; then
        print_status "✅ No recent errors"
    else
        print_warning "⚠️ Found ${error_count} recent errors"
    fi
}

# Function to show help
show_help() {
    print_header "🔮 Fengwen2 Management Script"
    echo "Usage: $0 {command}"
    echo ""
    echo "Commands:"
    echo "  status          Show service status and recent logs"
    echo "  start           Start the service"
    echo "  stop            Stop the service" 
    echo "  restart         Restart the service"
    echo "  logs            Show live logs (follow mode)"
    echo "  logs-recent     Show recent logs (default: 50 lines)"
    echo "  backup          Backup the database"
    echo "  update          Update the project (requires new package)"
    echo "  health          Run system health check"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 status"
    echo "  $0 logs-recent 100"
    echo "  $0 restart"
    echo ""
}

# Main script logic
case "${1:-}" in
    "status")
        show_status
        ;;
    "start")
        start_service
        ;;
    "stop")
        stop_service
        ;;
    "restart")
        restart_service
        ;;
    "logs")
        show_logs
        ;;
    "logs-recent")
        show_recent_logs "${2:-50}"
        ;;
    "backup")
        backup_database
        ;;
    "update")
        update_project
        ;;
    "health")
        check_health
        ;;
    "help"|"-h"|"--help"|"")
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac