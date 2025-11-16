# Whisper Flask Microservice

A standalone Flask microservice that wraps the whisper-server binary for audio transcription.

## Features

- **REST API**: Simple POST endpoint for transcription
- **Process Management**: Automatically starts/stops whisper-server per request
- **File Handling**: Accepts multipart/form-data uploads (mp3, wav, etc.)
- **Concurrency Control**: Serializes requests with 429 response when busy
- **Health Monitoring**: Health check endpoint for service status
- **Comprehensive Logging**: Detailed logs of all operations

## Endpoints

### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "whisper_binary_exists": true,
  "whisper_model_exists": true,
  "whisper_server_running": false
}
```

### `POST /inference`
Transcribe an audio file.

**Request:**
- Content-Type: `multipart/form-data`
- Parameters:
  - `file` (required): Audio file
  - `word_timestamps` (optional): Enable word timestamps (default: True)
  - `response_format` (optional): Response format (default: verbose_json)
  - `temperature` (optional): Temperature parameter (default: 0.0)
  - `temperature_inc` (optional): Temperature increment (default: 0.2)
  - `language` (optional): Language code (default: en)

**Response:**
```json
{
  "text": "Full transcription...",
  "segments": [...],
  "language": "en",
  ...
}
```

*Note: The response is passed through directly from whisper-server without modification.*

**Error Responses:**
- `400`: Bad request (no file, empty filename)
- `429`: Too many requests (transcription in progress)
- `502`: Whisper server error
- `504`: Request timeout
- `503`: Service unavailable (health check failed)

## Configuration

The service uses environment variables from `.env.local` in the project root.

Required variables:
```bash
WHISPER_HOST=localhost
WHISPER_PORT=50021
WHISPER_MODEL_PATH=assets/models/ggml-large-v2.bin
WHISPER_PUBLIC_PATH=./

# OS-specific binary paths
WINDOWS_WHISPER_SERVER_PATH=assets/binaries/whisper/whisper-server.exe
MAC_WHISPER_SERVER_PATH=assets/binaries/whisper/whisper-server

# Flask configuration
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=False
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure `.env.local` exists in the project root with required variables

3. Verify whisper binary and model are in place

## Running

### Development
```bash
python main.py
```

### Production
```bash
# Using gunicorn (recommended)
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:5000 app:app

# Or using Flask directly
python main.py
```

**Note**: Use `-w 1` (single worker) with gunicorn since the service serializes requests internally.

## Example Usage

### Using curl
```bash
# Health check
curl http://localhost:5000/health

# Transcribe a file
curl -X POST http://localhost:5000/inference \
  -F "file=@audio.mp3" \
  -F "word_timestamps=True" \
  -F "response_format=verbose_json" \
  -F "language=en"
```

### Using Python
```python
import requests

# Transcribe
with open('audio.mp3', 'rb') as f:
    response = requests.post(
        'http://localhost:5000/inference',
        files={'file': f},
        data={
            'word_timestamps': 'True',
            'response_format': 'verbose_json',
            'language': 'en'
        }
    )
    
result = response.json()
print(result['text'])
```

## Architecture

The service follows a simple microservice pattern:

1. **Flask App** (`app.py`): REST API endpoints (pass-through proxy)
2. **Whisper Server Manager** (`whisper_server.py`): Process lifecycle management
3. **Configuration** (`config.py`): Environment and settings loader

### Request Flow

1. Client sends POST to `/inference` with audio file
2. Service acquires lock (or returns 429 if busy)
3. Saves file to temp directory
4. Starts whisper-server subprocess
5. Waits for server to be ready (health check)
6. POSTs file to whisper-server `/inference`
7. Returns whisper-server response directly to client (no parsing/modification)
8. Stops whisper-server
9. Cleans up temp file
10. Releases lock

### Concurrency Strategy

For v1, the service **serializes all transcription requests** using a `threading.Lock`:
- Only one transcription runs at a time
- Concurrent requests receive HTTP 429 (Too Many Requests)
- This simplifies resource management since whisper-server is started/stopped per request

Future versions could implement:
- Request queueing
- Long-running whisper-server with multiple workers
- WebSocket progress updates

## Logging

All operations are logged with timestamps:
- Server start/stop events
- Transcription requests and completions
- Errors and warnings
- Whisper-server output

Logs go to stdout by default (easily captured by Docker or systemd).

## Migration from `run_whisper.sh`

This microservice **replaces** the manual `run_whisper.sh` script for production use:

- ✅ Use this Flask service for automated transcription via API
- ℹ️ Keep `run_whisper.sh` for manual debugging and testing

The Flask service uses the same configuration and command-line arguments as the shell script.

## Development Notes

- The whisper-server is started fresh for each transcription request
- Temp files are automatically cleaned up even on errors
- All paths are resolved relative to project root
- OS-specific binary paths are detected automatically
