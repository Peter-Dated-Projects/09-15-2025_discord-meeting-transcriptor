import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
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
    participants = Column(JSONB, nullable=False)
    recording_files = Column(JSONB, nullable=False)
    transcript_ids = Column(JSONB, nullable=False)


class RecordingModel(Base):
    __tablename__ = "recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    duration_in_ms = Column(Integer, nullable=False)
    meeting_id = Column(String(16), ForeignKey("meetings.id"), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False, unique=True)
    recording_filename = Column(String, nullable=False)


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
