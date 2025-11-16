#!/bin/bash

# Script to run Whisper server
# Loads environment variables from .env.local and starts the Whisper server
#
# NOTE: For production use, consider using the Flask microservice instead:
#   cd whisper_wrapper && python main.py
# This script is primarily for manual debugging and testing.

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

echo "Starting Whisper server..."

# Detect OS and set appropriate path
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    WHISPER_PATH="${MAC_WHISPER_SERVER_PATH:-assets/binaries/whisper/whisper-server}"
    FFMPEG_PATH="${MAC_FFMPEG_PATH:-assets/binaries/ffmpeg}"
    FFPROBE_PATH="${MAC_FFPROBE_PATH:-assets/binaries/ffprobe}"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    # Windows
    WHISPER_PATH="${WINDOWS_WHISPER_SERVER_PATH:-assets/binaries/whisper/whisper-server.exe}"
    FFMPEG_PATH="${WINDOWS_FFMPEG_PATH:-assets/binaries/ffmpeg.exe}"
    FFPROBE_PATH="${WINDOWS_FFPROBE_PATH:-assets/binaries/ffprobe.exe}"
else
    # Linux or other
    WHISPER_PATH="${MAC_WHISPER_SERVER_PATH:-assets/binaries/whisper/whisper-server}"
    FFMPEG_PATH="${MAC_FFMPEG_PATH:-assets/binaries/ffmpeg}"
    FFPROBE_PATH="${MAC_FFPROBE_PATH:-assets/binaries/ffprobe}"
fi

# Convert to absolute path
WHISPER_PATH="$PROJECT_ROOT/$WHISPER_PATH"

echo "Whisper binary path: $WHISPER_PATH"

# Check if whisper server exists
if [ ! -f "$WHISPER_PATH" ]; then
    echo "Error: Whisper server binary not found at $WHISPER_PATH"
    echo "Please ensure the Whisper server binary is in the correct location."
    exit 1
fi

# Make sure the binary is executable (for Unix-like systems)
if [[ "$OSTYPE" != "msys" && "$OSTYPE" != "cygwin" && "$OSTYPE" != "win32" ]]; then
    chmod +x "$WHISPER_PATH"
fi

# Set model path from environment variable or use default
MODEL_PATH="${WHISPER_MODEL_PATH:-assets/models/ggml-large-v2.bin}"
# Convert to absolute path if it's relative
if [[ "$MODEL_PATH" != /* ]]; then
    MODEL_PATH="$PROJECT_ROOT/$MODEL_PATH"
fi

# Use Whisper server configuration from environment variables
WHISPER_HOST="${WHISPER_HOST:-localhost}"
WHISPER_PORT="${WHISPER_PORT:-50021}"

# Set public path for serving the web interface from environment variable
PUBLIC_PATH="${WHISPER_PUBLIC_PATH:-./}"
# Convert to absolute path if it's relative
if [[ "$PUBLIC_PATH" != /* ]]; then
    PUBLIC_PATH="$PROJECT_ROOT/$PUBLIC_PATH"
fi

echo "Host: $WHISPER_HOST"
echo "Port: $WHISPER_PORT"
echo "Model path: $MODEL_PATH"
echo "Public path: $PUBLIC_PATH"

# Check if model file exists
if [ ! -f "$MODEL_PATH" ]; then
    echo "Warning: Whisper model not found at $MODEL_PATH"
    echo "Please ensure the model file is downloaded to the correct location."
fi

# Check if public directory exists
if [ ! -d "$PUBLIC_PATH" ]; then
    echo "Warning: Public directory not found at $PUBLIC_PATH"
fi

# Run Whisper server
# Adjust parameters as needed for your use case
echo "Running Whisper server..."
"$WHISPER_PATH" \
    -p 2 \
    -sow \
    --host "$WHISPER_HOST" \
    --port "$WHISPER_PORT" \
    --model "$MODEL_PATH" \
    --public "$PUBLIC_PATH" \
    --convert
