import enum

from sqlalchemy import CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

# -------------------------------------------------------------- #
# SQL Database Data Models
# -------------------------------------------------------------- #

Base = declarative_base()


class MeetingStatus(enum.Enum):
    SCHEDULED = "scheduled"
    RECORDING = "recording"
    PROCESSING = "processing"
    CLEANING = "cleaning"
    COMPLETED = "completed"


class JobsType(enum.Enum):
    TRANSCODING = "transcoding"
    TRANSCRIBING = "transcribing"
    CLEANING = "cleaning"


class JobsStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


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

    __table_args__ = (
        # define constraints for recording_files: {user_id: recording_id, ...}
        CheckConstraint(
            "jsonb_typeof(recording_files) = 'object'", name="recording_files_jsonb_object"
        ),
        # define constraints for transcript_ids: {user_id: transcript_id, ...}
        CheckConstraint(
            "jsonb_typeof(transcript_ids) = 'object'", name="transcript_ids_jsonb_object"
        ),
    )

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
    participants = Column(JSONB, nullable=False, default=dict)
    recording_files = Column(JSONB, nullable=False, default=dict)
    transcript_ids = Column(JSONB, nullable=False, default=dict)


class RecordingModel(Base):
    """
    ID = Recording ID
    Created At = Timestamp when recording was created
    Duration in ms = Duration of the recording in milliseconds
    Meeting ID = Foreign Key to associated Meeting ID
    SHA256 = SHA256 hash of the recording file
    Recording Filename = Filename of the recording file
    """

    __tablename__ = "recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    duration_in_ms = Column(Integer, nullable=False)
    meeting_id = Column(String(16), ForeignKey("meetings.id"), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False, unique=True)
    filename = Column(String, nullable=False)


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
    meeting_id = Column(String(16), ForeignKey("meetings.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    status = Column(Enum(JobsStatus, name="jobs_status_enum"), nullable=False)
    error_log = Column(String(16), nullable=True)


class TranscriptsModel(Base):
    """
    ID = Transcript ID
    Created At = Timestamp when transcript was created
    Meeting ID = Foreign Key to associated Meeting ID
    User ID = Discord User ID of the participant
    sha256 = SHA256 hash of the transcript file
    Transcript Filename = Filename of the transcript file
    """

    __tablename__ = "transcripts"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    meeting_id = Column(String(16), ForeignKey("meetings.id"), nullable=False, index=True)
    user_id = Column(String(20), nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    transcript_filename = Column(String, nullable=False)


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
    log_file = Column(String, nullable=False)


class TempRecordingModel(Base):
    """
    ID = Temporary Recording ID
    Created At = Timestamp when temporary recording was created
    Meeting ID = Foreign Key to associated Meeting ID
    Filename = Filename of the temporary recording file
    """

    __tablename__ = "temp_recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    meeting_id = Column(String(16), ForeignKey("meetings.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
