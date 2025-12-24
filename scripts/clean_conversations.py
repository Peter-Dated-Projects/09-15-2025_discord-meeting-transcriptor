import asyncio
import argparse
import os
import sys
from pathlib import Path
import dotenv

# Add source to path
sys.path.append(os.getcwd())

from source.constructor import ServerManagerType
from source.context import Context
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

dotenv.load_dotenv(dotenv_path=".env.local")

async def main():
    parser = argparse.ArgumentParser(description="Clean up conversations from the database.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Delete conversation by ID")
    group.add_argument("--thread-id", help="Delete conversation by Discord Thread ID")
    group.add_argument("--guild-id", help="Delete all conversations for a Discord Guild ID")
    
    args = parser.parse_args()

    print("Initializing services...")

    # Initialize Context and Managers
    context = Context()
    
    # Init Server Manager
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
    context.set_server_manager(servers_manager)
    await servers_manager.connect_all()
    
    # Init Services Manager
    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")
    transcription_storage_path = os.getenv("TRANSCRIPTION_STORAGE_PATH", "assets/data/transcriptions")
    conversation_storage_path = os.path.join(storage_path, "conversations")
    
    # Ensure logs directory exists
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        transcription_storage_path=transcription_storage_path,
        conversation_storage_path=conversation_storage_path,
        log_file="logs/cleanup_script.log"
    )
    context.set_services_manager(services_manager)
    await services_manager.initialize_all()
    
    sql_manager = services_manager.conversations_sql_manager
    
    try:
        if args.id:
            print(f"Deleting conversation with ID: {args.id}")
            await sql_manager.delete_conversation_by_id(args.id)
        elif args.thread_id:
            print(f"Deleting conversation with Thread ID: {args.thread_id}")
            await sql_manager.delete_conversation_by_thread_id(args.thread_id)
        elif args.guild_id:
            print(f"Deleting all conversations for Guild ID: {args.guild_id}")
            await sql_manager.delete_conversations_by_guild_id(args.guild_id)
            
        print("Operation completed successfully.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing connections...")
        await servers_manager.disconnect_all()
        await services_manager.close_all()

if __name__ == "__main__":
    asyncio.run(main())
