#!/bin/bash

# Test runner helper script for local/prod environment testing
# REQUIRED: You must specify either 'local' or 'prod'
# Usage: ./run_tests.sh local|prod [pytest_args...]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get environment argument (REQUIRED)
ENV="${1:-}"

# Remaining arguments passed to pytest
shift || true
PYTEST_ARGS="$@"

# Validate environment - REQUIRED
if [[ -z "$ENV" ]]; then
    echo -e "${RED}❌ ERROR: Database environment is REQUIRED${NC}"
    echo ""
    echo "Usage: $0 local|prod [pytest_args...]"
    echo ""
    echo "Choose one environment:"
    echo ""
    echo -e "${BLUE}  local  - Use MySQL (development database)${NC}"
    echo -e "${BLUE}  prod   - Use PostgreSQL (production database)${NC}"
    echo ""
    echo "Examples:"
    echo "  $0 local                           # Run all local tests"
    echo "  $0 prod                            # Run all prod tests"
    echo "  $0 local -k health_check           # Run specific local tests"
    echo "  $0 prod tests/unit -m integration  # Run integration tests in prod"
    exit 1
fi

if [[ ! "$ENV" =~ ^(local|prod)$ ]]; then
    echo -e "${RED}❌ ERROR: Invalid environment '$ENV'${NC}"
    echo ""
    echo "You must choose 'local' or 'prod':"
    echo -e "${BLUE}  local  - MySQL (development)${NC}"
    echo -e "${BLUE}  prod   - PostgreSQL (production)${NC}"
    exit 1
fi

# Print environment info
echo -e "${BLUE}═════════════════════════════════════════${NC}"
if [ "$ENV" = "local" ]; then
    echo -e "${BLUE}🔧 Running tests in LOCAL mode (MySQL)${NC}"
else
    echo -e "${BLUE}🚀 Running tests in PROD mode (PostgreSQL)${NC}"
fi
echo -e "${BLUE}═════════════════════════════════════════${NC}"
echo ""

# Set environment variable as well (for backwards compatibility)
export TEST_ENV="$ENV"
echo -e "${YELLOW}Environment: TEST_ENV=$ENV${NC}"
echo ""

# Run pytest with the --db-env option and specified arguments
echo -e "${YELLOW}Running: uv run pytest --db-env $ENV $PYTEST_ARGS${NC}"
echo ""

# Execute pytest
if uv run pytest --db-env "$ENV" $PYTEST_ARGS; then
    echo ""
    echo -e "${GREEN}✅ Tests passed!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}❌ Tests failed!${NC}"
    exit 1
fi
