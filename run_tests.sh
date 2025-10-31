#!/usr/bin/env bash
# Test runner script for database connection tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TEST_TYPE="unit"
VERBOSE=false
COVERAGE=false

# Function to print help
print_help() {
    cat <<EOF
Usage: ./run_tests.sh [OPTIONS]

OPTIONS:
    -t, --type TYPE         Type of tests to run: unit, integration, all (default: unit)
    -v, --verbose           Enable verbose output
    -c, --coverage          Generate coverage report
    -h, --help              Print this help message

EXAMPLES:
    # Run unit tests only
    ./run_tests.sh --type unit

    # Run integration tests with verbose output
    ./run_tests.sh --type integration --verbose

    # Run all tests with coverage
    ./run_tests.sh --type all --coverage

    # Run unit tests with verbose output and coverage
    ./run_tests.sh --type unit --verbose --coverage

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--type)
            TEST_TYPE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_help
            exit 1
            ;;
    esac
done

# Validate test type
if [[ ! "$TEST_TYPE" =~ ^(unit|integration|all)$ ]]; then
    echo -e "${RED}Error: Invalid test type '$TEST_TYPE'${NC}"
    echo "Valid types: unit, integration, all"
    exit 1
fi

# Build pytest command
PYTEST_CMD="pytest"

# Add verbosity
if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -v"
else
    PYTEST_CMD="$PYTEST_CMD -q"
fi

# Add coverage
if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=source/server --cov-report=html --cov-report=term"
fi

# Run tests based on type
echo -e "${BLUE}Running $TEST_TYPE tests...${NC}"
echo ""

case $TEST_TYPE in
    unit)
        echo -e "${YELLOW}Running unit tests (mocked, no database required)${NC}"
        $PYTEST_CMD tests/unit/ -m "not integration"
        ;;
    integration)
        echo -e "${YELLOW}Running integration tests (requires PostgreSQL and MySQL)${NC}"
        $PYTEST_CMD tests/integration/ -m integration
        ;;
    all)
        echo -e "${YELLOW}Running all tests${NC}"
        $PYTEST_CMD tests/
        ;;
esac

# Print coverage report location if generated
if [ "$COVERAGE" = true ]; then
    echo ""
    echo -e "${GREEN}Coverage report generated at: htmlcov/index.html${NC}"
fi

echo ""
echo -e "${GREEN}Tests completed successfully!${NC}"
