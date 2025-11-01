import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
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


class MeetingModel(Base):
    __tablename__ = "meetings"

    id = Column(String(16), primary_key=True, index=True)
    guild_id = Column(String(20), nullable=False, index=True)
    channel_id = Column(String(20), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default=MeetingStatus.SCHEDULED.value)
    requested_by = Column(String(20), nullable=False)
    participants = Column(JSONB, nullable=False)
    recording_files = Column(JSONB, nullable=False)
    transcript_ids = Column(JSONB, nullable=False)


class RecordingModel(Base):
    __tablename__ = "recordings"

    id = Column(String(16), primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False)
    duration_in_ms = Column(Integer, nullable=False)
    meeting_id = Column(String(16), ForeignKey('meetings.id'), nullable=False, index=True)
    sha256 = Column(String(64), nullable=False, unique=True)
    recording_filename = Column(String, nullable=False)
