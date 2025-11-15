#!/bin/bash

# Script to run Ollama server
# Loads environment variables from .env.local and starts the Ollama server

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables from .env.local
ENV_FILE="$PROJECT_ROOT/.env.local"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env.local file not found at $ENV_FILE"
    exit 1
fi

# Source the environment file
set -a  # automatically export all variables
source "$ENV_FILE"
set +a

echo "Starting Ollama server..."
echo "Host: ${OLLAMA_HOST:-localhost}"
echo "Port: ${OLLAMA_PORT:-11434}"
echo "Model: ${OLLAMA_MODEL:-gpt-oss:20b}"

# Set Ollama environment variables
export OLLAMA_HOST="${OLLAMA_HOST:-localhost}"
export OLLAMA_PORT="${OLLAMA_PORT:-11434}"

# Check if ollama command exists
if ! command -v ${OLLAMA_COMMAND_PATH:-ollama} &> /dev/null; then
    echo "Error: Ollama command not found. Please install Ollama first."
    echo "Visit: https://ollama.ai for installation instructions"
    exit 1
fi

# Start Ollama server
echo "Running: ${OLLAMA_COMMAND_PATH:-ollama} serve"
${OLLAMA_COMMAND_PATH:-ollama} serve
