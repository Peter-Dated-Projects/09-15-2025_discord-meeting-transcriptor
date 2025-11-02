"""
Unit tests for FFmpeg Manager Service.

These tests use mocks to test the FFmpeg service logic without
requiring actual FFmpeg installation or file conversions.
"""

from unittest.mock import MagicMock, patch

import pytest

from source.services.ffmpeg_manager.manager import FFmpegHandler


# ============================================================================
# FFmpeg Handler Unit Tests
# ============================================================================


@pytest.mark.unit
class TestFFmpegHandlerValidation:
    """Test FFmpeg handler validation logic."""

    def test_validate_ffmpeg_success(self):
        """Test successful FFmpeg validation."""
        # Setup: Create a mock FFmpeg service manager
        mock_service_manager = MagicMock()
        ffmpeg_path = "ffmpeg"

        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        # Mock subprocess.run to simulate successful FFmpeg validation
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Act
            is_valid = handler.validate_ffmpeg()

            # Assert
            assert is_valid is True
            mock_run.assert_called_once()

    def test_validate_ffmpeg_not_found(self):
        """Test FFmpeg validation when FFmpeg is not installed."""
        # Setup
        mock_service_manager = MagicMock()
        ffmpeg_path = "nonexistent_ffmpeg"

        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        # Mock subprocess.run to raise FileNotFoundError
        with patch("subprocess.run", side_effect=FileNotFoundError):
            # Act
            is_valid = handler.validate_ffmpeg()

            # Assert
            assert is_valid is False

    def test_validate_ffmpeg_timeout(self):
        """Test FFmpeg validation when process times out."""
        # Setup
        mock_service_manager = MagicMock()
        ffmpeg_path = "ffmpeg"

        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        # Mock subprocess.run to raise TimeoutExpired
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)):
            # Act
            is_valid = handler.validate_ffmpeg()

            # Assert
            assert is_valid is False


@pytest.mark.unit
class TestFFmpegHandlerConversion:
    """Test FFmpeg handler conversion logic."""

    def test_convert_file_success(self):
        """Test successful file conversion."""
        # Setup
        mock_service_manager = MagicMock()
        ffmpeg_path = "ffmpeg"
        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        input_path = "input.m4a"
        output_path = "output.wav"
        options = {"-f": "s16le", "-ar": "48000", "-ac": "1", "-y": None}

        # Mock subprocess.run to simulate successful conversion
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="conversion successful", stderr=""
            )

            # Act
            success, stdout, stderr = handler.convert_file(input_path, output_path, options)

            # Assert
            assert success is True
            assert stdout == "conversion successful"
            assert stderr == ""
            mock_run.assert_called_once()

    def test_convert_file_failure(self):
        """Test file conversion failure."""
        # Setup
        mock_service_manager = MagicMock()
        ffmpeg_path = "ffmpeg"
        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        input_path = "input.m4a"
        output_path = "output.wav"
        options = {"-f": "s16le"}

        # Mock subprocess.run to simulate failed conversion
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="conversion failed"
            )

            # Act
            success, stdout, stderr = handler.convert_file(input_path, output_path, options)

            # Assert
            assert success is False
            assert stderr == "conversion failed"

    def test_convert_file_timeout(self):
        """Test file conversion timeout."""
        # Setup
        mock_service_manager = MagicMock()
        ffmpeg_path = "ffmpeg"
        handler = FFmpegHandler(mock_service_manager, ffmpeg_path)

        input_path = "input.m4a"
        output_path = "output.wav"
        options = {}

        # Mock subprocess.run to simulate timeout
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 300)):
            # Act
            success, stdout, stderr = handler.convert_file(input_path, output_path, options)

            # Assert
            assert success is False
            assert "timed out" in stderr.lower()
