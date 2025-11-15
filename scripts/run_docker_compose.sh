#!/bin/bash
# run_docker_compose.sh - Start / manage local MySQL container(s) with docker-compose.local.yml

set -e

# ─────────────────────────────────────────
# Colors
# ─────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────
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

usage() {
    echo "Usage: ./run_docker_compose.sh [--down [service]] [--restart <service|all>] [--list]"
    echo "  --down [service]      Stop containers (do NOT remove), or only the specified service."
    echo "  --restart <service>   Restart the specified service/container from this compose file."
    echo "  --restart all         Restart all services/containers from this compose file."
    echo "  --list                Show containers/services and their current status (with IP + ports if available)."
}

COMPOSE_FILE="docker-compose.local.yml"

# ─────────────────────────────────────────
# Ensure .env.local exists
# ─────────────────────────────────────────
if [ ! -f .env.local ]; then
    log_error ".env.local not found!"
    log_info "Please create .env.local by copying .env.example:"
    log_info "  cp .env.example .env.local"
    log_info "Then update it with your desired settings."
    exit 1
fi

# ─────────────────────────────────────────
# Read MySQL env (for info printout only)
# ─────────────────────────────────────────
MYSQL_DATABASE=$(grep '^MYSQL_DATABASE=' .env.local | cut -d '=' -f2- || echo "")
MYSQL_USER=$(grep '^MYSQL_USER=' .env.local | cut -d '=' -f2- || echo "")
MYSQL_PASSWORD=$(grep '^MYSQL_PASSWORD=' .env.local | cut -d '=' -f2- || echo "")
MYSQL_ROOT_PASSWORD=$(grep '^MYSQL_ROOT_PASSWORD=' .env.local | cut -d '=' -f2- || echo "")

# ─────────────────────────────────────────
# Check docker
# ─────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed!"
    exit 1
fi

# ─────────────────────────────────────────
# Pick docker compose command
# ─────────────────────────────────────────
docker_compose_cmd=""
if command -v docker compose &> /dev/null; then
    docker_compose_cmd="docker compose"
elif command -v docker-compose &> /dev/null; then
    docker_compose_cmd="docker-compose"
else
    log_error "docker-compose or 'docker compose' is not available!"
    exit 1
fi

# ─────────────────────────────────────────
# Handle CLI args (management mode)
# ─────────────────────────────────────────
if [ "$#" -gt 0 ]; then
    case "$1" in
        --help)
            usage
            exit 0
            ;;

        # ------------------------------
        # Stop / remove all or 1 service
        # ------------------------------
        --down)
            SERVICE="$2"
            if [ -n "$SERVICE" ]; then
                # Stop specific service (do NOT remove container)
                log_info "Stopping service '$SERVICE'..."
                if $docker_compose_cmd -f "$COMPOSE_FILE" stop "$SERVICE"; then
                    log_success "Service '$SERVICE' stopped successfully."
                    exit 0
                else
                    log_error "Failed to stop service '$SERVICE'."
                    exit 1
                fi
            else
                # Stop all services/containers but do not remove them
                log_info "Stopping all services/containers from $COMPOSE_FILE (containers will not be removed)..."
                if $docker_compose_cmd -f "$COMPOSE_FILE" stop; then
                    log_success "All containers stopped. Containers were not removed."
                    exit 0
                else
                    log_error "Failed to stop containers."
                    exit 1
                fi
            fi
            ;;

        # ------------------------------
        # Restart specific service
        # ------------------------------
        --restart)
            SERVICE="$2"
            if [ -z "$SERVICE" ]; then
                log_error "Please specify a service to restart or use 'all'."
                usage
                exit 1
            fi
            
            if [ "$SERVICE" = "all" ]; then
                log_info "Restarting all services..."
                if $docker_compose_cmd -f "$COMPOSE_FILE" restart; then
                    log_success "All services restarted successfully."
                    exit 0
                else
                    # try other compose style just in case
                    if [ "$docker_compose_cmd" = "docker compose" ]; then
                        if docker-compose -f "$COMPOSE_FILE" restart; then
                            log_success "All services restarted successfully."
                            exit 0
                        fi
                    fi
                    log_error "Failed to restart all services."
                    exit 1
                fi
            else
                log_info "Restarting service '$SERVICE'..."
                if $docker_compose_cmd -f "$COMPOSE_FILE" restart "$SERVICE"; then
                    log_success "Service '$SERVICE' restarted successfully."
                    exit 0
                else
                    # try other compose style just in case
                    if [ "$docker_compose_cmd" = "docker compose" ]; then
                        if docker-compose -f "$COMPOSE_FILE" restart "$SERVICE"; then
                            log_success "Service '$SERVICE' restarted successfully."
                            exit 0
                        fi
                    fi
                    log_error "Failed to restart service '$SERVICE'."
                    exit 1
                fi
            fi
            ;;

        # ------------------------------
        # List services
        # ------------------------------
        --list)
            # Try JSON format first (Compose v2)
            LIST_JSON=$($docker_compose_cmd -f "$COMPOSE_FILE" ps --format json 2>/dev/null || true)

            if [ -n "$LIST_JSON" ] && command -v python3 >/dev/null 2>&1; then
                LIST_OUTPUT=$(LIST_JSON="$LIST_JSON" python3 << 'PYCODE'
import os
import json
import sys

raw = os.environ.get("LIST_JSON", "").strip()
if not raw:
    sys.exit(1)

def load_entries(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                return None
        return entries if entries else None
    return data

data = load_entries(raw)
if data is None:
    sys.exit(2)

items = data if isinstance(data, list) else [data]
lines = []

for item in items:
    if isinstance(item, str):
        if item.strip():
            lines.append(item)
        continue

    service = str(item.get("Service") or "")[:20]
    name = str(item.get("Name") or "")[:30]

    state = str(item.get("State") or "")
    health = str(item.get("Health") or "")
    if state == "running" and health:
        status = "running (" + health + ")"
    else:
        status = state

    ports = str(item.get("Ports") or "")[:50]

    line = "{:<22} {:<32} {:<20} {}".format(service, name, status, ports)
    if line.strip():
        lines.append(line)

if not lines:
    sys.exit(3)

print("\n".join(lines))
PYCODE
)
                PY_STATUS=$?
                if [ $PY_STATUS -eq 0 ] && [ -n "$LIST_OUTPUT" ]; then
                    echo "SERVICE               CONTAINER NAME                   STATUS               PORTS"
                    printf '%s\n' "$LIST_OUTPUT"
                    exit 0
                fi
            fi

            FORMAT_TEMPLATE='{{- $pub := or .Publishers .Ports -}}{{printf "%-18s %-29s %-19s %-15s %s" .Service .Name .State "" $pub}}'
            TABLE_OUTPUT=$($docker_compose_cmd -f "$COMPOSE_FILE" ps --format "$FORMAT_TEMPLATE" 2>/dev/null)
            TABLE_STATUS=$?
            if [ $TABLE_STATUS -eq 0 ] && [ -n "$TABLE_OUTPUT" ]; then
                echo "SERVICE              CONTAINER                         STATUS               IP               PORTS"
                printf '%s\n' "$TABLE_OUTPUT"
                exit 0
            fi

            if OUTPUT=$($docker_compose_cmd -f "$COMPOSE_FILE" ps 2>/dev/null); then
                if [ -n "$OUTPUT" ]; then
                    printf '%s\n' "$OUTPUT"
                fi
                exit 0
            fi

            if [ "$docker_compose_cmd" = "docker compose" ]; then
                if OUTPUT=$(docker-compose -f "$COMPOSE_FILE" ps 2>/dev/null); then
                    if [ -n "$OUTPUT" ]; then
                        printf '%s\n' "$OUTPUT"
                    fi
                    exit 0
                fi
            fi

            log_error "Failed to list containers/services."
            exit 1
            ;;

        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
fi

# ─────────────────────────────────────────
# No args → start stack
# ─────────────────────────────────────────
log_info "Starting MySQL container from $COMPOSE_FILE..."

started=false
if $docker_compose_cmd -f "$COMPOSE_FILE" up -d; then
    started=true
fi

if [ "$started" = true ]; then
    log_success "MySQL container started!"

    # Give MySQL a moment
    sleep 2

    # Show status
    log_info "Container status:"
    $docker_compose_cmd -f "$COMPOSE_FILE" ps

    # Connection info (from .env.local)
    log_info ""
    log_info "MySQL Connection Details:"
    log_info "  Host:     localhost"
    log_info "  Port:     3306"
    log_info "  Database: ${MYSQL_DATABASE}"
    log_info "  User:     ${MYSQL_USER}"
    log_info ""

    # Health check loop
    log_info "Checking database health..."
    for i in {1..5}; do
        if [ -n "${MYSQL_PASSWORD}" ]; then
            if $docker_compose_cmd -f "$COMPOSE_FILE" exec -T mysql \
                mysqladmin ping -h localhost -u"${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD}" > /dev/null 2>&1; then
                log_success "Database is ready!"
                exit 0
            fi
        elif [ -n "${MYSQL_ROOT_PASSWORD}" ]; then
            if $docker_compose_cmd -f "$COMPOSE_FILE" exec -T mysql \
                mysqladmin ping -h localhost -u"${MYSQL_USER:-root}" -p"${MYSQL_ROOT_PASSWORD}" > /dev/null 2>&1; then
                log_success "Database is ready!"
                exit 0
            fi
        else
            # no password case
            if $docker_compose_cmd -f "$COMPOSE_FILE" exec -T mysql \
                mysqladmin ping -h localhost -u"${MYSQL_USER:-root}" > /dev/null 2>&1; then
                log_success "Database is ready!"
                exit 0
            fi
        fi

        log_info "Attempt $i/5 - waiting for database..."
        sleep 2
    done

    log_warning "MySQL may still be initializing. Check logs with: $docker_compose_cmd -f $COMPOSE_FILE logs -f mysql"
else
    log_error "Failed to start MySQL container!"
    exit 1
fi
