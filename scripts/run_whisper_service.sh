#!/bin/bash

# Script to run Whisper Flask microservice
# This is the recommended way to run whisper for automated transcription
# Usage: ./run_whisper_service.sh [--background]

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WHISPER_WRAPPER="$PROJECT_ROOT/whisper_wrapper"

# Check for background flag
BACKGROUND=false
if [ "$1" == "--background" ]; then
    BACKGROUND=true
fi

echo "Starting Whisper Flask Microservice..."
echo ""

# Check if .env.local exists
if [ ! -f "$PROJECT_ROOT/.env.local" ]; then
    echo "Error: .env.local file not found at $PROJECT_ROOT/.env.local"
    echo "Please create it based on the template in the repository."
    exit 1
fi

# Change to whisper_wrapper directory
cd "$WHISPER_WRAPPER"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "Warning: uv is not installed. Install it with: pip install uv"
    echo "Falling back to python3..."
    USE_UV=false
else
    USE_UV=true
fi

echo ""
echo "Starting Flask application..."
echo ""

if [ "$USE_UV" = true ]; then
    if [ "$BACKGROUND" = true ]; then
        exec uv run main.py
    else
        uv run main.py
    fi
else
    if [ "$BACKGROUND" = true ]; then
        exec python3 main.py
    else
        python3 main.py
    fi
fi
