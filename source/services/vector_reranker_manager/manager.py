"""
Vector Reranker Manager.

This service handles reranking of retrieved embeddings using a cross-encoder model.
The reranker takes a query and a list of candidate documents and re-scores them
to improve relevance ranking.

Usage:
    async with services.gpu_resource_manager.acquire_lock(job_type="vector_reranker"):
        results = await reranker_manager.rerank(query, candidates, top_k=10)
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from source.context import Context

from source.services.manager import Manager


class VectorRerankerManager(Manager):
    """
    Manager for vector reranking operations using cross-encoder models.

    This manager loads a cross-encoder model on-demand and provides
    reranking functionality for improving retrieval results.
    """

    def __init__(self, context: Context):
        """
        Initialize the Vector Reranker Manager.

        Args:
            context: Application context
        """
        super().__init__(context)
        self._model = None
        self._model_name = "BAAI/bge-reranker-v2-m3"

    async def on_start(self, services) -> None:
        """Actions to perform on manager start."""
        await super().on_start(services)
        if self.services:
            await self.services.logging_service.info("Vector Reranker Manager started")

    async def on_close(self) -> None:
        """Actions to perform on manager shutdown."""
        await self._offload_model()
        if self.services:
            await self.services.logging_service.info("Vector Reranker Manager stopped")

    def _load_model(self) -> None:
        """Load the cross-encoder model."""
        if self._model is not None:
            return  # Already loaded

        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)

            if self.services:
                import asyncio

                asyncio.create_task(
                    self.services.logging_service.info(
                        f"Loaded cross-encoder model: {self._model_name}"
                    )
                )
        except Exception as e:
            if self.services:
                import asyncio

                asyncio.create_task(
                    self.services.logging_service.error(
                        f"Failed to load cross-encoder model: {type(e).__name__}: {str(e)}"
                    )
                )
            raise

    async def _offload_model(self) -> None:
        """Offload the model from memory to free up GPU resources."""
        if self._model is None:
            return

        try:
            import torch

            # Move to CPU if using GPU
            if hasattr(self._model, "to"):
                try:
                    self._model.to("cpu")
                except Exception:
                    pass

            # Drop reference
            self._model = None

            # Garbage collection
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            if self.services:
                await self.services.logging_service.info("Offloaded cross-encoder model")

        except ImportError:
            # torch not available, just drop reference
            self._model = None
            gc.collect()
        except Exception as e:
            if self.services:
                await self.services.logging_service.error(
                    f"Error offloading model: {type(e).__name__}: {str(e)}"
                )

    def is_model_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self._model is not None

    async def rerank(
        self, query: str, candidates: list[str] | list[list[str]], top_k: int = 10
    ) -> list[str]:
        """
        Rerank a list of candidate documents based on their relevance to the query.

        TODO: Improve this implementation with:
        - Batch processing for large candidate lists
        - Caching mechanism for repeated queries
        - Better error handling and fallback strategies
        - Model warmup/preloading options
        - Support for different reranker models
        - Score threshold filtering

        Args:
            query: The search query string
            candidates: List of candidate documents to rerank. Can be a flat list
                       or nested list (e.g., from ChromaDB results)
            top_k: Number of top results to return (default: 10)

        Returns:
            List of reranked documents, ordered by relevance (most relevant first)

        Raises:
            ValueError: If model is not loaded or candidates are empty
        """
        # Handle both flat lists and nested lists from ChromaDB
        if candidates and isinstance(candidates[0], list):
            candidates = candidates[0]

        if not candidates:
            if self.services:
                await self.services.logging_service.warning("Empty candidates list for reranking")
            return []

        # Load model if not already loaded
        if not self.is_model_loaded():
            self._load_model()

        if self._model is None:
            raise ValueError("Failed to load reranker model")

        try:
            # Create query-document pairs
            pairs = [(query, candidate) for candidate in candidates]

            # Get scores from the model (synchronous operation)
            scores = self._model.predict(pairs)

            # Sort candidates by score (descending)
            ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

            # Return top_k results
            results = [doc for doc, _ in ranked[:top_k]]

            if self.services:
                await self.services.logging_service.info(
                    f"Reranked {len(candidates)} candidates, returning top {len(results)}"
                )

            return results

        except Exception as e:
            if self.services:
                await self.services.logging_service.error(
                    f"Error during reranking: {type(e).__name__}: {str(e)}"
                )
            # On error, return original candidates (unranked)
            return candidates[:top_k]

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of the reranker manager.

        Returns:
            Dictionary with status information
        """
        return {
            "model_loaded": self.is_model_loaded(),
            "model_name": self._model_name,
        }
