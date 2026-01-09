import os
import platform
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from source.context import Context

from source.constructor import ServerManagerType
from source.services.logger import AsyncLoggingService
from source.services.manager import ServicesManager

# prefer a project-local .env.local file, then fallback to any .env
load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Services Manager
# -------------------------------------------------------------- #


def construct_services_manager(
    service_type: ServerManagerType,
    context: "Context",
    storage_path: str,
    recording_storage_path: str,
    transcription_storage_path: str,
    conversation_storage_path: str,
    default_logging_path: str = "logs",
    log_file: str | None = None,
    use_timestamp_logs: bool = True,
):
    """Construct and return a service manager instance based on the service type.

    Args:
        service_type: Type of server manager (DEVELOPMENT or PRODUCTION)
        context: Context instance containing server and services
        storage_path: Path for general file storage
        recording_storage_path: Path for recording file storage
        transcription_storage_path: Path for transcription JSON file storage
        conversation_storage_path: Path for conversation JSON file storage
        default_logging_path: Directory to store log files (default: "logs")
        log_file: Specific log file name (optional, overrides use_timestamp_logs)
        use_timestamp_logs: If True and log_file is None, creates timestamped log files (default: True)
    """

    file_service_manager = None
    recording_file_service_manager = None
    transcription_file_service_manager = None
    conversation_file_service_manager = None
    ffmpeg_service_manager = None
    sql_recording_service_manager = None
    sql_logging_service_manager = None
    subscription_sql_manager = None
    discord_recorder_service_manager = None
    presence_manager_service = None
    transcription_job_manager = None
    transcription_compilation_job_manager = None
    summarization_job_manager = None
    text_embedding_job_manager = None
    gpu_resource_manager = None
    ollama_request_manager = None
    conversation_manager = None
    chat_job_manager = None
    instagram_reels_manager = None

    # create logger
    logging_service = AsyncLoggingService(
        context=context,
        log_dir=default_logging_path,
        log_file=log_file,
        use_timestamp=use_timestamp_logs,
    )

    # create file service manager
    if (
        service_type == ServerManagerType.DEVELOPMENT
        or service_type == ServerManagerType.PRODUCTION
    ):

        # -------------------------------------------------------------- #
        # Service Managers Setup
        # -------------------------------------------------------------- #

        from source.services.chat.conversation_file_manager.manager import (
            ConversationFileManagerService,
        )
        from source.services.common.file_manager.manager import FileManagerService
        from source.services.discord.recording_file_manager.manager import (
            RecordingFileManagerService,
        )
        from source.services.gpu.ffmpeg_manager.manager import FFmpegManagerService
        from source.services.transcription.transcription_file_manager.manager import (
            TranscriptionFileManagerService,
        )

        file_service_manager = FileManagerService(context=context, storage_path=storage_path)
        recording_file_service_manager = RecordingFileManagerService(
            context=context, recording_storage_path=recording_storage_path
        )
        transcription_file_service_manager = TranscriptionFileManagerService(
            context=context, transcription_storage_path=transcription_storage_path
        )
        conversation_file_service_manager = ConversationFileManagerService(
            context=context, conversation_storage_path=conversation_storage_path
        )

        # Decide ffmpeg binary path based on environment and platform
        if platform.system().lower().startswith("win") or os.name == "nt":
            ffmpeg_env = os.getenv("WINDOWS_FFMPEG_PATH")
        else:
            ffmpeg_env = os.getenv("MAC_FFMPEG_PATH")

        ffmpeg_path = ffmpeg_env

        ffmpeg_service_manager = FFmpegManagerService(context=context, ffmpeg_path=ffmpeg_path)

        # -------------------------------------------------------------- #
        # DB Interfaces Setup
        # -------------------------------------------------------------- #

        from source.services.chat.conversations_sql_manager.manager import (
            ConversationsSQLManagerService,
        )
        from source.services.chat.conversations_store_sql_manager.manager import (
            ConversationsStoreSQLManagerService,
        )
        from source.services.common.sql_logging_manager.manager import SQLLoggingManagerService
        from source.services.common.subscription_sql_manager.manager import (
            SubscriptionSQLManagerService,
        )
        from source.services.discord.recording_sql_manager.manager import SQLRecordingManagerService

        sql_recording_service_manager = SQLRecordingManagerService(context=context)
        sql_logging_service_manager = SQLLoggingManagerService(context=context)
        subscription_sql_manager = SubscriptionSQLManagerService(context=context)
        conversations_sql_manager = ConversationsSQLManagerService(context=context)
        conversations_store_sql_manager = ConversationsStoreSQLManagerService(context=context)

        # -------------------------------------------------------------- #
        # Discord Recorder Setup
        # -------------------------------------------------------------- #

        from source.services.discord.discord_recorder_manager.manager import (
            DiscordRecorderManagerService,
        )

        discord_recorder_service_manager = DiscordRecorderManagerService(context=context)

        # -------------------------------------------------------------- #
        # Presence Manager Setup
        # -------------------------------------------------------------- #

        from source.services.discord.presence_manager.manager import PresenceManagerService

        presence_manager_service = PresenceManagerService(context=context)

        # -------------------------------------------------------------- #
        # Transcription Job Manager Setup
        # -------------------------------------------------------------- #

        from source.services.transcription.transcription_job_manager.compiler import (
            TranscriptionCompilationJobManagerService,
        )
        from source.services.transcription.transcription_job_manager.manager import (
            TranscriptionJobManagerService,
        )

        transcription_job_manager = TranscriptionJobManagerService(context=context)
        transcription_compilation_job_manager = TranscriptionCompilationJobManagerService(
            context=context
        )

        # -------------------------------------------------------------- #
        # Summarization Job Manager Setup
        # -------------------------------------------------------------- #

        from source.services.transcription.summarization_job_manager.manager import (
            SummarizationJobManagerService,
        )

        summarization_job_manager = SummarizationJobManagerService(context=context)

        # -------------------------------------------------------------- #
        # Text Embedding Job Manager Setup
        # -------------------------------------------------------------- #

        from source.services.transcription.text_embedding_manager.manager import (
            TextEmbeddingJobManagerService,
        )

        text_embedding_job_manager = TextEmbeddingJobManagerService(context=context)

        # -------------------------------------------------------------- #
        # GPU Resource Manager Setup
        # -------------------------------------------------------------- #

        from source.services.gpu.gpu_resource_manager import GPUResourceManager

        gpu_resource_manager = GPUResourceManager(context=context)

        # -------------------------------------------------------------- #
        # Ollama Request Manager Setup
        # -------------------------------------------------------------- #

        from source.services.gpu.ollama_request_manager.manager import OllamaRequestManager

        ollama_request_manager = OllamaRequestManager(context=context)

        # -------------------------------------------------------------- #
        # Conversation Manager Setup
        # -------------------------------------------------------------- #

        from source.services.chat.conversation_manager.in_memory_cache import (
            InMemoryConversationManager,
        )

        conversation_manager = InMemoryConversationManager(
            conversation_file_manager=conversation_file_service_manager
        )

        # -------------------------------------------------------------- #
        # Chat Job Manager Setup
        # -------------------------------------------------------------- #

        from source.services.chat.chat_job_manager.manager import ChatJobManagerService
        from source.services.misc.instagram_reels.manager import InstagramReelsManager

        chat_job_manager = ChatJobManagerService(context=context)
        instagram_reels_manager = InstagramReelsManager(context=context)

        # -------------------------------------------------------------- #
        # MCP Manager Setup
        # -------------------------------------------------------------- #

        from source.services.chat.mcp import MCPManager

        mcp_manager = MCPManager(context=context)

    # TODO: https://www.notion.so/DISC-19-create-ffmpeg-service-29c5eca3b9df805a949fdcd5850eaf5a?source=copy_link
    # # create ffmpeg service manager
    # if service_type == ServerManagerType.DEVELOPMENT:
    #     from source.services.ffmpeg.manager import FFmpegService
    #     ffmpeg_service_manager = FFmpegService()

    if (
        not file_service_manager or not sql_recording_service_manager
    ):  # or not ffmpeg_service_manager:
        raise ValueError(f"Unsupported service type: {service_type}")

    return ServicesManager(
        context=context,
        file_service_manager=file_service_manager,
        recording_file_service_manager=recording_file_service_manager,
        transcription_file_service_manager=transcription_file_service_manager,
        ffmpeg_service_manager=ffmpeg_service_manager,
        logging_service=logging_service,
        sql_recording_service_manager=sql_recording_service_manager,
        sql_logging_service_manager=sql_logging_service_manager,
        conversation_file_service_manager=conversation_file_service_manager,
        subscription_sql_manager=subscription_sql_manager,
        conversations_sql_manager=conversations_sql_manager,
        conversations_store_sql_manager=conversations_store_sql_manager,
        discord_recorder_service_manager=discord_recorder_service_manager,
        presence_manager_service=presence_manager_service,
        transcription_job_manager=transcription_job_manager,
        transcription_compilation_job_manager=transcription_compilation_job_manager,
        summarization_job_manager=summarization_job_manager,
        text_embedding_job_manager=text_embedding_job_manager,
        gpu_resource_manager=gpu_resource_manager,
        ollama_request_manager=ollama_request_manager,
        conversation_manager=conversation_manager,
        chat_job_manager=chat_job_manager,
        instagram_reels_manager=instagram_reels_manager,
        mcp_manager=mcp_manager,
    )
