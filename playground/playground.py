import asyncio
import os

import dotenv

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.server.sql_models import MeetingStatus, RecordingModel, TempRecordingModel
from source.services.constructor import construct_services_manager
from source.services.recording_sql_manager.manager import SQLRecordingManagerService
from source.utils import generate_16_char_uuid, get_current_timestamp_est

dotenv.load_dotenv(dotenv_path=".env.local")


async def main():
    """Main function to setup services and run transcription."""
    # -------------------------------------------------------------- #
    # Startup services
    # -------------------------------------------------------------- #

    print("=" * 60)
    print("Setting up server and services...")
    print("=" * 60)

    # Initialize server manager
    from source.context import Context

    context = Context()

    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
    context.set_server_manager(servers_manager)
    await servers_manager.connect_all()
    print("✓ Connected all servers")

    # Initialize services manager
    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")
    transcription_storage_path = os.getenv(
        "TRANSCRIPTION_STORAGE_PATH", "assets/data/transcriptions"
    )

    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        transcription_storage_path=transcription_storage_path,
    )
    await services_manager.initialize_all()
    print("✓ Initialized all services")

    # -------------------------------------------------------------- #
    # Test Data Setup
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("TEST: SQL Recording Manager Service")
    print("=" * 60)

    # Get the recording SQL service
    recording_sql_service: SQLRecordingManagerService = (
        services_manager.sql_recording_service_manager
    )

    # Test IDs and data
    test_user_id = "1234567890123456"  # Discord User ID (16 chars min)
    test_guild_id = "1234567890"  # Discord Guild ID
    test_channel_id = "9876543210"  # Discord Channel ID
    test_meeting_id = generate_16_char_uuid()  # Generate a meeting ID (16 chars)
    test_audio_file = os.path.join("tests", "assets", "pokemon_song.mp3")

    print(f"\nTest User ID: {test_user_id}")
    print(f"Test Guild ID: {test_guild_id}")
    print(f"Test Channel ID: {test_channel_id}")
    print(f"Test Meeting ID: {test_meeting_id}")
    print(f"Test Audio File: {test_audio_file}")

    # -------------------------------------------------------------- #
    # CLEANUP: Remove any existing test data
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("CLEANUP: Removing existing test data")
    print("=" * 60)

    db_service = servers_manager.sql_client

    # Delete any existing recordings for this test file (by SHA256)
    print("\n[Cleanup] Deleting existing recordings with test file SHA256...")
    from sqlalchemy import delete

    from source.utils import calculate_file_sha256

    test_sha256 = calculate_file_sha256(test_audio_file)
    cleanup_recordings_stmt = delete(RecordingModel).where(RecordingModel.sha256 == test_sha256)
    await db_service.execute(cleanup_recordings_stmt)
    print("✓ Cleaned up existing recordings")

    # -------------------------------------------------------------- #
    # TEST 0: Create Required Meeting (Foreign Key Dependency)
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("TEST 0: Creating Meeting (Required Foreign Key)")
    print("=" * 60)

    # Create a meeting first (required for all recording operations)
    now = get_current_timestamp_est()

    # Insert meeting
    print("\n[0.1] Inserting meeting...")
    from sqlalchemy import insert

    from source.server.sql_models import MeetingModel

    meeting_stmt = insert(MeetingModel).values(
        id=test_meeting_id,
        guild_id=test_guild_id,
        channel_id=test_channel_id,
        started_at=now,
        ended_at=now,
        status=MeetingStatus.RECORDING.value,
        requested_by=test_user_id,
        participants={test_user_id: test_user_id},
        recording_files={},
        transcript_ids={},
    )
    await db_service.execute(meeting_stmt)
    print(f"✓ Created meeting with ID: {test_meeting_id}")

    # -------------------------------------------------------------- #
    # TEST 1: Temp Recording CRUD Operations
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("TEST 1: Temp Recording CRUD Operations")
    print("=" * 60)

    # INSERT Temp Recording
    print("\n[1.1] Inserting temp recording...")
    temp_filename = os.path.join("assets", "data", "temp", "test_recording_temp.mp3")
    temp_recording_id = await recording_sql_service.insert_temp_recording(
        user_id=test_user_id,
        meeting_id=test_meeting_id,
        start_timestamp_ms=1000,
        filename=temp_filename,
    )
    print(f"✓ Inserted temp recording with ID: {temp_recording_id}")

    # QUERY Temp Recording by Meeting
    print("\n[1.2] Querying temp recordings for meeting...")
    temp_recordings = await recording_sql_service.get_temp_recordings_for_meeting(test_meeting_id)
    print(f"✓ Found {len(temp_recordings)} temp recording(s)")
    for recording in temp_recordings:
        print(f"  - ID: {recording.get('id')}, User: {recording.get('user_id')}")

    # QUERY Temp Recording by User
    print("\n[1.3] Querying temp recordings for user...")
    user_temp_recordings = await recording_sql_service.get_temp_recordings_for_user(test_user_id)
    print(f"✓ Found {len(user_temp_recordings)} temp recording(s) for user")

    # DELETE Temp Recording
    print("\n[1.4] Deleting temp recording...")
    await recording_sql_service.delete_temp_recording(temp_recording_id)
    print(f"✓ Deleted temp recording: {temp_recording_id}")

    # VERIFY Deletion
    print("\n[1.5] Verifying deletion...")
    verify_recordings = await recording_sql_service.get_temp_recordings_for_meeting(test_meeting_id)
    print(f"✓ After deletion, found {len(verify_recordings)} temp recording(s)")

    # -------------------------------------------------------------- #
    # TEST 2: Persistent Recording CRUD Operations
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("TEST 2: Persistent Recording CRUD Operations")
    print("=" * 60)

    # INSERT Persistent Recording
    print("\n[2.1] Inserting persistent recording...")
    persistent_recording_id = await recording_sql_service.insert_persistent_recording(
        user_id=test_user_id,
        meeting_id=test_meeting_id,
        filename=test_audio_file,
    )
    print(f"✓ Inserted persistent recording with ID: {persistent_recording_id}")

    # QUERY Persistent Recording by Meeting
    print("\n[2.2] Querying persistent recordings for meeting...")
    persistent_recordings = await recording_sql_service.get_persistent_recordings_for_meeting(
        test_meeting_id
    )
    print(f"✓ Found {len(persistent_recordings)} persistent recording(s)")
    for recording in persistent_recordings:
        print(f"  - ID: {recording.get('id')}, User: {recording.get('user_id')}")

    # QUERY Persistent Recording by User
    print("\n[2.3] Querying persistent recordings for user...")
    user_persistent_recordings = await recording_sql_service.get_persistent_recordings_for_user(
        test_user_id
    )
    print(f"✓ Found {len(user_persistent_recordings)} persistent recording(s) for user")

    # DELETE Persistent Recording
    print("\n[2.4] Deleting persistent recording...")
    await recording_sql_service.delete_temp_recording(persistent_recording_id)
    print(f"✓ Deleted persistent recording: {persistent_recording_id}")

    # VERIFY Deletion
    print("\n[2.5] Verifying deletion...")
    verify_persistent = await recording_sql_service.get_persistent_recordings_for_meeting(
        test_meeting_id
    )
    print(f"✓ After deletion, found {len(verify_persistent)} persistent recording(s)")

    # -------------------------------------------------------------- #
    # TEST 3: Bulk Operations
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("TEST 3: Bulk Operations")
    print("=" * 60)

    # Create multiple temp recordings
    print("\n[3.1] Creating multiple temp recordings...")
    temp_ids = []
    for i in range(3):
        temp_id = await recording_sql_service.insert_temp_recording(
            user_id=test_user_id,
            meeting_id=test_meeting_id,
            start_timestamp_ms=1000 + i * 1000,
            filename=f"assets/data/temp/test_recording_temp_{i}.mp3",
        )
        temp_ids.append(temp_id)
        print(f"  ✓ Created: {temp_id}")

    # Query all temp recordings
    print("\n[3.2] Querying all temp recordings...")
    all_temp = await recording_sql_service.get_temp_recordings_for_meeting(test_meeting_id)
    print(f"✓ Found {len(all_temp)} total temp recording(s)")

    # Delete multiple temp recordings
    print("\n[3.3] Deleting multiple temp recordings...")
    await recording_sql_service.delete_temp_recordings(temp_ids)
    print(f"✓ Deleted {len(temp_ids)} temp recording(s)")

    # Verify bulk deletion
    print("\n[3.4] Verifying bulk deletion...")
    verify_bulk = await recording_sql_service.get_temp_recordings_for_meeting(test_meeting_id)
    print(f"✓ After bulk deletion, found {len(verify_bulk)} temp recording(s)")

    # -------------------------------------------------------------- #
    # Cleanup
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("Cleaning up...")
    print("=" * 60)

    # Delete recordings first (foreign key dependency)
    print("\n[Cleanup] Deleting all recordings for test meeting...")
    from sqlalchemy import delete

    # Delete all temp recordings for this meeting
    delete_temp_recordings_stmt = delete(TempRecordingModel).where(
        TempRecordingModel.meeting_id == test_meeting_id
    )
    await db_service.execute(delete_temp_recordings_stmt)

    # Delete all persistent recordings for this meeting
    delete_recordings_stmt = delete(RecordingModel).where(
        RecordingModel.meeting_id == test_meeting_id
    )
    await db_service.execute(delete_recordings_stmt)
    print(f"✓ Deleted all recordings for meeting: {test_meeting_id}")

    # Now delete the test meeting
    print("\n[Cleanup] Deleting test meeting...")
    delete_meeting_stmt = delete(MeetingModel).where(MeetingModel.id == test_meeting_id)
    await db_service.execute(delete_meeting_stmt)
    print(f"✓ Deleted test meeting: {test_meeting_id}")

    await servers_manager.disconnect_all()
    print("✓ Disconnected all servers")
    print("✓ Done")


if __name__ == "__main__":
    asyncio.run(main())
