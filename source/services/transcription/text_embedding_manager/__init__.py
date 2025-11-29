"""
Text Embedding Job Manager Package.

This package contains the job manager for creating text embeddings of compiled transcriptions.
"""

from source.services.transcription.text_embedding_manager.manager import (
    TextEmbeddingJob,
    TextEmbeddingJobManagerService,
)

__all__ = [
    "TextEmbeddingJob",
    "TextEmbeddingJobManagerService",
]
