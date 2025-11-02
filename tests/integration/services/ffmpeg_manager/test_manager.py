"""
Integration tests for FFmpeg Manager Service.

These tests verify the FFmpeg service's ability to convert audio files
in various formats. Tests require a working FFmpeg installation and
a connected server manager.
"""

import os

import pytest

from source.services.manager import ServicesManager


# ============================================================================
# FFmpeg Service Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
class TestFFmpegManagerService:
    """Test FFmpeg Manager Service functionality."""

    async def test_mp3_to_whisper_format_conversion(
        self, services_manager: ServicesManager, tmp_path
    ):
        """
        Test converting an audio file from MP3/M4A format to Whisper-compatible WAV format.

        This test mimics the functionality in playground.py, converting an audio file
        to the format required by OpenAI's Whisper model (16-bit PCM WAV at 48kHz).

        Args:
            services_manager: Fixture providing initialized services
            tmp_path: Pytest fixture providing temporary directory
        """
        # Setup: Define input and output paths
        # Use the test asset audio file
        test_audio_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "assets", "audio-recording-1.m4a"
        )
        
        # Verify test audio file exists
        if not os.path.exists(test_audio_file):
            pytest.skip(
                f"Test audio file not found at {test_audio_file}. "
                "Please ensure tests/assets/audio-recording-1.m4a exists."
            )

        output_path = str(tmp_path / "test_output.wav")

        # Act: Queue the conversion job
        success = await services_manager.ffmpeg_service_manager.queue_mp3_to_whisper_format_job(
            input_path=test_audio_file,
            output_path=output_path,
        )

        # Assert: Verify conversion succeeded
        assert success, "FFmpeg conversion should complete successfully"

        # Assert: Verify output file was created
        assert os.path.exists(output_path), f"Output file should exist at {output_path}"

        # Assert: Verify output file has content
        assert os.path.getsize(output_path) > 0, "Output file should not be empty"

    async def test_ffmpeg_validation(self, services_manager: ServicesManager):
        """
        Test that FFmpeg is properly installed and accessible.

        Args:
            services_manager: Fixture providing initialized services
        """
        # Access the FFmpeg handler through the service manager
        ffmpeg_handler = services_manager.ffmpeg_service_manager.ffmpeg_handler

        # Verify FFmpeg is available
        is_valid = ffmpeg_handler.validate_ffmpeg()

        assert is_valid, (
            "FFmpeg should be installed and accessible. "
            "Please ensure FFmpeg is installed at the configured path."
        )

    @pytest.mark.slow
    async def test_large_file_conversion(
        self, services_manager: ServicesManager, tmp_path
    ):
        """
        Test converting a larger audio file (stress test).

        This test is marked as 'slow' to exclude it from quick test runs.

        Args:
            services_manager: Fixture providing initialized services
            tmp_path: Pytest fixture providing temporary directory
        """
        # This test would use a larger test file if available
        # For now, we'll skip if the large test file doesn't exist
        pytest.skip("Large test file not configured - implement when needed")


# ============================================================================
# FFmpeg Error Handling Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
class TestFFmpegErrorHandling:
    """Test FFmpeg error handling and edge cases."""

    async def test_nonexistent_input_file(
        self, services_manager: ServicesManager, tmp_path
    ):
        """
        Test that conversion fails gracefully with a nonexistent input file.

        Args:
            services_manager: Fixture providing initialized services
            tmp_path: Pytest fixture providing temporary directory
        """
        # Setup: Define paths with nonexistent input
        input_path = str(tmp_path / "nonexistent_file.m4a")
        output_path = str(tmp_path / "output.wav")

        # Act: Attempt conversion
        success = await services_manager.ffmpeg_service_manager.queue_mp3_to_whisper_format_job(
            input_path=input_path,
            output_path=output_path,
        )

        # Assert: Conversion should fail
        assert not success, "Conversion should fail for nonexistent input file"

        # Assert: Output file should not be created
        assert not os.path.exists(
            output_path
        ), "Output file should not exist when conversion fails"

    async def test_invalid_output_path(
        self, services_manager: ServicesManager, tmp_path
    ):
        """
        Test that conversion fails gracefully with an invalid output path.

        Args:
            services_manager: Fixture providing initialized services
            tmp_path: Pytest fixture providing temporary directory
        """
        # Setup: Use test audio file with invalid output directory
        test_audio_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "assets", "audio-recording-1.m4a"
        )

        if not os.path.exists(test_audio_file):
            pytest.skip(f"Test audio file not found at {test_audio_file}")

        # Use a path with a nonexistent directory
        output_path = str(tmp_path / "nonexistent_dir" / "subdir" / "output.wav")

        # Act: Attempt conversion
        success = await services_manager.ffmpeg_service_manager.queue_mp3_to_whisper_format_job(
            input_path=test_audio_file,
            output_path=output_path,
        )

        # Assert: Check if conversion handled the invalid path
        # (Behavior may vary - FFmpeg might create dirs or fail)
        # This test documents the current behavior
        if success:
            # If FFmpeg created the directories, verify output exists
            assert os.path.exists(output_path), "Output should exist if conversion succeeded"
        else:
            # If conversion failed, output should not exist
            assert not os.path.exists(output_path), "Output should not exist if conversion failed"
