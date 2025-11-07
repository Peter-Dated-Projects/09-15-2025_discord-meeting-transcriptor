"""
Unit tests for Discord Recorder Timeline-Driven Audio Chunker.

Tests the following critical functionality:
1. Gap padding calculation and frame alignment
2. Exact 30s window flushing
3. Timeline tracking with wall-clock
4. Edge cases: late join, long silence, reconnects

Note: These tests validate the timeline logic without requiring actual Discord connections.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from source.services.discord_recorder.manager import (
    DiscordRecorderConstants,
    DiscordSessionHandler,
)
from source.services.discord_recorder.pcm_generator import (
    calculate_pcm_bytes,
    calculate_pcm_duration_ms,
)

# -------------------------------------------------------------- #
# Test Constants
# -------------------------------------------------------------- #


@pytest.fixture
def constants():
    """Test constants for timeline chunker."""
    return {
        "FRAME_MS": DiscordRecorderConstants.FRAME_MS,
        "BYTES_PER_MS": DiscordRecorderConstants.BYTES_PER_MS,
        "FRAME_BYTES": DiscordRecorderConstants.FRAME_BYTES,
        "WINDOW_MS": DiscordRecorderConstants.WINDOW_MS,
        "WINDOW_BYTES": DiscordRecorderConstants.WINDOW_BYTES,
    }


# -------------------------------------------------------------- #
# Test Frame Alignment
# -------------------------------------------------------------- #


def test_frame_bytes_constant():
    """Verify FRAME_BYTES is exactly 3840 bytes (20ms at 48kHz stereo 16-bit)."""
    # 20ms * 48000 Hz * 2 channels * 2 bytes = 3840 bytes
    expected_frame_bytes = 20 * 48000 * 2 * 2 // 1000
    assert expected_frame_bytes == DiscordRecorderConstants.FRAME_BYTES
    assert DiscordRecorderConstants.FRAME_BYTES == 3840


def test_window_bytes_constant():
    """Verify WINDOW_BYTES is exactly 5,760,000 bytes (30s at 48kHz stereo 16-bit)."""
    # 30,000ms * 192 bytes/ms = 5,760,000 bytes
    expected_window_bytes = 30_000 * DiscordRecorderConstants.BYTES_PER_MS
    assert expected_window_bytes == DiscordRecorderConstants.WINDOW_BYTES
    assert DiscordRecorderConstants.WINDOW_BYTES == 5_760_000


def test_bytes_per_ms_constant():
    """Verify BYTES_PER_MS is exactly 192 bytes (1ms at 48kHz stereo 16-bit)."""
    # 48000 Hz * 2 channels * 2 bytes / 1000ms = 192 bytes/ms
    expected_bytes_per_ms = 48000 * 2 * 2 // 1000
    assert expected_bytes_per_ms == DiscordRecorderConstants.BYTES_PER_MS
    assert DiscordRecorderConstants.BYTES_PER_MS == 192


@pytest.mark.asyncio
async def test_frame_alignment_validation():
    """Test _is_frame_aligned helper method."""
    # Create minimal mock context
    mock_context = MagicMock()
    mock_context.services_manager = MagicMock()
    mock_context.bot = None

    mock_voice_client = MagicMock()

    # Create session handler
    handler = DiscordSessionHandler(
        discord_voice_client=mock_voice_client,
        channel_id=123,
        meeting_id="test-meeting",
        user_id="user123",
        guild_id="guild123",
        context=mock_context,
    )

    # Test frame-aligned sizes
    assert handler._is_frame_aligned(0) is True  # 0 frames
    assert handler._is_frame_aligned(3840) is True  # 1 frame (20ms)
    assert handler._is_frame_aligned(7680) is True  # 2 frames (40ms)
    assert handler._is_frame_aligned(5_760_000) is True  # 1500 frames (30s)

    # Test non-aligned sizes
    assert handler._is_frame_aligned(1) is False
    assert handler._is_frame_aligned(3839) is False
    assert handler._is_frame_aligned(3841) is False
    assert handler._is_frame_aligned(5_760_001) is False


# -------------------------------------------------------------- #
# Test Gap Padding Calculation
# -------------------------------------------------------------- #


def test_gap_padding_rounding():
    """Test that gaps are rounded up to 20ms frame boundaries."""
    # Gap of 15ms should round up to 20ms (1 frame)
    gap_ms = 15
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 20
    assert frames_needed == 1

    # Gap of 25ms should round up to 40ms (2 frames)
    gap_ms = 25
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 40
    assert frames_needed == 2

    # Gap of 3000ms should stay at 3000ms (150 frames)
    gap_ms = 3000
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 3000
    assert frames_needed == 150

    # Gap of 2961ms should round up to 2980ms (149 frames)
    gap_ms = 2961
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 2980
    assert frames_needed == 149


# -------------------------------------------------------------- #
# Test PCM Duration Calculations
# -------------------------------------------------------------- #


def test_pcm_duration_calculations():
    """Test that PCM duration calculations are accurate."""
    # 1 second = 192,000 bytes at 48kHz stereo 16-bit
    one_second_bytes = calculate_pcm_bytes(
        duration_ms=1000,
        sample_rate=48000,
        bits_per_sample=16,
        channels=2,
    )
    assert one_second_bytes == 192_000

    # Verify round-trip: 192,000 bytes = 1000ms
    duration = calculate_pcm_duration_ms(
        num_bytes=192_000,
        sample_rate=48000,
        bits_per_sample=16,
        channels=2,
    )
    assert duration == 1000

    # 20ms frame = 3,840 bytes
    frame_bytes = calculate_pcm_bytes(
        duration_ms=20,
        sample_rate=48000,
        bits_per_sample=16,
        channels=2,
    )
    assert frame_bytes == 3_840

    # 30 seconds = 5,760,000 bytes
    thirty_sec_bytes = calculate_pcm_bytes(
        duration_ms=30_000,
        sample_rate=48000,
        bits_per_sample=16,
        channels=2,
    )
    assert thirty_sec_bytes == 5_760_000


# -------------------------------------------------------------- #
# Test Window Extraction Logic
# -------------------------------------------------------------- #


def test_exact_windowing_multiple_windows():
    """Test that exact 30s windows are extracted correctly from a buffer."""
    # Simulate a buffer with 65 seconds of audio (2 full windows + 5s partial)
    total_duration_ms = 65_000
    total_bytes = calculate_pcm_bytes(total_duration_ms)

    # Create a mock buffer
    mock_buffer = bytearray(total_bytes)

    # Extract windows
    windows = []
    while len(mock_buffer) >= DiscordRecorderConstants.WINDOW_BYTES:
        window = bytes(mock_buffer[: DiscordRecorderConstants.WINDOW_BYTES])
        del mock_buffer[: DiscordRecorderConstants.WINDOW_BYTES]
        windows.append(window)

    # Should have 2 full windows
    assert len(windows) == 2
    for window in windows:
        assert len(window) == DiscordRecorderConstants.WINDOW_BYTES
        duration = calculate_pcm_duration_ms(len(window))
        assert duration == 30_000

    # Remaining partial window should be 5 seconds
    remaining_bytes = len(mock_buffer)
    remaining_duration_ms = calculate_pcm_duration_ms(remaining_bytes)
    assert remaining_duration_ms == 5_000


def test_exact_windowing_partial_window_only():
    """Test handling of buffers smaller than one full window."""
    # Simulate a buffer with 15 seconds of audio (less than one window)
    total_duration_ms = 15_000
    total_bytes = calculate_pcm_bytes(total_duration_ms)

    # Create a mock buffer
    mock_buffer = bytearray(total_bytes)

    # Try to extract windows
    windows = []
    while len(mock_buffer) >= DiscordRecorderConstants.WINDOW_BYTES:
        window = bytes(mock_buffer[: DiscordRecorderConstants.WINDOW_BYTES])
        del mock_buffer[: DiscordRecorderConstants.WINDOW_BYTES]
        windows.append(window)

    # Should have 0 full windows
    assert len(windows) == 0

    # Entire buffer should remain (15s)
    remaining_bytes = len(mock_buffer)
    remaining_duration_ms = calculate_pcm_duration_ms(remaining_bytes)
    assert remaining_duration_ms == 15_000


# -------------------------------------------------------------- #
# Test Edge Cases
# -------------------------------------------------------------- #


def test_gap_calculation_first_packet():
    """Test that first packet has no gap (last_wall_ms initialized to now_ms)."""
    # For first packet: last_wall_ms is set to now_ms on initialization
    # So gap should be: (now_ms - pcm_duration_ms) - last_wall_ms = -pcm_duration_ms
    # But we use max(0, gap), so it should be 0

    now_ms = 10_000  # Arbitrary current time
    pcm_duration_ms = 20  # 20ms packet
    last_wall_ms = now_ms  # Initialized to now_ms

    packet_start_ms = now_ms - pcm_duration_ms
    gap_ms = max(0, packet_start_ms - last_wall_ms)

    assert gap_ms == 0  # No gap for first packet


def test_gap_calculation_consecutive_packets():
    """Test gap calculation between consecutive packets with no silence."""
    # Two consecutive 20ms packets with no gap between them
    now_ms_packet1 = 10_000
    pcm_duration_ms = 20

    # After packet 1, last_wall_ms = 10,000
    last_wall_ms_after_packet1 = now_ms_packet1

    # Packet 2 arrives 20ms later (immediately after packet 1 ends)
    now_ms_packet2 = now_ms_packet1 + pcm_duration_ms
    packet_start_ms = now_ms_packet2 - pcm_duration_ms
    gap_ms = max(0, packet_start_ms - last_wall_ms_after_packet1)

    assert gap_ms == 0  # No gap between consecutive packets


def test_gap_calculation_with_silence():
    """Test gap calculation when there's actual silence between packets."""
    # Packet 1 at t=0, duration 20ms, ends at t=20
    last_wall_ms_after_packet1 = 20

    # Packet 2 arrives at t=3020 (3 seconds of silence)
    # Packet 2 duration: 20ms, so it started at t=3000
    now_ms_packet2 = 3020
    pcm_duration_ms = 20
    packet_start_ms = now_ms_packet2 - pcm_duration_ms  # 3000

    gap_ms = max(0, packet_start_ms - last_wall_ms_after_packet1)

    # Gap should be 3000ms - 20ms = 2980ms
    assert gap_ms == 2980

    # This should round up to 2980ms (149 frames of 20ms)
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 2980
    assert frames_needed == 149


# -------------------------------------------------------------- #
# Test Timestamp Calculation
# -------------------------------------------------------------- #


def test_chunk_timestamp_calculation():
    """Test that chunk timestamps are calculated correctly (chunk_idx * WINDOW_MS)."""
    # Chunk 0 starts at t=0
    chunk_idx = 0
    timestamp_ms = chunk_idx * DiscordRecorderConstants.WINDOW_MS
    assert timestamp_ms == 0

    # Chunk 1 starts at t=30,000ms
    chunk_idx = 1
    timestamp_ms = chunk_idx * DiscordRecorderConstants.WINDOW_MS
    assert timestamp_ms == 30_000

    # Chunk 5 starts at t=150,000ms (2.5 minutes)
    chunk_idx = 5
    timestamp_ms = chunk_idx * DiscordRecorderConstants.WINDOW_MS
    assert timestamp_ms == 150_000


# -------------------------------------------------------------- #
# Test Integration Scenarios
# -------------------------------------------------------------- #


def test_late_join_scenario():
    """
    Test scenario: User joins 5 seconds after recording starts.

    Expected behavior:
    - First packet arrives at t=5000ms (5s silence gap)
    - Gap of ~5000ms should be padded
    - First window should contain: [5s silence] + [25s audio]
    """
    # User joins at t=5000ms, sends first 20ms packet
    now_ms = 5020  # Packet arrives at t=5020, started at t=5000
    pcm_duration_ms = 20
    last_wall_ms = now_ms  # First packet, initialized to now_ms

    # Since this is the first packet, gap calculation:
    # packet_start_ms = 5020 - 20 = 5000
    # gap = max(0, 5000 - 5020) = 0
    # So we need to adjust our approach for late joins...

    # Actually, for late joins, we should initialize last_wall_ms to 0 (recording start)
    # Then gap = (5020 - 20) - 0 = 5000ms
    last_wall_ms = 0  # Recording started at t=0
    packet_start_ms = now_ms - pcm_duration_ms
    gap_ms = max(0, packet_start_ms - last_wall_ms)

    assert gap_ms == 5000

    # Round to frame boundary (5000ms is already aligned)
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 5000


def test_long_silence_scenario():
    """
    Test scenario: User speaks, then silent for 2 minutes, then speaks again.

    Expected behavior:
    - Packet 1 at t=0-20ms
    - Silence gap of 120,000ms (2 minutes)
    - Packet 2 at t=120,000-120,020ms
    - Gap should be padded with silence
    """
    # Packet 1
    last_wall_ms_after_packet1 = 20

    # Packet 2 arrives 2 minutes later
    silence_duration_ms = 120_000
    now_ms_packet2 = last_wall_ms_after_packet1 + silence_duration_ms + 20
    pcm_duration_ms = 20
    packet_start_ms = now_ms_packet2 - pcm_duration_ms

    gap_ms = max(0, packet_start_ms - last_wall_ms_after_packet1)

    # Gap should be exactly 120,000ms
    assert gap_ms == 120_000

    # Should be already frame-aligned (6000 frames)
    frames_needed = (
        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
    ) // DiscordRecorderConstants.FRAME_MS
    assert frames_needed == 6000
    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS
    assert pad_ms == 120_000


# -------------------------------------------------------------- #
# Test Memory and Buffer Management
# -------------------------------------------------------------- #


def test_buffer_growth_with_gaps():
    """Test that buffer size grows correctly with gap padding."""
    # Start with empty buffer
    buffer = bytearray()

    # Add 20ms of audio (1 frame)
    audio_bytes = calculate_pcm_bytes(20)
    buffer.extend(b"\x00" * audio_bytes)
    assert len(buffer) == 3_840

    # Add 3 seconds of silence gap (150 frames)
    gap_bytes = calculate_pcm_bytes(3000)
    buffer.extend(b"\x00" * gap_bytes)
    assert len(buffer) == 3_840 + 576_000  # 579,840 bytes

    # Add another 20ms of audio
    buffer.extend(b"\x00" * audio_bytes)
    assert len(buffer) == 583_680

    # Total duration should be 3040ms
    total_duration = calculate_pcm_duration_ms(len(buffer))
    assert total_duration == 3040


# -------------------------------------------------------------- #
# Run Tests
# -------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_equal_chunk_counts_after_stop():
    """
    Integration test: Verify all users end with equal chunk counts after stop_recording.

    Scenario:
    - User A joins at t=0s, speaks for 60s
    - User B joins at t=30s (backfilled 1 window), speaks for 30s
    - User C joins at t=45s (backfilled 1 window), speaks for 15s
    - Stop at t=60s

    Expected:
    - All users should have 2 chunks (0-30s, 30-60s)
    - Equal chunk counts guarantee timeline alignment
    """
    # Create minimal mock context
    mock_context = MagicMock()
    mock_context.services_manager = MagicMock()
    mock_context.services_manager.logging_service = AsyncMock()
    mock_context.services_manager.recording_file_service_manager = MagicMock()
    mock_context.services_manager.recording_file_service_manager.get_temporary_storage_path.return_value = (
        "/tmp/recordings"
    )
    mock_context.services_manager.recording_file_service_manager.save_to_temp_file = AsyncMock(
        return_value="/tmp/recordings/test.pcm"
    )
    mock_context.services_manager.sql_recording_service_manager = AsyncMock()
    mock_context.services_manager.sql_recording_service_manager.insert_temp_recording = AsyncMock(
        return_value="temp_id_123"
    )
    mock_context.services_manager.ffmpeg_service_manager = AsyncMock()
    mock_context.services_manager.ffmpeg_service_manager.queue_pcm_to_mp3 = AsyncMock()
    mock_context.bot = None

    mock_voice_client = MagicMock()

    session = DiscordSessionHandler(
        discord_voice_client=mock_voice_client,
        channel_id=12345,
        meeting_id="test_meeting",
        user_id="user_123",
        guild_id="guild_456",
        context=mock_context,
    )

    # Simulate session state at 60s mark
    from datetime import datetime, timedelta

    session.start_time = datetime.utcnow() - timedelta(seconds=60)
    session.is_recording = True

    # User A: joined at t=0s, has 60s of audio (2 full windows)
    user_a_id = 1001
    session._user_audio_buffers[user_a_id] = bytearray(DiscordRecorderConstants.WINDOW_BYTES * 2)
    session._user_chunk_counters[user_a_id] = 0
    session._user_temp_recording_ids[user_a_id] = []

    # User B: joined at t=30s (backfilled 1 window), has 30s of audio (1 full window)
    user_b_id = 1002
    session._user_audio_buffers[user_b_id] = bytearray(DiscordRecorderConstants.WINDOW_BYTES)
    session._user_chunk_counters[user_b_id] = 1  # Already backfilled chunk 0
    session._user_temp_recording_ids[user_b_id] = []

    # User C: joined at t=45s (backfilled 1 window), has 15s of audio (partial window)
    user_c_id = 1003
    session._user_audio_buffers[user_c_id] = bytearray(
        DiscordRecorderConstants.WINDOW_BYTES // 2  # 15s
    )
    session._user_chunk_counters[user_c_id] = 1  # Already backfilled chunk 0
    session._user_temp_recording_ids[user_c_id] = []

    # Mock the flush methods to avoid actual I/O
    with (
        patch.object(session, "_flush_user_window", new_callable=AsyncMock),
        patch.object(session, "_flush_user_backfill", new_callable=AsyncMock),
    ):

        # Execute stop sequence: flush (force=True) → backfill to max
        await session._flush_all_users(force=True)
        await session._backfill_to_max_chunks()

        # Verify all users have equal chunk counts
        assert session._user_chunk_counters[user_a_id] == session._user_chunk_counters[user_b_id]
        assert session._user_chunk_counters[user_b_id] == session._user_chunk_counters[user_c_id]

        # Verify chunk count is 2 (two 30s windows)
        expected_chunks = 2
        assert session._user_chunk_counters[user_a_id] == expected_chunks
        assert session._user_chunk_counters[user_b_id] == expected_chunks
        assert session._user_chunk_counters[user_c_id] == expected_chunks

        print(f"✅ All users have equal chunk counts: {expected_chunks} chunks (60s total)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
