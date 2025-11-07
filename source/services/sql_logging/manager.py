from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import JobsStatus, JobsStatusModel, JobsType
from source.services.manager import BaseSQLLoggingServiceManager

# -------------------------------------------------------------- #
# SQL Logging Manager Service
# -------------------------------------------------------------- #


class SQLLoggingManagerService(BaseSQLLoggingServiceManager):
    """Service for managing SQL logging."""

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("SQLLoggingManagerService initialized")
        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # SQL Logging Methods
    # -------------------------------------------------------------- #

    async def log_job_status_event(
        self,
        job_type: JobsType,
        job_id: str,
        meeting_id: str,
        created_at: datetime,
        status: JobsStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_log: str | None = None,
    ):
        """
        Log or update a job status event in the SQL database.

        This method will:
        - INSERT a new row if the job_id doesn't exist yet
        - UPDATE the existing row if the job_id already exists

        This ensures we maintain a single row per job and track its progress from
        PENDING -> IN_PROGRESS -> COMPLETED/FAILED, updating timestamps along the way.

        Args:
            job_type: Type of job (TEMP_TRANSCODING, TRANSCODING, TRANSCRIBING, CLEANING)
            job_id: Unique 16-character job identifier (used as primary key)
            meeting_id: Associated meeting ID
            created_at: When the job was created
            status: Current job status
            started_at: When the job started (set when status = IN_PROGRESS)
            finished_at: When the job finished (set when status = COMPLETED/FAILED)
            error_log: Error log ID if job failed
        """
        # type checking
        if job_type is None or job_id is None or meeting_id is None:
            raise ValueError("job_id, job_type, and meeting_id cannot be None")
        if status is None or created_at is None:
            raise ValueError("status and created_at cannot be None")

        if len(job_id) != 16:
            raise ValueError("job_id must be 16 characters long")
        if len(meeting_id) != 16:
            raise ValueError("meeting_id must be 16 characters long")
        if not isinstance(status, JobsStatus):
            raise ValueError("status must be a valid JobsStatus enum value")
        if not isinstance(job_type, JobsType):
            raise ValueError("job_type must be a valid JobsType enum value")

        # Check if job already exists
        stmt = select(JobsStatusModel).where(JobsStatusModel.id == job_id)
        existing_jobs = await self.server.sql_client.execute(stmt)

        if existing_jobs:
            # UPDATE existing job
            existing_job = existing_jobs[0]

            # Preserve timestamps that shouldn't change
            if started_at is None and "started_at" in existing_job:
                started_at = existing_job["started_at"]
            if finished_at is None and "finished_at" in existing_job:
                finished_at = existing_job["finished_at"]
            if error_log is None and "error_log" in existing_job:
                error_log = existing_job["error_log"]

            # UPDATE the row
            update_stmt = (
                update(JobsStatusModel)
                .where(JobsStatusModel.id == job_id)
                .values(
                    status=status.value,  # Use the enum value string
                    started_at=started_at,
                    finished_at=finished_at,
                    error_log=error_log,
                )
            )
            await self.server.sql_client.execute(update_stmt)
            await self.services.logging_service.log(
                f"Updated job status: job_id={job_id}, status={status.value}, "
                f"started_at={started_at}, finished_at={finished_at}"
            )
        else:
            # INSERT new job
            job_data = {
                "id": job_id,  # Use job_id as the primary key
                "type": job_type.value,  # Use the enum value string
                "meeting_id": meeting_id,
                "created_at": created_at,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status.value,  # Use the enum value string
                "error_log": error_log,
            }

            # Build and execute insert statement
            stmt = insert(JobsStatusModel).values(**job_data)
            await self.server.sql_client.execute(stmt)
            await self.services.logging_service.log(
                f"Inserted new job status: job_id={job_id}, type={job_type.value}, "
                f"status={status.value}, meeting_id={meeting_id}"
            )

    async def fetch_logs(self) -> list:
        """Fetch logs from the SQL database."""
        # Implement SQL fetching logic here
        return []
