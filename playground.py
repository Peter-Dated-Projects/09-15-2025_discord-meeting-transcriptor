import asyncio
import os

import dotenv

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

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
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT)
    await servers_manager.connect_all()
    print("✓ Connected all servers")

    # Initialize services manager
    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")

    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        server=servers_manager,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
    )
    await services_manager.initialize_all()
    print("✓ Initialized all services")

    # -------------------------------------------------------------- #
    # Playground for testing services
    # -------------------------------------------------------------- #

    # test the ffmpeg service
    success = await services_manager.ffmpeg_service_manager.queue_mp3_to_whisper_format_job(
        input_path=r"C:\Users\peter\Videos\audio-recording-1.m4a",
        output_path="assets/data/test_output.wav",
        options={"-f": "s16le", "-ar": "48000", "-y": None},
    )
    if success:
        print("✓ FFmpeg conversion completed successfully")
    else:
        print("✗ FFmpeg conversion failed")

    # -------------------------------------------------------------- #
    # Cleanup
    # -------------------------------------------------------------- #

    print("\n" + "=" * 60)
    print("Cleaning up...")
    print("=" * 60)

    await servers_manager.disconnect_all()
    print("✓ Disconnected all servers")
    print("✓ Done")


if __name__ == "__main__":
    asyncio.run(main())
