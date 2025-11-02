from datetime import datetime

from source.server.server import ServerManager
from source.server.sql_models import JobsStatus, JobsStatusModel, JobsType
from source.services.manager import BaseSQLLoggingServiceManager
from source.utils import generate_16_char_uuid

# -------------------------------------------------------------- #
# SQL Logging Manager Service
# -------------------------------------------------------------- #


class SQLLoggingManagerService(BaseSQLLoggingServiceManager):
    """Service for managing SQL logging."""

    def __init__(self, server: ServerManager):
        super().__init__(server)

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
    ):
        """Log an event to the SQL database."""
        log_id = generate_16_char_uuid()

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

        # create event data
        job_status = JobsStatusModel(
            id=log_id,
            type=job_type,
            meeting_id=meeting_id,
            created_at=created_at,
            started_at=None,
            finished_at=None,
            status=status,
            error_log=None,
        )
        await self.server.sql_client.insert(JobsStatusModel.__tablename__, job_status.dict())
        await self.server.logging_service.log(f"Logged job status event: {job_status.dict()}")

    async def fetch_logs(self) -> list:
        """Fetch logs from the SQL database."""
        # Implement SQL fetching logic here
        return []
