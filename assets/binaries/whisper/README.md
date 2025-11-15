# Whisper.cpp Server

This directory contains the Whisper.cpp server binary, which provides HTTP endpoints for speech-to-text transcription using the Whisper model.

## Overview

The Whisper server is a lightweight HTTP server that accepts audio files and returns transcriptions. It uses the GGML (Generalized Graphics Markup Language) quantized Whisper models for efficient inference.

## Quick Start

The server is managed by the `dy.sh` script in the project root:

```bash
# Start the Whisper server
./dy.sh up

# Stop the Whisper server
./dy.sh down

# Restart the Whisper server
./dy.sh restart

# Check server status
./dy.sh status
```

## Configuration

Server configuration is managed through environment variables in `.env.local`:

```env
# Whisper Server Configuration
WHISPER_MODEL_PATH=assets/models/ggml-large-v2.bin
WHISPER_HOST=localhost
WHISPER_PORT=50021
WHISPER_PUBLIC_PATH=./

# Binary paths
WINDOWS_WHISPER_SERVER_PATH=assets/binaries/whisper/whisper-server.exe
MAC_WHISPER_SERVER_PATH=assets/binaries/whisper/whisper-server
```

## API Endpoints

### `/inference` - Transcribe Audio

Transcribes an audio file and returns the text.

**Request:**
```bash
curl http://localhost:50021/inference \
  -H "Content-Type: multipart/form-data" \
  -F file="@audio.wav" \
  -F temperature="0.0" \
  -F response_format="json"
```

**Response:**
```json
{
  "result": "The transcribed text from the audio file"
}
```

### `/load` - Load Model

Loads a different model at runtime.

**Request:**
```bash
curl http://localhost:50021/load \
  -H "Content-Type: multipart/form-data" \
  -F model="path/to/model.bin"
```

## Common Options

- `--host` - Server hostname (default: localhost)
- `--port` - Server port (default: 50021)
- `--model` - Path to the GGML model file
- `--public` - Path to public web interface folder
- `--convert` - Convert audio to WAV format (requires ffmpeg)
- `--threads` - Number of threads for computation
- `--language` - Language code (e.g., 'en', 'auto' for auto-detect)
- `--translate` - Translate to English

## Models

Place GGML quantized Whisper models in the `assets/models/` directory:

- `ggml-tiny.en.bin` - Tiny English model (~39M)
- `ggml-base.en.bin` - Base English model (~141M)
- `ggml-large-v2.bin` - Large v2 model (~775M) - Recommended

## Performance Tips

1. **Use quantized models** for faster inference
2. **Adjust threads** based on CPU cores for optimal performance
3. **Enable `--convert`** if you need to handle various audio formats
4. **Use GPU acceleration** if available on your system

## Security Notes

⚠️ **Important**: 
- Do not run the server with administrative privileges
- Ensure the server runs in a sandbox environment
- Validate and sanitize all inputs
- Be cautious with file upload functionality
- The server accepts user file uploads and uses ffmpeg for format conversions

## Troubleshooting

**Server won't start:**
- Check if port is already in use: `netstat -an | grep 50021`
- Verify model file exists at the specified path
- Check logs in `logs/whisper.log`

**High memory usage:**
- Use a smaller model (tiny or base instead of large)
- Reduce threads: `--threads 2`

**Audio conversion issues:**
- Ensure ffmpeg is installed and in PATH
- The `--convert` flag requires ffmpeg

## References

- [Whisper.cpp Repository](https://github.com/ggml-org/whisper.cpp)
- [Whisper.cpp Server Docs](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server)
- [OpenAI Whisper](https://github.com/openai/whisper)
