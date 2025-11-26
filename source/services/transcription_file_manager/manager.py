from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from source.context import Context

from sqlalchemy import delete, insert, select

from source.server.sql_models import UserTranscriptsModel
from source.services.manager import BaseTranscriptionFileServiceManager
from source.utils import calculate_file_sha256, generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Transcription File Manager Service
# -------------------------------------------------------------- #


class TranscriptionFileManagerService(BaseTranscriptionFileServiceManager):
    """Service for managing transcription JSON files and their SQL entries."""

    def __init__(self, context: Context, transcription_storage_path: str):
        super().__init__(context)
        self.transcription_storage_path = transcription_storage_path
        self.storage_path = os.path.join(self.transcription_storage_path, "storage")
        self.compilations_storage_path = os.path.join(
            self.transcription_storage_path, "compilations", "storage"
        )

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
        if not await loop.run_in_executor(None, os.path.exists, self.compilations_storage_path):
            await loop.run_in_executor(None, os.makedirs, self.compilations_storage_path)

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

            async with aiofiles.open(file_path, encoding="utf-8") as f:
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

    async def update_transcription(
        self,
        transcript_id: str,
        transcript_data: dict[str, Any],
    ) -> bool:
        """
        Update an existing transcription JSON file with new data.

        This method uses the file_manager's atomic update operation to safely
        modify the transcript file. It's designed to be used when adding
        summaries, summary_layers, or other metadata to existing transcripts.

        Args:
            transcript_id: The transcript ID to update
            transcript_data: The complete updated transcript data

        Returns:
            True if update was successful, False otherwise

        Raises:
            RuntimeError: If update fails
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
            file_path = os.path.join(self.storage_path, filename)

            # Check if file exists
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.error(f"Transcript file not found: {filename}")
                return False

            # Convert transcript data to JSON and write atomically
            json_content = json.dumps(transcript_data, indent=2, ensure_ascii=False)

            # Write file atomically using aiofiles
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(json_content)

            await self.services.logging_service.info(
                f"Updated transcription file: {filename} ({len(json_content)} bytes)"
            )

            return True

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update transcription {transcript_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to update transcription: {str(e)}") from e

    async def update_transcription_with_summary(
        self,
        transcript_id: str,
        summary: str,
        summary_layers: dict[int, list[str]],
    ) -> bool:
        """
        Update a transcription file with summary data.

        This is a convenience method that loads the transcript, adds summary
        fields, and saves it back using atomic operations.

        Args:
            transcript_id: The transcript ID to update
            summary: The final summary text
            summary_layers: Dictionary of summary layers {level: [summaries]}

        Returns:
            True if update was successful, False otherwise

        Raises:
            RuntimeError: If update fails
        """
        try:
            # Load the existing transcript
            transcript_data = await self.retrieve_transcription(transcript_id)

            if not transcript_data:
                await self.services.logging_service.error(
                    f"Cannot update non-existent transcript: {transcript_id}"
                )
                return False

            # Add summary fields
            transcript_data["summary"] = summary
            transcript_data["summary_layers"] = summary_layers
            transcript_data["summarized_at"] = get_current_timestamp_est().isoformat()

            # Update using atomic operation
            return await self.update_transcription(transcript_id, transcript_data)

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update transcript {transcript_id} with summary: {str(e)}"
            )
            raise RuntimeError(f"Failed to update transcript with summary: {str(e)}") from e

    async def bulk_update_transcriptions_with_summary(
        self,
        transcript_ids: list[str],
        summary: str,
        summary_layers: dict[int, list[str]],
    ) -> dict[str, bool]:
        """
        Update multiple transcription files with the same summary data.

        This method is used by the summarization job manager to update all
        user transcripts from a meeting with the generated summary.

        Args:
            transcript_ids: List of transcript IDs to update
            summary: The final summary text to add to each transcript
            summary_layers: Dictionary of summary layers to add to each transcript

        Returns:
            Dictionary mapping transcript_id to success status (True/False)
        """
        results = {}

        await self.services.logging_service.info(
            f"Bulk updating {len(transcript_ids)} transcripts with summary data"
        )

        for transcript_id in transcript_ids:
            try:
                success = await self.update_transcription_with_summary(
                    transcript_id, summary, summary_layers
                )
                results[transcript_id] = success

                if success:
                    await self.services.logging_service.info(
                        f"Successfully updated transcript {transcript_id} with summary"
                    )
                else:
                    await self.services.logging_service.warning(
                        f"Failed to update transcript {transcript_id} with summary"
                    )

            except Exception as e:
                await self.services.logging_service.error(
                    f"Error updating transcript {transcript_id}: {str(e)}"
                )
                results[transcript_id] = False

        success_count = sum(1 for success in results.values() if success)
        await self.services.logging_service.info(
            f"Bulk update complete: {success_count}/{len(transcript_ids)} successful"
        )

        return results

    # -------------------------------------------------------------- #
    # Compiled Transcript Management Methods
    # -------------------------------------------------------------- #

    def _build_compiled_transcript_filename(self, meeting_id: str) -> str:
        """Build a standardized filename for a compiled transcript."""
        return f"transcript_{meeting_id}.json"

    async def save_compiled_transcription(
        self,
        compiled_data: dict[str, Any],
        meeting_id: str,
    ) -> str:
        """
        Save a compiled transcription JSON file.

        Args:
            compiled_data: The compiled transcript data to save
            meeting_id: The meeting ID associated with this compiled transcript

        Returns:
            The full file path where the compiled transcript was saved

        Raises:
            ValueError: If compiled_data is empty or invalid
            RuntimeError: If file save fails
        """
        if not compiled_data:
            raise ValueError("Compiled transcript data cannot be empty")

        filename = self._build_compiled_transcript_filename(meeting_id)
        file_path = os.path.join(self.compilations_storage_path, filename)

        try:
            # Convert to JSON bytes
            json_content = json.dumps(compiled_data, indent=2, ensure_ascii=False)
            data_bytes = json_content.encode("utf-8")

            # Ensure parent directory exists
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, self.compilations_storage_path):
                await loop.run_in_executor(None, os.makedirs, self.compilations_storage_path)

            # Check if file already exists
            if await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.warning(
                    f"Compiled transcript already exists, will update: {filename}"
                )
                # Use update instead of save
                async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                    await f.write(json_content)
            else:
                # Save new file
                async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                    await f.write(json_content)

            await self.services.logging_service.info(
                f"Saved compiled transcription: {filename} ({len(data_bytes)} bytes)"
            )

            return file_path

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to save compiled transcription for meeting {meeting_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to save compiled transcription: {str(e)}") from e

    async def retrieve_compiled_transcription(self, meeting_id: str) -> dict[str, Any] | None:
        """
        Retrieve a compiled transcription JSON file by meeting ID.

        Args:
            meeting_id: The meeting ID to retrieve

        Returns:
            The compiled transcript JSON data as a dictionary, or None if not found

        Raises:
            RuntimeError: If file read fails
        """
        filename = self._build_compiled_transcript_filename(meeting_id)
        file_path = os.path.join(self.compilations_storage_path, filename)

        try:
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.warning(
                    f"Compiled transcript not found: {filename}"
                )
                return None

            # Read the JSON file
            async with aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()
                compiled_data = json.loads(content)

            await self.services.logging_service.info(
                f"Retrieved compiled transcription for meeting: {meeting_id}"
            )

            return compiled_data

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to retrieve compiled transcription for meeting {meeting_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to retrieve compiled transcription: {str(e)}") from e

    async def update_compiled_transcription(
        self,
        meeting_id: str,
        compiled_data: dict[str, Any],
    ) -> bool:
        """
        Update an existing compiled transcription JSON file with new data.

        This method uses atomic file operations to safely modify the compiled
        transcript. It's designed to be used when adding summaries, summary_layers,
        or other metadata to existing compiled transcripts.

        Args:
            meeting_id: The meeting ID to update
            compiled_data: The complete updated compiled transcript data

        Returns:
            True if update was successful, False otherwise

        Raises:
            RuntimeError: If update fails
        """
        filename = self._build_compiled_transcript_filename(meeting_id)
        file_path = os.path.join(self.compilations_storage_path, filename)

        try:
            # Check if file exists
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.error(
                    f"Compiled transcript file not found: {filename}"
                )
                return False

            # Convert compiled data to JSON bytes
            json_content = json.dumps(compiled_data, indent=2, ensure_ascii=False)
            data_bytes = json_content.encode("utf-8")

            # Write atomically
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(json_content)

            await self.services.logging_service.info(
                f"Updated compiled transcription: {filename} ({len(data_bytes)} bytes)"
            )

            return True

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update compiled transcription for meeting {meeting_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to update compiled transcription: {str(e)}") from e

    async def update_compiled_transcription_with_summary(
        self,
        meeting_id: str,
        summary: str,
        summary_layers: dict[int, list[str]],
    ) -> bool:
        """
        Update a compiled transcription file with summary data.

        This is a convenience method that loads the compiled transcript, adds
        summary fields, and saves it back using atomic operations.

        Args:
            meeting_id: The meeting ID to update
            summary: The final summary text
            summary_layers: Dictionary of summary layers {level: [summaries]}

        Returns:
            True if update was successful, False otherwise

        Raises:
            RuntimeError: If update fails
        """
        try:
            # Load the existing compiled transcript
            compiled_data = await self.retrieve_compiled_transcription(meeting_id)

            if not compiled_data:
                await self.services.logging_service.error(
                    f"Cannot update non-existent compiled transcript for meeting: {meeting_id}"
                )
                return False

            # Add summary fields
            compiled_data["summary"] = summary
            compiled_data["summary_layers"] = summary_layers
            compiled_data["summarized_at"] = get_current_timestamp_est().isoformat()

            # Update using atomic operation
            return await self.update_compiled_transcription(meeting_id, compiled_data)

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update compiled transcript {meeting_id} with summary: {str(e)}"
            )
            raise RuntimeError(
                f"Failed to update compiled transcript with summary: {str(e)}"
            ) from e

    async def delete_compiled_transcription(self, meeting_id: str) -> bool:
        """
        Delete a compiled transcription JSON file.

        Args:
            meeting_id: The meeting ID to delete

        Returns:
            True if deletion was successful, False if transcript was not found

        Raises:
            RuntimeError: If deletion fails
        """
        filename = self._build_compiled_transcript_filename(meeting_id)
        file_path = os.path.join(self.compilations_storage_path, filename)

        try:
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.warning(
                    f"Compiled transcript not found: {filename}"
                )
                return False

            # Delete the file
            await loop.run_in_executor(None, os.remove, file_path)

            await self.services.logging_service.info(f"Deleted compiled transcription: {filename}")

            return True

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to delete compiled transcription for meeting {meeting_id}: {str(e)}"
            )
            raise RuntimeError(f"Failed to delete compiled transcription: {str(e)}") from e
