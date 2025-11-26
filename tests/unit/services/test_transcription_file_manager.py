import os

import pytest

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager


@pytest.mark.unit
class TestTranscriptionFileManagerService:
    """Test Transcription File Manager Service operations."""

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
    def test_data(self, request):
        """Provide test data with unique transcript content per test."""
        import time

        # Use test name and timestamp to ensure unique transcript content
        test_name = request.node.name
        unique_text = f"Hello, this is a test transcription for {test_name} at {time.time()}."

        return {
            "meeting_id": "test_meeting_123",
            "user_id": "123456789012345678",
            "guild_id": "111111111111111111",
            "channel_id": "222222222222222222",
            "transcript_data": {
                "text": unique_text,
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.5,
                        "text": unique_text,
                    }
                ],
                "language": "en",
            },
        }

    @pytest.fixture
    async def setup_meeting(self, services_and_db, test_data):
        """Create a meeting record for tests that need it."""
        services_manager, _ = services_and_db
        sql_recording_service = services_manager.sql_recording_service_manager

        # Insert meeting record, ignore if it already exists (from previous test)
        try:
            await sql_recording_service.insert_meeting(
                meeting_id=test_data["meeting_id"],
                guild_id=test_data["guild_id"],
                channel_id=test_data["channel_id"],
                requested_by=test_data["user_id"],
            )
        except Exception as e:
            # If the meeting already exists (from a previous test run), that's fine
            if "Duplicate entry" not in str(e):
                raise

        return test_data["meeting_id"]

    async def test_save_transcription(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test saving a transcription."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Save transcription
        transcript_id, filename = await transcription_service.save_transcription(
            transcript_data=test_data["transcript_data"],
            meeting_id=test_data["meeting_id"],
            user_id=test_data["user_id"],
        )

        # Verify transcript ID was generated
        assert transcript_id is not None
        assert len(transcript_id) == 16

        # Verify filename was generated
        assert filename is not None
        assert test_data["meeting_id"] in filename
        assert test_data["user_id"] in filename
        assert transcript_id in filename

        # Verify file exists
        file_path = os.path.join(transcription_service.storage_path, filename)
        assert os.path.exists(file_path)

        # Verify SQL entry exists
        assert await transcription_service.transcript_exists(transcript_id)

    async def test_retrieve_transcription(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test retrieving a transcription."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Save transcription first
        transcript_id, _ = await transcription_service.save_transcription(
            transcript_data=test_data["transcript_data"],
            meeting_id=test_data["meeting_id"],
            user_id=test_data["user_id"],
        )

        # Retrieve transcription
        retrieved_data = await transcription_service.retrieve_transcription(transcript_id)

        # Verify data matches
        assert retrieved_data is not None
        assert retrieved_data["text"] == test_data["transcript_data"]["text"]
        assert retrieved_data["language"] == test_data["transcript_data"]["language"]
        assert len(retrieved_data["segments"]) == len(test_data["transcript_data"]["segments"])

    async def test_delete_transcription(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test deleting a transcription."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Save transcription first
        transcript_id, filename = await transcription_service.save_transcription(
            transcript_data=test_data["transcript_data"],
            meeting_id=test_data["meeting_id"],
            user_id=test_data["user_id"],
        )

        file_path = os.path.join(transcription_service.storage_path, filename)

        # Verify file exists before deletion
        assert os.path.exists(file_path)
        assert await transcription_service.transcript_exists(transcript_id)

        # Delete transcription
        result = await transcription_service.delete_transcription(transcript_id)

        # Verify deletion was successful
        assert result is True
        assert not os.path.exists(file_path)
        assert not await transcription_service.transcript_exists(transcript_id)

    async def test_get_transcriptions_by_meeting(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test retrieving all transcriptions for a meeting."""
        import time

        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Save multiple transcriptions for the same meeting
        user_ids = ["111111111111111111", "222222222222222222", "333333333333333333"]
        saved_ids = []

        for i, user_id in enumerate(user_ids):
            # Make each transcript unique by including the user_id and iteration number
            unique_text = f"Transcript for user {user_id} at {time.time()}_{i}"
            unique_transcript_data = {
                "text": unique_text,
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.5,
                        "text": unique_text,
                    }
                ],
                "language": "en",
            }

            transcript_id, _ = await transcription_service.save_transcription(
                transcript_data=unique_transcript_data,
                meeting_id=test_data["meeting_id"],
                user_id=user_id,
            )
            saved_ids.append(transcript_id)

        # Retrieve all transcriptions for the meeting
        transcripts = await transcription_service.get_transcriptions_by_meeting(
            test_data["meeting_id"]
        )

        # Verify all transcriptions were retrieved
        assert len(transcripts) >= 3  # At least 3, may have more from previous tests
        retrieved_ids = [t["id"] for t in transcripts]
        for saved_id in saved_ids:
            assert saved_id in retrieved_ids

    async def test_get_transcription_by_user_and_meeting(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test retrieving a specific user's transcription for a meeting."""
        import random

        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Use a unique user_id for this test to avoid conflicts with previous test runs
        # Keep it within 18 characters (matching Discord user ID format)
        unique_user_id = f"{random.randint(100000000000000000, 999999999999999999)}"

        # Save transcription
        transcript_id, _ = await transcription_service.save_transcription(
            transcript_data=test_data["transcript_data"],
            meeting_id=test_data["meeting_id"],
            user_id=unique_user_id,
        )

        # Retrieve transcription by user and meeting
        transcript_meta = await transcription_service.get_transcription_by_user_and_meeting(
            meeting_id=test_data["meeting_id"], user_id=unique_user_id
        )

        # Verify correct transcription was retrieved
        assert transcript_meta is not None
        assert transcript_meta["id"] == transcript_id
        assert transcript_meta["user_id"] == unique_user_id

    async def test_save_transcription_with_custom_id(
        self, services_and_db, test_data, setup_meeting  # noqa: ARG002
    ):
        """Test saving a transcription with a custom ID."""
        import random

        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Use a unique custom ID to avoid conflicts with previous test runs
        # ID must be max 16 characters
        custom_id = f"cust{random.randint(10000000000, 99999999999)}"

        # Save transcription with custom ID
        transcript_id, filename = await transcription_service.save_transcription(
            transcript_data=test_data["transcript_data"],
            meeting_id=test_data["meeting_id"],
            user_id=test_data["user_id"],
            transcript_id=custom_id,
        )

        # Verify custom ID was used
        assert transcript_id == custom_id
        assert custom_id in filename

    async def test_save_transcription_empty_data_fails(self, services_and_db, test_data):
        """Test that saving empty transcription data fails."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Attempt to save empty data
        with pytest.raises(ValueError, match="Transcript data cannot be empty"):
            await transcription_service.save_transcription(
                transcript_data={},
                meeting_id=test_data["meeting_id"],
                user_id=test_data["user_id"],
            )

    async def test_retrieve_nonexistent_transcription(self, services_and_db):
        """Test retrieving a transcription that doesn't exist."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Attempt to retrieve nonexistent transcription
        result = await transcription_service.retrieve_transcription("nonexistent_id_12")

        # Verify None is returned
        assert result is None

    async def test_delete_nonexistent_transcription(self, services_and_db):
        """Test deleting a transcription that doesn't exist."""
        services_manager, _ = services_and_db
        transcription_service = services_manager.transcription_file_service_manager

        # Attempt to delete nonexistent transcription
        result = await transcription_service.delete_transcription("nonexistent_id_12")

        # Verify False is returned
        assert result is False
