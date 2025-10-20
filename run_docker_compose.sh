#!/bin/bash
# run_docker_compose.sh - Start PostgreSQL container with docker-compose

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if .env.local exists
if [ ! -f .env.local ]; then
    log_error ".env.local not found!"
    log_info "Please create .env.local by copying .env.example:"
    log_info "  cp .env.example .env.local"
    log_info "Then update it with your desired settings."
    exit 1
fi

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed!"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_error "docker-compose or 'docker compose' is not available!"
    exit 1
fi

log_info "Starting PostgreSQL 15 container..."

# Start the services
if docker compose up -d; then
    log_success "PostgreSQL container started!"
    
    # Wait a moment for the container to initialize
    sleep 2
    
    # Show status
    log_info "Container status:"
    docker compose ps
    
    # Display connection info
    log_info ""
    log_info "PostgreSQL Connection Details:"
    log_info "  Host:     localhost"
    log_info "  Port:     5432"
    log_info "  Database: $(grep POSTGRES_DB .env.local | cut -d '=' -f2)"
    log_info "  User:     $(grep POSTGRES_USER .env.local | cut -d '=' -f2)"
    log_info ""
    
    # Check health
    log_info "Checking database health..."
    for i in {1..5}; do
        if docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
            log_success "Database is ready!"
            exit 0
        fi
        log_info "Attempt $i/5 - waiting for database..."
        sleep 2
    done
    
    log_warning "Database may still be initializing. Check logs with: docker compose logs -f postgres"
else
    log_error "Failed to start PostgreSQL container!"
    exit 1
fi
