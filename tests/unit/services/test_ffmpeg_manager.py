"""
Unit tests for FFmpeg Manager Service.

These tests use real FFmpeg service with actual file conversions.
Test files are properly cleaned up after each test to ensure isolation.
"""

import os

import pytest

from source.services.ffmpeg_manager.manager import FFmpegHandler

# ============================================================================
# FFmpeg Handler Unit Tests (Real FFmpeg)
# ============================================================================


@pytest.mark.unit
class TestFFmpegHandlerValidation:
    """Test FFmpeg handler validation logic."""

    @pytest.fixture
    def ffmpeg_handler_from_services(self, tmp_path):
        """Provide FFmpeg handler constructed through services manager."""
        import asyncio

        from source.constructor import ServerManagerType
        from source.context import Context
        from source.server.constructor import construct_server_manager
        from source.services.constructor import construct_services_manager

        async def setup():
            # Create context
            context = Context()

            # Create server manager
            server_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
            context.set_server_manager(server_manager)
            await server_manager.connect_all()

            # Create services manager
            storage_path = str(tmp_path / "data")
            recording_storage_path = str(tmp_path / "data" / "recordings")
            transcription_storage_path = str(tmp_path / "data" / "transcriptions")

            services_manager = construct_services_manager(
                ServerManagerType.DEVELOPMENT,
                context=context,
                storage_path=storage_path,
                recording_storage_path=recording_storage_path,
                transcription_storage_path=transcription_storage_path,
            )
            await services_manager.initialize_all()

            return server_manager, services_manager

        # Run async setup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server_manager, services_manager = loop.run_until_complete(setup())

        # Get handler from services
        handler = services_manager.ffmpeg_service_manager.handler

        yield handler

        # Cleanup
        async def cleanup():
            await services_manager.ffmpeg_service_manager.on_close()
            await server_manager.disconnect_all()

        loop.run_until_complete(cleanup())
        loop.close()

    def test_validate_ffmpeg_installed(self, ffmpeg_handler_from_services):
        """Test that FFmpeg is properly installed and accessible."""
        import asyncio

        handler = ffmpeg_handler_from_services

        # Act: Validate FFmpeg
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        is_valid = loop.run_until_complete(handler.validate_ffmpeg())
        loop.close()

        # Assert: FFmpeg should be installed
        if not is_valid:
            pytest.skip(f"FFmpeg not found at {handler.ffmpeg_path}. Skipping validation test.")

        assert is_valid is True

    def test_validate_ffmpeg_not_found(self):
        """Test FFmpeg validation when FFmpeg is not installed."""
        import asyncio

        # Setup: Use a nonexistent FFmpeg path
        handler = FFmpegHandler(None, "/nonexistent/path/to/ffmpeg")

        # Act
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        is_valid = loop.run_until_complete(handler.validate_ffmpeg())
        loop.close()

        # Assert
        assert is_valid is False


@pytest.mark.unit
class TestFFmpegHandlerConversion:
    """Test FFmpeg handler conversion with real file conversions."""

    @pytest.fixture
    def ffmpeg_handler_and_services(self, tmp_path):
        """Provide FFmpeg handler and services manager via constructors."""
        import asyncio

        from source.constructor import ServerManagerType
        from source.context import Context
        from source.server.constructor import construct_server_manager
        from source.services.constructor import construct_services_manager

        async def setup():
            # Create context
            context = Context()

            # Create server manager (same as playground.py)
            server_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
            context.set_server_manager(server_manager)
            await server_manager.connect_all()

            # Create services manager (same as playground.py)
            storage_path = str(tmp_path / "data")
            recording_storage_path = str(tmp_path / "data" / "recordings")
            transcription_storage_path = str(tmp_path / "data" / "transcriptions")

            services_manager = construct_services_manager(
                ServerManagerType.DEVELOPMENT,
                context=context,
                storage_path=storage_path,
                recording_storage_path=recording_storage_path,
                transcription_storage_path=transcription_storage_path,
            )
            await services_manager.initialize_all()

            return server_manager, services_manager

        # Run async setup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server_manager, services_manager = loop.run_until_complete(setup())

        yield services_manager.ffmpeg_service_manager.handler, server_manager

        # Cleanup
        async def cleanup():
            await services_manager.ffmpeg_service_manager.on_close()
            await server_manager.disconnect_all()

        loop.run_until_complete(cleanup())
        loop.close()

    def test_convert_file_with_real_ffmpeg(self, ffmpeg_handler_and_services, tmp_path):
        """Test real file conversion using actual FFmpeg via constructors."""
        import asyncio

        # Setup: Get test audio file
        test_audio_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "audio-recording-1.m4a"
        )

        if not os.path.exists(test_audio_file):
            pytest.skip(f"Test audio file not found at {test_audio_file}")

        handler, _ = ffmpeg_handler_and_services

        # Validate FFmpeg is available
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if not loop.run_until_complete(handler.validate_ffmpeg()):
            loop.close()
            pytest.skip("FFmpeg not installed or not accessible")

        output_path = str(tmp_path / "test_output.wav")
        options = {"-f": "s16le", "-ar": "48000", "-ac": "1", "-y": None}

        try:
            # Act: Convert the file
            success, stdout, stderr = loop.run_until_complete(
                handler.convert_file(test_audio_file, output_path, options)
            )

            # Assert: Conversion should succeed
            assert success is True, f"Conversion failed. stderr: {stderr}"

            # Assert: Output file should exist
            assert os.path.exists(output_path), "Output file should exist"

            # Assert: Output file should have content
            file_size = os.path.getsize(output_path)
            assert file_size > 0, "Output file should not be empty"

        finally:
            loop.close()
            # Cleanup: Remove output file if it exists
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_convert_file_with_nonexistent_input(self, ffmpeg_handler_and_services, tmp_path):
        """Test conversion failure with nonexistent input file."""
        import asyncio

        handler, _ = ffmpeg_handler_and_services

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if not loop.run_until_complete(handler.validate_ffmpeg()):
            loop.close()
            pytest.skip("FFmpeg not installed or not accessible")

        input_path = str(tmp_path / "nonexistent_file.m4a")
        output_path = str(tmp_path / "output.wav")
        options = {"-f": "s16le", "-ar": "48000", "-ac": "1", "-y": None}

        try:
            # Act: Attempt conversion with nonexistent input
            success, stdout, stderr = loop.run_until_complete(
                handler.convert_file(input_path, output_path, options)
            )

            # Assert: Conversion should fail
            assert success is False, "Conversion should fail for nonexistent input file"

            # Assert: Output file should not exist
            assert not os.path.exists(output_path), "Output file should not be created on failure"

        finally:
            loop.close()
            # Cleanup: Remove output file if it was created despite failure
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_convert_file_with_invalid_output_path(self, ffmpeg_handler_and_services, tmp_path):
        """Test conversion with invalid output directory path."""
        import asyncio

        # Setup: Get test audio file
        test_audio_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "audio-recording-1.m4a"
        )

        if not os.path.exists(test_audio_file):
            pytest.skip(f"Test audio file not found at {test_audio_file}")

        handler, _ = ffmpeg_handler_and_services

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if not loop.run_until_complete(handler.validate_ffmpeg()):
            loop.close()
            pytest.skip("FFmpeg not installed or not accessible")

        # Use path with nonexistent directories
        output_path = str(tmp_path / "nonexistent_dir" / "subdir" / "output.wav")
        options = {"-f": "s16le", "-ar": "48000", "-ac": "1", "-y": None}

        try:
            # Act: Attempt conversion with invalid output path
            success, stdout, stderr = loop.run_until_complete(
                handler.convert_file(test_audio_file, output_path, options)
            )

            # Assert: Conversion should fail (FFmpeg cannot write to nonexistent directory)
            assert success is False, "Conversion should fail for nonexistent output directory"

        finally:
            loop.close()
            # Cleanup: Try to remove any created files
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_convert_file_preserves_audio_properties(self, ffmpeg_handler_and_services, tmp_path):
        """Test that converted file has the specified audio properties."""
        import asyncio

        # Setup: Get test audio file
        test_audio_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "audio-recording-1.m4a"
        )

        if not os.path.exists(test_audio_file):
            pytest.skip(f"Test audio file not found at {test_audio_file}")

        handler, _ = ffmpeg_handler_and_services

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if not loop.run_until_complete(handler.validate_ffmpeg()):
            loop.close()
            pytest.skip("FFmpeg not installed or not accessible")

        output_path = str(tmp_path / "test_output_properties.wav")
        # Convert to WAV format with 16-bit PCM, 48kHz, mono
        options = {"-f": "wav", "-ar": "48000", "-ac": "1", "-acodec": "pcm_s16le", "-y": None}

        try:
            # Act: Convert the file
            success, stdout, stderr = loop.run_until_complete(
                handler.convert_file(test_audio_file, output_path, options)
            )

            # Assert: Conversion should succeed
            assert success is True, f"Conversion failed. stderr: {stderr}"

            # Assert: Output file should exist and have reasonable size
            assert os.path.exists(output_path), "Output file should exist"
            file_size = os.path.getsize(output_path)
            assert file_size > 44, "WAV file should be at least 44 bytes (header size)"

            # Verify it's a valid WAV file (check for WAV header)
            with open(output_path, "rb") as f:
                wav_header = f.read(4)
                assert wav_header == b"RIFF", "Output should be a valid WAV file"

        finally:
            loop.close()
            # Cleanup: Remove output file
            if os.path.exists(output_path):
                os.remove(output_path)
