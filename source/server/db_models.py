from pydantic import RootModel, field_validator

from source.server.sql_models import (
    CompiledTranscriptsModel,
    GuildAdminWhitelistModel,
    JobsStatusErrorLogModel,
    JobsStatusModel,
    MeetingModel,
    RecordingModel,
    TempRecordingModel,
    UserTranscriptsModel,
    ConversationsModel,
    SubscriptionsModel,
)

# -------------------------------------------------------------- #
# SQL DB Models
# -------------------------------------------------------------- #

SQL_DATABASE_MODELS = [
    MeetingModel,
    RecordingModel,
    JobsStatusModel,
    UserTranscriptsModel,
    CompiledTranscriptsModel,
    GuildAdminWhitelistModel,
    JobsStatusErrorLogModel,
    TempRecordingModel,
    ConversationsModel,
    SubscriptionsModel,
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


class TranscriptIdsMapping(RootModel[dict]):
    """
    Represents the structure:
    {
        "meeting_summary": "{meeting_summary_file_path}",
        "users": [
            {"user_id": "{transcript_id}"}, ...
        ]
    }
    where meeting_summary is the path to the meeting summary file,
    and users is an array of objects mapping user_id to transcript_id
    """

    root: dict  # New format with meeting_summary and users array

    @field_validator("root")
    def validate_format(cls, v: dict) -> dict:
        if not isinstance(v, dict):
            raise ValueError("Must be a dictionary")

        # Validate meeting_summary field
        if "meeting_summary" not in v:
            raise ValueError("Must contain 'meeting_summary' key")
        if not isinstance(v["meeting_summary"], str):
            raise ValueError("'meeting_summary' must be a string (file path)")

        # Validate users array
        if "users" not in v:
            raise ValueError("Must contain 'users' key")
        if not isinstance(v["users"], list):
            raise ValueError("'users' value must be a list")

        for user_entry in v["users"]:
            if not isinstance(user_entry, dict):
                raise ValueError("Each user entry must be a dictionary")
            if len(user_entry) != 1:
                raise ValueError("Each user entry must have exactly one key-value pair")

            # Validate user_id: transcript_id mapping
            for user_id, transcript_id in user_entry.items():
                if not isinstance(user_id, str) or not isinstance(transcript_id, str):
                    raise ValueError("Both user_id and transcript_id must be strings")
                if len(user_id) == 0 or len(transcript_id) == 0:
                    raise ValueError("user_id and transcript_id cannot be empty")

        return v


class ParticipantsMapping(RootModel[dict[str, list[str]]]):
    """
    Represents the structure: {users: [user_id1, user_id2, ...]}
    where users is the key and the value is a list of Discord User IDs (strings)
    """

    root: dict[str, list[str]]  # {users: [user_ids]}

    @field_validator("root")
    def validate_format(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if not isinstance(v, dict):
            raise ValueError("Must be a dictionary")
        if "users" not in v:
            raise ValueError("Must contain 'users' key")
        if not isinstance(v["users"], list):
            raise ValueError("'users' value must be a list")
        for user_id in v["users"]:
            if not isinstance(user_id, str):
                raise ValueError("All user IDs must be strings")
            if len(user_id) == 0:
                raise ValueError("User IDs cannot be empty")
        return v
