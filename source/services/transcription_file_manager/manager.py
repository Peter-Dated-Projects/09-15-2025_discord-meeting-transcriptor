from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from source.context import Context

from sqlalchemy import delete, insert, select, update

from source.server.sql_models import UserTranscriptsModel
from source.services.manager import BaseTranscriptionFileServiceManager
from source.utils import calculate_file_sha256, generate_16_char_uuid

# -------------------------------------------------------------- #
# Transcription File Manager Service
# -------------------------------------------------------------- #


class TranscriptionFileManagerService(BaseTranscriptionFileServiceManager):
    """Service for managing transcription JSON files and their SQL entries."""

    def __init__(self, context: Context, transcription_storage_path: str):
        super().__init__(context)
        self.transcription_storage_path = transcription_storage_path
        self.storage_path = os.path.join(self.transcription_storage_path, "storage")

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)

        # Run blocking filesystem operations in executor
        loop = asyncio.get_event_loop()

        # Check if folders exist, create if they don't
        if not await loop.run_in_executor(None, os.path.exists, self.transcription_storage_path):
            await loop.run_in_executor(None, os.makedirs, self.transcription_storage_path)
        if not await loop.run_in_executor(None, os.path.exists, self.storage_path):
            await loop.run_in_executor(None, os.makedirs, self.storage_path)

        await self.services.logging_service.info(
            f"TranscriptionFileManagerService initialized with storage path: {self.transcription_storage_path}"
        )
        return True

    async def on_close(self):
        await self.services.logging_service.info("TranscriptionFileManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Transcription File Management Methods
    # -------------------------------------------------------------- #

    def get_storage_path(self) -> str:
        """Get the absolute storage path."""
        return os.path.abspath(self.storage_path)

    def _build_transcript_filename(self, meeting_id: str, user_id: str, transcript_id: str) -> str:
        """Build a standardized filename for a transcript."""
        return f"transcript_{meeting_id}_{user_id}_{transcript_id}.json"

    async def save_transcription(
        self,
        transcript_data: dict[str, Any],
        meeting_id: str,
        user_id: str,
        transcript_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Save transcription JSON data and create a SQL entry.

        Args:
            transcript_data: The transcript JSON data to save
            meeting_id: The meeting ID associated with this transcript
            user_id: The Discord user ID associated with this transcript
            transcript_id: Optional transcript ID (will be generated if not provided)

        Returns:
            Tuple of (transcript_id, filename)

        Raises:
            ValueError: If transcript_data is empty or invalid
            RuntimeError: If file save or SQL insert fails
        """
        if not transcript_data:
            raise ValueError("Transcript data cannot be empty")

        # Generate transcript ID if not provided
        if transcript_id is None:
            transcript_id = generate_16_char_uuid()

        # Build filename
        filename = self._build_transcript_filename(meeting_id, user_id, transcript_id)
        file_path = os.path.join(self.storage_path, filename)

        try:
            # Save JSON file
            loop = asyncio.get_event_loop()

            # Write the JSON file asynchronously
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(json.dumps(transcript_data, indent=2, ensure_ascii=False))

            await self.services.logging_service.info(f"Saved transcription JSON file: {filename}")

            # Calculate SHA256 hash
            sha256_hash = await calculate_file_sha256(file_path)

            # Create SQL entry
            created_at = datetime.now()

            stmt = insert(UserTranscriptsModel).values(
                id=transcript_id,
                created_at=created_at,
                meeting_id=meeting_id,
                user_id=user_id,
                sha256=sha256_hash,
                transcript_filename=filename,
            )
            await self.server.sql_client.execute(stmt)

            await self.services.logging_service.info(
                f"Created SQL entry for transcript: {transcript_id}"
            )

            return transcript_id, filename

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to save transcription {transcript_id}: {str(e)}"
            )
            # Clean up file if SQL insert failed
            if await loop.run_in_executor(None, os.path.exists, file_path):
                await loop.run_in_executor(None, os.remove, file_path)
            raise RuntimeError(f"Failed to save transcription: {str(e)}") from e

    async def retrieve_transcription(self, transcript_id: str) -> dict[str, Any] | None:
        """
        Retrieve a transcription JSON file by transcript ID.

        Args:
            transcript_id: The transcript ID to retrieve

        Returns:
            The transcript JSON data as a dictionary, or None if not found

        Raises:
            RuntimeError: If file read fails
        """
        try:
            # Get the filename from SQL
            stmt = select(UserTranscriptsModel).where(UserTranscriptsModel.id == transcript_id)
            result = await self.server.sql_client.execute(stmt)

            if not result:
                await self.services.logging_service.warning(
                    f"Transcript not found in SQL: {transcript_id}"
                )
                return None

            transcript_model = result[0]
            filename = transcript_model["transcript_filename"]

            # Read the JSON file
            file_path = os.path.join(self.storage_path, filename)

            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.error(f"Transcript file not found: {filename}")
                return None

            async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
                content = await f.read()
                transcript_data = json.loads(content)

            await self.services.logging_service.info(f"Retrieved transcription: {transcript_id}")

            return transcript_data

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to retrieve transcription {transcript_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to retrieve transcription: {str(e)}") from e

    async def delete_transcription(self, transcript_id: str) -> bool:
        """
        Delete a transcription JSON file and its SQL entry.

        Args:
            transcript_id: The transcript ID to delete

        Returns:
            True if deletion was successful, False if transcript was not found

        Raises:
            RuntimeError: If deletion fails
        """
        try:
            # Get the filename from SQL
            stmt = select(UserTranscriptsModel).where(UserTranscriptsModel.id == transcript_id)
            result = await self.server.sql_client.execute(stmt)

            if not result:
                await self.services.logging_service.warning(
                    f"Transcript not found in SQL: {transcript_id}"
                )
                return False

            transcript_model = result[0]
            filename = transcript_model["transcript_filename"]

            # Delete SQL entry
            delete_stmt = delete(UserTranscriptsModel).where(
                UserTranscriptsModel.id == transcript_id
            )
            await self.server.sql_client.execute(delete_stmt)

            await self.services.logging_service.info(
                f"Deleted SQL entry for transcript: {transcript_id}"
            )

            # Delete the JSON file
            file_path = os.path.join(self.storage_path, filename)

            loop = asyncio.get_event_loop()
            if await loop.run_in_executor(None, os.path.exists, file_path):
                await loop.run_in_executor(None, os.remove, file_path)
                await self.services.logging_service.info(f"Deleted transcription file: {filename}")
            else:
                await self.services.logging_service.warning(
                    f"Transcription file not found (already deleted?): {filename}"
                )

            return True

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to delete transcription {transcript_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to delete transcription: {str(e)}") from e

    async def get_transcriptions_by_meeting(self, meeting_id: str) -> list[dict[str, Any]]:
        """
        Get all transcription metadata for a specific meeting.

        Args:
            meeting_id: The meeting ID to query

        Returns:
            List of dictionaries containing transcript metadata (id, user_id, filename, created_at, sha256)
        """
        try:
            stmt = select(UserTranscriptsModel).where(UserTranscriptsModel.meeting_id == meeting_id)
            results = await self.server.sql_client.execute(stmt)

            return [
                {
                    "id": t["id"],
                    "user_id": t["user_id"],
                    "filename": t["transcript_filename"],
                    "created_at": t["created_at"].isoformat() if t["created_at"] else None,
                    "sha256": t["sha256"],
                }
                for t in results
            ]

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to get transcriptions for meeting {meeting_id}: {str(e)}"
            )
            return []

    async def get_transcription_by_user_and_meeting(
        self, meeting_id: str, user_id: str
    ) -> dict[str, Any] | None:
        """
        Get transcription metadata for a specific user in a specific meeting.

        Args:
            meeting_id: The meeting ID to query
            user_id: The user ID to query

        Returns:
            Dictionary containing transcript metadata or None if not found
        """
        try:
            stmt = select(UserTranscriptsModel).where(
                UserTranscriptsModel.meeting_id == meeting_id,
                UserTranscriptsModel.user_id == user_id,
            )
            results = await self.server.sql_client.execute(stmt)

            if not results:
                return None

            transcript = results[0]

            return {
                "id": transcript["id"],
                "user_id": transcript["user_id"],
                "filename": transcript["transcript_filename"],
                "created_at": (
                    transcript["created_at"].isoformat() if transcript["created_at"] else None
                ),
                "sha256": transcript["sha256"],
            }

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to get transcription for user {user_id} in meeting {meeting_id}: {str(e)}"
            )
            return None

    async def transcript_exists(self, transcript_id: str) -> bool:
        """
        Check if a transcript exists in the SQL database.

        Args:
            transcript_id: The transcript ID to check

        Returns:
            True if transcript exists, False otherwise
        """
        try:
            stmt = select(UserTranscriptsModel).where(UserTranscriptsModel.id == transcript_id)
            results = await self.server.sql_client.execute(stmt)
            return len(results) > 0

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to check if transcript exists {transcript_id}: {str(e)}"
            )
            return False
