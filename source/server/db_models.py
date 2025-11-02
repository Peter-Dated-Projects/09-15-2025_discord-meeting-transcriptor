from pydantic import RootModel, field_validator

from source.server.sql_models import (
    GuildAdminWhitelistModel,
    JobsStatusErrorLogModel,
    JobsStatusModel,
    MeetingModel,
    RecordingModel,
    TranscriptsModel,
    TempRecordingModel,
)

# -------------------------------------------------------------- #
# SQL DB Models
# -------------------------------------------------------------- #

SQL_DATABASE_MODELS = [
    MeetingModel,
    RecordingModel,
    JobsStatusModel,
    TranscriptsModel,
    GuildAdminWhitelistModel,
    JobsStatusErrorLogModel,
    TempRecordingModel,
]


# -------------------------------------------------------------- #
# Pydantic Validation Models for JSONB Fields
# -------------------------------------------------------------- #


class RecordingFilesMapping(RootModel[dict[str, str]]):
    """
    Represents the structure: {user_id: recording_id}
    where user_id is a Discord User ID (string) and recording_id is a Recording ID (string)
    """

    root: dict[str, str]  # Maps user_id -> recording_id

    @field_validator("root")
    def validate_format(cls, v: dict[str, str]) -> dict[str, str]:
        if not isinstance(v, dict):
            raise ValueError("Must be a dictionary")
        for user_id, recording_id in v.items():
            if not isinstance(user_id, str) or not isinstance(recording_id, str):
                raise ValueError("Both keys and values must be strings (user_id and recording_id)")
            if len(user_id) == 0 or len(recording_id) == 0:
                raise ValueError("user_id and recording_id cannot be empty")
        return v


class TranscriptIdsMapping(RootModel[dict[str, str]]):
    """
    Represents the structure: {user_id: transcript_id}
    where user_id is a Discord User ID (string) and transcript_id is a Transcript ID (string)
    """

    root: dict[str, str]  # Maps user_id -> transcript_id

    @field_validator("root")
    def validate_format(cls, v: dict[str, str]) -> dict[str, str]:
        if not isinstance(v, dict):
            raise ValueError("Must be a dictionary")
        for user_id, transcript_id in v.items():
            if not isinstance(user_id, str) or not isinstance(transcript_id, str):
                raise ValueError("Both keys and values must be strings (user_id and transcript_id)")
            if len(user_id) == 0 or len(transcript_id) == 0:
                raise ValueError("user_id and transcript_id cannot be empty")
        return v
