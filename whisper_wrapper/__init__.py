"""
Whisper Flask Microservice

A standalone Flask microservice that wraps the whisper-server binary
for audio transcription with a simple REST API.

Usage:
    python main.py

Endpoints:
    GET /health - Health check
    POST /inference - Transcribe audio file
"""

__version__ = "1.0.0"
