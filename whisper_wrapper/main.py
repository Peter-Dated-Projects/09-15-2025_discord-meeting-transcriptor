"""
Main entry point for Whisper Flask microservice.
Run this file to start the transcription service.
"""

from app import app, config, logger


if __name__ == "__main__":
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.warning("Server will start but may not function correctly")

    logger.info("=" * 60)
    logger.info("Whisper Flask Microservice")
    logger.info("=" * 60)
    logger.info(f"Starting Flask app on {config.flask_host}:{config.flask_port}")
    logger.info(f"Whisper binary: {config.whisper_binary_path}")
    logger.info(f"Whisper model: {config.whisper_model_path}")
    logger.info(f"Debug mode: {config.flask_debug}")
    logger.info("=" * 60)

    # Start Flask application
    app.run(host=config.flask_host, port=config.flask_port, debug=config.flask_debug)
