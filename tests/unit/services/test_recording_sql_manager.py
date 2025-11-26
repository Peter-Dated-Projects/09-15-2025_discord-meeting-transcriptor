"""
Unit tests for SQL Recording Manager Service.

Tests cover CRUD operations for both temporary and persistent recordings,
as well as bulk operations. These tests require the database to be set up.
"""

import os

import pytest

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.server.sql_models import MeetingStatus
from source.services.constructor import construct_services_manager
from source.services.recording_sql_manager.manager import SQLRecordingManagerService
from source.utils import generate_16_char_uuid, get_current_timestamp_est


@pytest.mark.unit
class TestSQLRecordingManagerService:
    """Test SQL Recording Manager Service CRUD operations."""

    @pytest.fixture
    async def services_and_db(self, tmp_path, shared_test_log_file):
        """Setup services and database for testing."""
        from source.context import Context

        # Create context
        context = Context()

        # Initialize server manager
        servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
        context.set_server_manager(servers_manager)
        await servers_manager.connect_all()

        # Initialize services manager
        storage_path = os.path.join(str(tmp_path), "data")
        recording_storage_path = os.path.join(storage_path, "recordings")
        transcription_storage_path = os.path.join(storage_path, "transcriptions")
        conversation_storage_path = os.path.join(storage_path, "conversations")

        services_manager = construct_services_manager(
            ServerManagerType.DEVELOPMENT,
            context=context,
            storage_path=storage_path,
            recording_storage_path=recording_storage_path,
            transcription_storage_path=transcription_storage_path,
            conversation_storage_path=conversation_storage_path,
            log_file=shared_test_log_file,
            use_timestamp_logs=False,
        )
        await services_manager.initialize_all()

        yield services_manager, servers_manager

        # Cleanup
        await servers_manager.disconnect_all()

    @pytest.fixture
    def test_data(self, tmp_path):
        """Provide test data."""
        test_user_id = "1234567890123456"
        test_guild_id = "1234567890"
        test_channel_id = "9876543210"
        test_meeting_id = generate_16_char_uuid()

        # Create a dummy test audio file with unique content based on meeting_id
        # This ensures each test has a unique SHA256
        test_audio_file = tmp_path / "test_audio.mp3"
        test_audio_file.write_bytes(f"dummy audio data {test_meeting_id}".encode())

        return {
            "user_id": test_user_id,
            "guild_id": test_guild_id,
            "channel_id": test_channel_id,
            "meeting_id": test_meeting_id,
            "audio_file": str(test_audio_file),
        }

    @pytest.fixture
    async def setup_meeting(self, services_and_db, test_data):
        """Setup a test meeting in the database."""
        services_manager, servers_manager = services_and_db
        db_service = servers_manager.sql_client

        from sqlalchemy import insert

        from source.server.sql_models import MeetingModel

        now = get_current_timestamp_est()

        meeting_stmt = insert(MeetingModel).values(
            id=test_data["meeting_id"],
            guild_id=test_data["guild_id"],
            channel_id=test_data["channel_id"],
            started_at=now,
            ended_at=now,
            status=MeetingStatus.RECORDING.value,
            requested_by=test_data["user_id"],
            participants={test_data["user_id"]: test_data["user_id"]},
            recording_files={},
            transcript_ids={},
        )
        await db_service.execute(meeting_stmt)

        yield services_manager, servers_manager, test_data

        # Cleanup - delete temp_recordings first due to foreign key constraint
        from sqlalchemy import delete

        from source.server.sql_models import MeetingModel, RecordingModel, TempRecordingModel

        # Delete temp recordings first
        delete_temp_recordings_stmt = delete(TempRecordingModel).where(
            TempRecordingModel.meeting_id == test_data["meeting_id"]
        )
        await db_service.execute(delete_temp_recordings_stmt)

        # Delete persistent recordings
        delete_recordings_stmt = delete(RecordingModel).where(
            RecordingModel.meeting_id == test_data["meeting_id"]
        )
        await db_service.execute(delete_recordings_stmt)

        # Finally delete meeting
        delete_meeting_stmt = delete(MeetingModel).where(MeetingModel.id == test_data["meeting_id"])
        await db_service.execute(delete_meeting_stmt)

    # ========================================================================
    # TEST 1: Temp Recording CRUD Operations
    # ========================================================================

    @pytest.mark.asyncio
    async def test_insert_temp_recording(self, setup_meeting):
        """Test inserting a temporary recording."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        temp_filename = os.path.join("assets", "data", "temp", "test_recording_temp.mp3")
        temp_recording_id = await recording_sql_service.insert_temp_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            start_timestamp_ms=1000,
            filename=temp_filename,
        )

        assert temp_recording_id is not None
        assert isinstance(temp_recording_id, str)

    @pytest.mark.asyncio
    async def test_get_temp_recordings_for_meeting(self, setup_meeting):
        """Test querying temporary recordings for a meeting."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a temp recording
        temp_filename = os.path.join("assets", "data", "temp", "test_recording_temp.mp3")
        temp_recording_id = await recording_sql_service.insert_temp_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            start_timestamp_ms=1000,
            filename=temp_filename,
        )

        # Query temp recordings for meeting
        temp_recordings = await recording_sql_service.get_temp_recordings_for_meeting(
            test_data["meeting_id"]
        )

        assert len(temp_recordings) > 0
        assert any(recording.get("id") == temp_recording_id for recording in temp_recordings)

    @pytest.mark.asyncio
    async def test_get_temp_recordings_for_user(self, setup_meeting):
        """Test querying temporary recordings for a user."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a temp recording
        temp_filename = os.path.join("assets", "data", "temp", "test_recording_temp.mp3")
        await recording_sql_service.insert_temp_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            start_timestamp_ms=1000,
            filename=temp_filename,
        )

        # Query temp recordings for user
        user_temp_recordings = await recording_sql_service.get_temp_recordings_for_user(
            test_data["user_id"]
        )

        assert len(user_temp_recordings) > 0

    @pytest.mark.asyncio
    async def test_delete_temp_recording(self, setup_meeting):
        """Test deleting a temporary recording."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a temp recording
        temp_filename = os.path.join("assets", "data", "temp", "test_recording_temp.mp3")
        temp_recording_id = await recording_sql_service.insert_temp_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            start_timestamp_ms=1000,
            filename=temp_filename,
        )

        # Delete the temp recording
        await recording_sql_service.delete_temp_recording(temp_recording_id)

        # Verify deletion
        verify_recordings = await recording_sql_service.get_temp_recordings_for_meeting(
            test_data["meeting_id"]
        )
        assert not any(recording.get("id") == temp_recording_id for recording in verify_recordings)

    # ========================================================================
    # TEST 2: Persistent Recording CRUD Operations
    # ========================================================================

    @pytest.mark.asyncio
    async def test_insert_persistent_recording(self, setup_meeting):
        """Test inserting a persistent recording."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        persistent_recording_id = await recording_sql_service.insert_persistent_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            filename=test_data["audio_file"],
        )

        assert persistent_recording_id is not None
        assert isinstance(persistent_recording_id, str)

    @pytest.mark.asyncio
    async def test_get_persistent_recordings_for_meeting(self, setup_meeting):
        """Test querying persistent recordings for a meeting."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a persistent recording
        persistent_recording_id = await recording_sql_service.insert_persistent_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            filename=test_data["audio_file"],
        )

        # Query persistent recordings for meeting
        persistent_recordings = await recording_sql_service.get_persistent_recordings_for_meeting(
            test_data["meeting_id"]
        )

        assert len(persistent_recordings) > 0
        assert any(
            recording.get("id") == persistent_recording_id for recording in persistent_recordings
        )

    @pytest.mark.asyncio
    async def test_get_persistent_recordings_for_user(self, setup_meeting):
        """Test querying persistent recordings for a user."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a persistent recording
        await recording_sql_service.insert_persistent_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            filename=test_data["audio_file"],
        )

        # Query persistent recordings for user
        user_persistent_recordings = await recording_sql_service.get_persistent_recordings_for_user(
            test_data["user_id"]
        )

        assert len(user_persistent_recordings) > 0

    @pytest.mark.asyncio
    async def test_delete_persistent_recording(self, setup_meeting):
        """Test deleting a persistent recording."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Insert a persistent recording
        persistent_recording_id = await recording_sql_service.insert_persistent_recording(
            user_id=test_data["user_id"],
            meeting_id=test_data["meeting_id"],
            filename=test_data["audio_file"],
        )

        # Delete the persistent recording
        await recording_sql_service.delete_persistent_recording(persistent_recording_id)

        # Verify deletion
        verify_persistent = await recording_sql_service.get_persistent_recordings_for_meeting(
            test_data["meeting_id"]
        )
        assert not any(
            recording.get("id") == persistent_recording_id for recording in verify_persistent
        )

    # ========================================================================
    # TEST 3: Bulk Operations
    # ========================================================================

    @pytest.mark.asyncio
    async def test_create_multiple_temp_recordings(self, setup_meeting):
        """Test creating multiple temporary recordings."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        temp_ids = []
        for i in range(3):
            temp_id = await recording_sql_service.insert_temp_recording(
                user_id=test_data["user_id"],
                meeting_id=test_data["meeting_id"],
                start_timestamp_ms=1000 + i * 1000,
                filename=f"assets/data/temp/test_recording_temp_{i}.mp3",
            )
            temp_ids.append(temp_id)

        assert len(temp_ids) == 3

    @pytest.mark.asyncio
    async def test_query_all_temp_recordings(self, setup_meeting):
        """Test querying all temporary recordings for a meeting."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Create multiple temp recordings
        for i in range(3):
            await recording_sql_service.insert_temp_recording(
                user_id=test_data["user_id"],
                meeting_id=test_data["meeting_id"],
                start_timestamp_ms=1000 + i * 1000,
                filename=f"assets/data/temp/test_recording_temp_{i}.mp3",
            )

        # Query all temp recordings
        all_temp = await recording_sql_service.get_temp_recordings_for_meeting(
            test_data["meeting_id"]
        )

        assert len(all_temp) >= 3

    @pytest.mark.asyncio
    async def test_delete_multiple_temp_recordings(self, setup_meeting):
        """Test deleting multiple temporary recordings."""
        services_manager, servers_manager, test_data = setup_meeting
        recording_sql_service: SQLRecordingManagerService = (
            services_manager.sql_recording_service_manager
        )

        # Create multiple temp recordings
        temp_ids = []
        for i in range(3):
            temp_id = await recording_sql_service.insert_temp_recording(
                user_id=test_data["user_id"],
                meeting_id=test_data["meeting_id"],
                start_timestamp_ms=1000 + i * 1000,
                filename=f"assets/data/temp/test_recording_temp_{i}.mp3",
            )
            temp_ids.append(temp_id)

        # Delete multiple temp recordings
        await recording_sql_service.delete_temp_recordings(temp_ids)

        # Verify bulk deletion
        verify_bulk = await recording_sql_service.get_temp_recordings_for_meeting(
            test_data["meeting_id"]
        )
        deleted_count = sum(1 for recording in verify_bulk if recording.get("id") in temp_ids)
        assert deleted_count == 0
