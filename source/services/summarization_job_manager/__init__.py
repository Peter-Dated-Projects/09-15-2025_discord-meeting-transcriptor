"""
Summarization Job Manager Package.

This package contains the job manager for creating summaries of compiled transcriptions.
"""

from source.services.summarization_job_manager.manager import (
    SummarizationJob,
    SummarizationJobManagerService,
)

__all__ = [
    "SummarizationJob",
    "SummarizationJobManagerService",
]
