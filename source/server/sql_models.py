import enum

from sqlalchemy import JSON, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

from source.utils import MEETING_UUID_LENGTH

# -------------------------------------------------------------- #
# SQL Database Data Models
# -------------------------------------------------------------- #

Base = declarative_base()


class MeetingStatus(enum.Enum):
    SCHEDULED = "scheduled"
    RECORDING = "recording"
    PAUSED = "paused"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    CLEANING = "cleaning"
    COMPLETED = "completed"


class JobsType(enum.Enum):
    TEMP_TRANSCODING = "temp_transcoding"
    TRANSCODING = "transcoding"
    TRANSCRIBING = "transcribing"
    COMPILING = "compiling"
    SUMMARIZING = "summarizing"
    TEXT_EMBEDDING = "text_embedding"
    CLEANING = "cleaning"
    CHATBOT = "chatbot"
    CONTEXT_CLEANING = "context_cleaning"


class JobsStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TranscodeStatus(enum.Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class SubscriptionType(enum.Enum):
    FREE = "free"
    PAID = "paid"


# -------------------------------------------------------------- #
# Models
# -------------------------------------------------------------- #


class MeetingModel(Base):
    """
    ID = Meeting ID
    Guild ID = Discord Guild (Server) ID
    Channel ID = Discord Channel ID
    Started At = Timestamp when meeting started
    Ended At = Timestamp when meeting ended
    Updated At = Timestamp when meeting was last updated
    Status = Current status of the meeting (scheduled, recording, processing, cleaning, completed)
    Requested By = Discord User ID of the user who requested the meeting
    Participants = List of participant Discord User IDs
    Recording Files = List of recording file metadata
        - {user_id: recording_id, ...}
    Transcript IDs = List of associated transcript IDs
        - {user_id: transcript_id, ...}
    """

    __tablename__ = "meetings"

    id = Column(String(16), primary_key=True, index=True)
    guild_id = Column(String(20), nullable=False, index=True)
    channel_id = Column(String(20), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    status = Column(
        Enum(MeetingStatus, name="meetings_status_enum"),
        nullable=False,
        default=MeetingStatus.SCHEDULED.value,
    )
    requested_by = Column(String(20), nullable=False)
    participants = Column(JSON, nullable=False, default=dict)
    recording_files = Column(JSON, nullable=False, default=dict)
    transcript_ids = Column(JSON, nullable=False, default=dict)


class RecordingModel(Base):
    """
    ID = Recording ID
    Created At = Timestamp when recording was created
    Duration in ms = Duration of the recording in milliseconds
    User ID = Discord User ID of the participant
    Meeting ID = Foreign Key to associated Meeting ID
    SHA256 = SHA256 hash of the recording file
    Recording Filename = Filename of the recording file
    """

    __tablename__ = "recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    duration_in_ms = Column(Integer, nullable=False)
    user_id = Column(String(20), nullable=False)
    meeting_id = Column(
        String(MEETING_UUID_LENGTH), ForeignKey("meetings.id"), nullable=False, index=True
    )
    sha256 = Column(String(64), nullable=False, unique=True)
    filename = Column(String(512), nullable=False)


class JobsStatusModel(Base):
    """
    ID = Job ID
    Type = Job Type (transcoding, transcribing, cleaning)
    Meeting ID = Foreign Key to associated Meeting ID
    Created At = Timestamp when job was created
    Started At = Timestamp when job started
    Finished At = Timestamp when job finished
    Status = Current status of the job (pending, in_progress, completed, failed, skipped)
    Error Log = Foreign Key to error log entry if job failed
    """

    __tablename__ = "jobs_status"

    id = Column(String(16), primary_key=True, index=True)
    type = Column(Enum(JobsType, name="jobs_type_enum"), nullable=False)
    meeting_id = Column(
        String(MEETING_UUID_LENGTH), ForeignKey("meetings.id"), nullable=False, index=True
    )
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(Enum(JobsStatus, name="jobs_status_enum"), nullable=False)
    error_log = Column(String(16), nullable=True)


class JobsModel(Base):
    """
    Generic jobs table for non-meeting related jobs (e.g., chat, background tasks).

    ID = Job ID (16 char UUID)
    Created At = Timestamp when job was created
    Updated At = Timestamp when job was last updated
    Status = Current status of the job (pending, in_progress, completed, failed, skipped)
    Type = Job Type (chatbot, etc)
    Meta = JSON metadata for the job (flexible storage for job-specific data)
    """

    __tablename__ = "jobs"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(JobsStatus, name="jobs_status_enum"), nullable=False)
    type = Column(Enum(JobsType, name="jobs_type_enum"), nullable=False)
    meta = Column(JSON, nullable=False, default=dict)


class UserTranscriptsModel(Base):
    """
    ID = Transcript ID
    Created At = Timestamp when transcript was created
    Meeting ID = Foreign Key to associated Meeting ID
    User ID = Discord User ID of the participant
    sha256 = SHA256 hash of the transcript file
    Transcript Filename = Filename of the transcript file
    """

    __tablename__ = "user_transcripts"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    meeting_id = Column(
        String(MEETING_UUID_LENGTH), ForeignKey("meetings.id"), nullable=False, index=True
    )
    user_id = Column(String(20), nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    transcript_filename = Column(String(512), nullable=False)


class CompiledTranscriptsModel(Base):
    """
    ID = Compiled Transcript ID
    Created At = Timestamp when compiled transcript was created
    Meeting ID = Foreign Key to associated Meeting ID
    sha256 = SHA256 hash of the compiled transcript file
    Transcript Filename = Filename of the compiled transcript file
    """

    __tablename__ = "compiled_transcripts"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    meeting_id = Column(
        String(MEETING_UUID_LENGTH), ForeignKey("meetings.id"), nullable=False, index=True
    )
    sha256 = Column(String(64), nullable=False, unique=True)
    transcript_filename = Column(String(512), nullable=False)


class GuildAdminWhitelistModel(Base):
    """
    ID = Whitelist Entry ID
    Guild ID = Discord Guild (Server) ID
    Whitelist User ID = Discord User ID of the user to whitelist
    Created_At = Timestamp when the whitelist entry was created
    """

    __tablename__ = "guild_admin_whitelist"

    id = Column(String(16), primary_key=True, index=True)
    guild_id = Column(String(20), nullable=False, unique=True, index=True)
    whitelist_user_id = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False)


class JobsStatusErrorLogModel(Base):
    """
    ID = Error Log Entry ID
    Job ID = Foreign Key to associated Job ID
    Created At = Timestamp when the error log entry was created
    """

    __tablename__ = "jobs_status_error_logs"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    log_file = Column(String(512), nullable=False)


class TempRecordingModel(Base):
    """
    ID = Recording ID
    Created At = Timestamp when recording was created
    User ID = Discord User ID of the participant
    Meeting ID = Foreign Key to associated Meeting ID
    Filename = Filename of the recording file
        - assets/recordings/yyyy-mm-dd_recording_{user_id}_{timestamp in ms}.???
    Transcode Status = Status of the FFmpeg transcode job (queued, in_progress, done, failed)
    """

    __tablename__ = "temp_recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    user_id = Column(String(20), nullable=False)
    meeting_id = Column(
        String(MEETING_UUID_LENGTH), ForeignKey("meetings.id"), nullable=False, index=True
    )
    filename = Column(String(512), nullable=False)
    timestamp_ms = Column(Integer, nullable=False)
    transcode_status = Column(
        Enum(TranscodeStatus, name="transcode_status_enum"),
        nullable=False,
        default=TranscodeStatus.QUEUED.value,
    )


class ConversationsModel(Base):
    """
    ID = Conversation ID (16 char UUID)
    Created At = Timestamp when conversation was created
    Updated At = Timestamp when conversation was last updated
    Discord Thread ID = Discord Thread ID where the chat is located
    Chat Meta = JSON metadata for the conversation (stored as empty JSON by default)
    Discord Requester ID = Discord User ID of the user who initiated the conversation
    Discord Guild ID = Discord Guild (Server) ID of the conversation
    Monitoring Stopped = Boolean indicating if monitoring is stopped for this conversation
    """

    __tablename__ = "conversations"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    discord_thread_id = Column(String(20), nullable=False, index=True)
    chat_meta = Column(JSON, nullable=False, default=dict)
    discord_requester_id = Column(String(20), nullable=False, index=True)
    discord_guild_id = Column(String(20), nullable=False, index=True)
    monitoring_stopped = Column(Integer, nullable=False, default=0, server_default="0")


class ConversationsStoreModel(Base):
    """
    ID = Conversations Store ID (16 char UUID)
    Created At = Timestamp when store entry was created
    Updated At = Timestamp when store entry was last updated
    Session ID = Foreign Key to conversations table
    Filename = Path/filename where chat is persisted on disk
    """

    __tablename__ = "conversations_store"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    session_id = Column(String(16), ForeignKey("conversations.id"), nullable=False, index=True)
    filename = Column(String(512), nullable=False, index=True)


class SubscriptionsModel(Base):
    """
    Discord Server ID = Discord Guild (Server) ID (Primary Key)
    Chroma Collection Name = Name of the Chroma collection for this guild
    Joined Guild At = Timestamp when the guild was joined/registered
    Activated Guild At = Timestamp when the subscription was activated (nullable)
    Subscription Type = Type of subscription (FREE, PAID)
    """

    __tablename__ = "subscriptions"

    discord_server_id = Column(String(20), primary_key=True, index=True)
    chroma_collection_name = Column(String(256), nullable=False)
    joined_guild_at = Column(DateTime, nullable=False)
    activated_guild_at = Column(DateTime, nullable=True)
    subscription_type = Column(
        Enum(SubscriptionType, name="subscription_type_enum"),
        nullable=False,
        default=SubscriptionType.FREE.value,
    )
