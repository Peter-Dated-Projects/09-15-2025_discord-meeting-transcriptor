"""
Flask microservice for Whisper transcription.
Wraps whisper-server with a simple REST API.
"""

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, request, jsonify

from config import config
from whisper_server import WhisperServer
from timestamp_sanitizer import sanitize_whisper_result

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Global whisper server instance
whisper_server = WhisperServer()

# Lock to serialize transcription requests
transcription_lock = threading.Lock()


@app.route("/health", methods=["GET"])
def health_check():
    """
    Health check endpoint.
    Returns the status of the Flask app and whisper binary availability.
    """
    errors = config.validate()

    health_status = {
        "status": "ok" if not errors else "degraded",
        "whisper_binary_exists": config.whisper_binary_path.exists(),
        "whisper_model_exists": config.whisper_model_path.exists(),
        "whisper_server_running": whisper_server.is_running,
    }

    if errors:
        health_status["errors"] = errors

    status_code = 200 if not errors else 503
    return jsonify(health_status), status_code


@app.route("/inference", methods=["POST"])
def inference():
    """
    Perform inference (transcription) on an audio file.

    Accepts multipart/form-data with:
    - file: Audio file (mp3, wav, etc.)
    - word_timestamps: Optional word timestamps flag (default: True)
    - response_format: Optional format (default: verbose_json)
    - temperature: Optional temperature parameter (default: 0.0)
    - temperature_inc: Optional temperature increment (default: 0.2)
    - language: Optional language code (default: en)

    Returns the raw JSON response from whisper-server.
    """
    # Check if a transcription is already in progress
    if not transcription_lock.acquire(blocking=False):
        logger.warning("Transcription request rejected: another transcription in progress")
        return (
            jsonify({"error": "A transcription is already in progress. Please try again later."}),
            429,
        )

    temp_file_path: Optional[Path] = None

    try:
        # Validate request
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Get optional parameters (matching whisper_server.py client expectations)
        word_timestamps = request.form.get("word_timestamps", "True")
        response_format = request.form.get("response_format", "verbose_json")
        temperature = request.form.get("temperature", "0.0")
        temperature_inc = request.form.get("temperature_inc", "0.2")
        language = request.form.get("language", "en")

        logger.info(
            f"Transcription request: file={file.filename}, "
            f"format={response_format}, word_timestamps={word_timestamps}"
        )

        # Save uploaded file to temp directory
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
        temp_file_path = Path(temp_file.name)
        file.save(str(temp_file_path))
        temp_file.close()

        logger.info(f"Saved uploaded file to: {temp_file_path}")

        # Start whisper server
        logger.info("Starting whisper server...")
        whisper_server.start_server()

        # Prepare inference request
        inference_url = f"{config.whisper_url}/inference"

        files = {"file": (file.filename, open(temp_file_path, "rb"), "audio/mpeg")}

        # Prepare all parameters for whisper-server
        data = {
            "word_timestamps": word_timestamps,
            "response_format": response_format,
            "temperature": temperature,
            "temperature_inc": temperature_inc,
            "language": language,
        }

        logger.info(f"Sending inference request to {inference_url}")

        # Call whisper-server /inference endpoint
        response = requests.post(
            inference_url, files=files, data=data, timeout=config.inference_timeout
        )

        # Close the file handle
        files["file"][1].close()

        if response.status_code != 200:
            logger.error(f"Whisper server error: {response.status_code} - {response.text}")
            return (
                jsonify(
                    {
                        "error": f"Whisper server returned error: {response.status_code}",
                        "details": response.text,
                    }
                ),
                502,
            )

        # Get raw response from whisper-server
        raw = response.json()

        # Sanitize timestamps to fix whisper-cpp bugs with long audio files
        try:
            raw = sanitize_whisper_result(raw)
        except Exception as e:
            logger.error(f"Failed to sanitize whisper timestamps: {e}", exc_info=True)
            # Fall back to raw if sanitizer fails

        # Return the sanitized response
        logger.info("Received response from whisper server, forwarding to client")

        return raw, 200

    except requests.exceptions.Timeout:
        logger.error("Whisper server request timed out")
        return (
            jsonify(
                {"error": "Transcription request timed out", "timeout": config.inference_timeout}
            ),
            504,
        )

    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}", exc_info=True)
        return jsonify({"error": "Transcription failed", "details": str(e)}), 500

    finally:
        # Always cleanup
        try:
            # Stop whisper server
            whisper_server.stop_server()
        except Exception as e:
            logger.error(f"Error stopping whisper server: {e}")

        try:
            # Delete temp file
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink()
                logger.info(f"Deleted temp file: {temp_file_path}")
        except Exception as e:
            logger.error(f"Error deleting temp file: {e}")

        # Release lock
        transcription_lock.release()


if __name__ == "__main__":
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.warning("Server will start but may not function correctly")

    logger.info(f"Starting Flask app on {config.flask_host}:{config.flask_port}")
    logger.info(f"Whisper binary: {config.whisper_binary_path}")
    logger.info(f"Whisper model: {config.whisper_model_path}")
    logger.info(f"Debug mode: {config.flask_debug}")

    app.run(host=config.flask_host, port=config.flask_port, debug=config.flask_debug)
