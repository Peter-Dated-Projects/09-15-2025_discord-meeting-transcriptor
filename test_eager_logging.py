"""Test script to verify eager logging works during initialization."""

import asyncio
import os
from pathlib import Path

import dotenv

from source.constructor import ServerManagerType
from source.context import Context
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

dotenv.load_dotenv(dotenv_path=".env.local")


async def main():
    """Test eager logging during service initialization."""
    print("=" * 60)
    print("Testing Eager Logging Implementation")
    print("=" * 60)

    # Create context
    context = Context()

    # Initialize server manager
    print("\n1. Connecting to servers...")
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
    context.set_server_manager(servers_manager)
    await servers_manager.connect_all()
    print("✓ Connected all servers")

    # Setup paths
    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")

    # Initialize services - this is where eager logging should kick in
    print("\n2. Initializing services (watch for log messages)...")
    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        log_file="test_eager_logging.log",  # Use a specific log file for this test
    )
    context.set_services_manager(services_manager)

    # This should use eager logging for all initialization messages
    await services_manager.initialize_all()
    print("✓ Initialized all services")

    # Test logging after initialization
    print("\n3. Testing logging after initialization...")
    await services_manager.logging_service.info("Test message after initialization")
    await services_manager.logging_service.debug("Debug message for testing")
    await services_manager.logging_service.warning("Warning message for testing")
    await services_manager.logging_service.error("Error message for testing")
    print("✓ Sent test messages")

    # Give the queue time to process
    await asyncio.sleep(0.5)

    # Check the log file
    log_path = Path("logs") / "test_eager_logging.log"
    if log_path.exists():
        print(f"\n4. Log file created at: {log_path}")
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"✓ Log file contains {len(lines)} lines")

        print("\n5. First 10 log entries:")
        for i, line in enumerate(lines[:10], 1):
            print(f"   {i}. {line.strip()}")
    else:
        print(f"\n✗ Log file not found at {log_path}")

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
