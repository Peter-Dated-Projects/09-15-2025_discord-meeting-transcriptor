"""
Ollama Request Manager.

This service provides a comprehensive wrapper around the Ollama API with:
- Full chat history management
- Configurable generation parameters
- Streaming and non-streaming support
- Session/conversation tracking
- Retry logic with exponential backoff
- JSON output mode support
- Keep-alive model management
- Request metadata and logging
- Future-proof hooks for RAG and function-calling

Usage:
    # Simple query
    response = await ollama_manager.query(
        model="llama2",
        messages=[{"role": "user", "content": "Hello!"}]
    )

    # Streaming query
    async for chunk in ollama_manager.query(
        model="llama2",
        messages=[{"role": "user", "content": "Tell me a story"}],
        stream=True
    ):
        print(chunk, end="")

    # JSON output mode
    response = await ollama_manager.query(
        model="llama2",
        messages=[{"role": "user", "content": "Give me a JSON object"}],
        format="json"
    )
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

import ollama

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.services.manager import Manager
from source.services.ollama_request_manager.conversation import ConversationHistory


# -------------------------------------------------------------- #
# Data Models
# -------------------------------------------------------------- #


@dataclass
class Message:
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class GenerationConfig:
    """Configuration for text generation parameters."""

    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    num_predict: int | None = None  # max tokens to generate
    stop: list[str] = field(default_factory=list)
    repeat_penalty: float = 1.1
    seed: int | None = None  # for reproducibility


@dataclass
class OllamaQueryInput:
    """Input parameters for Ollama query."""

    model: str
    messages: list[Message] | list[dict[str, str]]
    system_prompt: str | None = None
    generation_config: GenerationConfig = field(default_factory=GenerationConfig)
    format: Literal["text", "json"] | None = None
    stream: bool = False
    keep_alive: str | int = "5m"  # e.g., "5m", 0, -1
    session_id: str | None = None
    timeout_ms: int = 120000  # 2 minutes default
    max_retries: int = 3
    retry_backoff: float = 1.0  # exponential backoff multiplier
    metadata: dict[str, Any] = field(default_factory=dict)
    # Future extensibility
    tools: list[dict] | None = None
    tool_choice: str | None = None
    extra_context: str | None = None
    documents: list[str] | None = None


@dataclass
class OllamaQueryResult:
    """Result from Ollama query."""

    content: str
    model: str
    done: bool
    total_duration: int | None = None  # nanoseconds
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# -------------------------------------------------------------- #
# Ollama Request Manager
# -------------------------------------------------------------- #


class OllamaRequestManager(Manager):
    """
    Manager for Ollama API requests with full configuration support.

    This manager provides a comprehensive wrapper around Ollama with:
    - Session-based conversation history
    - Configurable generation parameters
    - Streaming and non-streaming modes
    - Automatic retry with exponential backoff
    - Request metadata and logging
    """

    def __init__(
        self,
        context: Context,
        host: str | None = None,
        default_model: str | None = None,
        default_system_prompt: str | None = None,
        max_history_length: int = 50,
        max_history_tokens: int | None = None,
    ):
        """
        Initialize the Ollama request manager.

        Args:
            context: Application context
            host: Ollama server host URL (defaults to env: OLLAMA_HOST + OLLAMA_PORT)
            default_model: Default model to use for queries (defaults to env: OLLAMA_MODEL)
            default_system_prompt: Default system prompt for all queries
            max_history_length: Maximum number of messages to keep in history
            max_history_tokens: Maximum total tokens in history (if set)
        """
        super().__init__(context)

        # Get configuration from environment variables
        ollama_host = os.environ.get("OLLAMA_HOST", "localhost")
        ollama_port = os.environ.get("OLLAMA_PORT", "11434")
        ollama_model = os.environ.get("OLLAMA_MODEL", "llama2")

        # Build host URL if not provided
        if host is None:
            host = f"http://{ollama_host}:{ollama_port}"

        # Use env model if not provided
        if default_model is None:
            default_model = ollama_model

        # Ollama client
        self._client = ollama.AsyncClient(host=host)
        self._host = host

        # Default configuration
        self._default_model = default_model
        self._default_system_prompt = default_system_prompt
        self._max_history_length = max_history_length
        self._max_history_tokens = max_history_tokens

        # Session management
        self._sessions: dict[str, ConversationHistory] = {}

        # Statistics
        self._total_requests = 0
        self._total_tokens_generated = 0
        self._total_errors = 0
        self._model_usage: dict[str, int] = {}

    # -------------------------------------------------------------- #
    # Manager Lifecycle
    # -------------------------------------------------------------- #

    async def on_start(self, services: ServicesManager) -> None:
        """Actions to perform on manager start."""
        await super().on_start(services)
        if self.services:
            await self.services.logging_service.info(
                f"Ollama Request Manager started (host: {self._host})"
            )

    async def on_close(self) -> None:
        """Actions to perform on manager shutdown."""
        # Clear all sessions
        self._sessions.clear()
        if self.services:
            await self.services.logging_service.info("Ollama Request Manager stopped")
            await self.services.logging_service.info(
                f"Total requests: {self._total_requests}, "
                f"Total tokens: {self._total_tokens_generated}, "
                f"Total errors: {self._total_errors}"
            )

    # -------------------------------------------------------------- #
    # Main Query Interface
    # -------------------------------------------------------------- #

    async def query(
        self,
        model: str | None = None,
        messages: list[Message] | list[dict[str, str]] | None = None,
        prompt: str | None = None,  # Shortcut for single user message
        system_prompt: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        num_predict: int | None = None,
        stop: list[str] | None = None,
        repeat_penalty: float | None = None,
        seed: int | None = None,
        format: Literal["text", "json"] | None = None,
        stream: bool = False,
        keep_alive: str | int = "5m",
        session_id: str | None = None,
        timeout_ms: int = 120000,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        metadata: dict[str, Any] | None = None,
        # Future extensibility
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        extra_context: str | None = None,
        documents: list[str] | None = None,
    ) -> OllamaQueryResult | AsyncIterator[str]:
        """
        Execute an Ollama query with full configuration support.

        Args:
            model: Model name (uses default if not provided)
            messages: Full chat history or None to use session history
            prompt: Shortcut for single user message (alternative to messages)
            system_prompt: System prompt (overrides default)
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            num_predict: Maximum tokens to generate
            stop: Stop sequences
            repeat_penalty: Repetition penalty
            seed: Random seed for reproducibility
            format: Output format ("text" or "json")
            stream: Enable streaming mode
            keep_alive: Model keep-alive duration
            session_id: Session ID for conversation tracking
            timeout_ms: Request timeout in milliseconds
            max_retries: Maximum retry attempts
            retry_backoff: Exponential backoff multiplier
            metadata: Additional metadata for logging
            tools: Tool definitions (future use)
            tool_choice: Tool selection strategy (future use)
            extra_context: Additional context (for RAG)
            documents: Document list (for RAG)

        Returns:
            OllamaQueryResult or AsyncIterator[str] if streaming
        """
        # Use default model if not specified
        model = model or self._default_model

        # Build generation config
        gen_config = GenerationConfig(
            temperature=temperature if temperature is not None else 0.7,
            top_p=top_p if top_p is not None else 0.9,
            top_k=top_k if top_k is not None else 40,
            num_predict=num_predict,
            stop=stop or [],
            repeat_penalty=repeat_penalty if repeat_penalty is not None else 1.1,
            seed=seed,
        )

        # Handle prompt shortcut
        if prompt and not messages:
            messages = [Message(role="user", content=prompt)]

        # Convert dict messages to Message objects
        if messages and isinstance(messages[0], dict):
            messages = [Message(role=m["role"], content=m["content"]) for m in messages]

        # Get or create session
        if session_id:
            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationHistory(
                    session_id=session_id,
                    max_length=self._max_history_length,
                    max_tokens=self._max_history_tokens,
                )
            session = self._sessions[session_id]

            # Add new messages to session history
            if messages:
                for msg in messages:
                    if msg.role == "user":
                        session.add_user_message(msg.content)
                    elif msg.role == "assistant":
                        session.add_assistant_message(msg.content)

            # Use session history for query
            messages = [Message(role=m["role"], content=m["content"]) for m in session.get_messages()]
        elif not messages:
            # No session and no messages provided
            raise ValueError("Either messages or session_id must be provided")

        # Build query input
        query_input = OllamaQueryInput(
            model=model,
            messages=messages,
            system_prompt=system_prompt or self._default_system_prompt,
            generation_config=gen_config,
            format=format,
            stream=stream,
            keep_alive=keep_alive,
            session_id=session_id,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            metadata=metadata or {},
            tools=tools,
            tool_choice=tool_choice,
            extra_context=extra_context,
            documents=documents,
        )

        # Execute query
        if stream:
            return self._query_stream(query_input)
        else:
            return await self._query_once(query_input)

    # -------------------------------------------------------------- #
    # Internal Query Methods
    # -------------------------------------------------------------- #

    async def _query_once(self, query_input: OllamaQueryInput) -> OllamaQueryResult:
        """Execute a single non-streaming query with retry logic."""
        start_time = time.time()
        last_error = None

        # Track request
        self._total_requests += 1
        self._model_usage[query_input.model] = self._model_usage.get(query_input.model, 0) + 1

        for attempt in range(query_input.max_retries):
            try:
                # Build Ollama request
                request_params = self._build_request_params(query_input)

                # Execute request with timeout
                response = await asyncio.wait_for(
                    self._client.chat(**request_params), timeout=query_input.timeout_ms / 1000
                )

                # Extract result
                content = response.get("message", {}).get("content", "")

                # Update session if applicable
                if query_input.session_id and query_input.session_id in self._sessions:
                    self._sessions[query_input.session_id].add_assistant_message(content)

                # Track statistics
                eval_count = response.get("eval_count", 0)
                self._total_tokens_generated += eval_count

                # Log success
                duration_ms = (time.time() - start_time) * 1000
                if self.services:
                    await self.services.logging_service.debug(
                        f"Ollama query completed: model={query_input.model}, "
                        f"tokens={eval_count}, duration={duration_ms:.0f}ms"
                    )

                return OllamaQueryResult(
                    content=content,
                    model=response.get("model", query_input.model),
                    done=response.get("done", True),
                    total_duration=response.get("total_duration"),
                    load_duration=response.get("load_duration"),
                    prompt_eval_count=response.get("prompt_eval_count"),
                    prompt_eval_duration=response.get("prompt_eval_duration"),
                    eval_count=response.get("eval_count"),
                    eval_duration=response.get("eval_duration"),
                    metadata=query_input.metadata,
                )

            except asyncio.TimeoutError as e:
                last_error = e
                if self.services:
                    await self.services.logging_service.warning(
                        f"Ollama query timeout (attempt {attempt + 1}/{query_input.max_retries})"
                    )

            except Exception as e:
                last_error = e
                if self.services:
                    await self.services.logging_service.warning(
                        f"Ollama query error (attempt {attempt + 1}/{query_input.max_retries}): {e}"
                    )

            # Exponential backoff
            if attempt < query_input.max_retries - 1:
                backoff_time = query_input.retry_backoff * (2**attempt)
                await asyncio.sleep(backoff_time)

        # All retries failed
        self._total_errors += 1
        if self.services:
            await self.services.logging_service.error(
                f"Ollama query failed after {query_input.max_retries} attempts: {last_error}"
            )
        raise RuntimeError(f"Ollama query failed after {query_input.max_retries} attempts") from last_error

    async def _query_stream(self, query_input: OllamaQueryInput) -> AsyncIterator[str]:
        """Execute a streaming query."""
        # Track request
        self._total_requests += 1
        self._model_usage[query_input.model] = self._model_usage.get(query_input.model, 0) + 1

        try:
            # Build Ollama request
            request_params = self._build_request_params(query_input)

            # Execute streaming request
            full_content = ""
            async for chunk in await self._client.chat(**request_params):
                content = chunk.get("message", {}).get("content", "")
                full_content += content
                yield content

            # Update session with full response
            if query_input.session_id and query_input.session_id in self._sessions:
                self._sessions[query_input.session_id].add_assistant_message(full_content)

            # Update token count (approximate from length)
            self._total_tokens_generated += len(full_content.split())

        except Exception as e:
            self._total_errors += 1
            if self.services:
                await self.services.logging_service.error(f"Ollama streaming query error: {e}")
            raise

    def _build_request_params(self, query_input: OllamaQueryInput) -> dict[str, Any]:
        """Build Ollama API request parameters."""
        # Convert messages to dict format
        messages = []

        # Add system prompt if provided
        if query_input.system_prompt:
            messages.append({"role": "system", "content": query_input.system_prompt})

        # Add conversation messages
        for msg in query_input.messages:
            if isinstance(msg, Message):
                messages.append({"role": msg.role, "content": msg.content})
            else:
                messages.append(msg)

        # Add RAG context if provided
        if query_input.extra_context or query_input.documents:
            context_parts = []
            if query_input.extra_context:
                context_parts.append(query_input.extra_context)
            if query_input.documents:
                context_parts.extend(query_input.documents)
            context_message = "\n\n".join(context_parts)
            # Insert context before last user message
            if messages and messages[-1]["role"] == "user":
                messages.insert(-1, {"role": "system", "content": f"Context:\n{context_message}"})

        # Build options
        options = {
            "temperature": query_input.generation_config.temperature,
            "top_p": query_input.generation_config.top_p,
            "top_k": query_input.generation_config.top_k,
            "repeat_penalty": query_input.generation_config.repeat_penalty,
        }

        if query_input.generation_config.num_predict:
            options["num_predict"] = query_input.generation_config.num_predict

        if query_input.generation_config.seed:
            options["seed"] = query_input.generation_config.seed

        if query_input.generation_config.stop:
            options["stop"] = query_input.generation_config.stop

        # Build request
        params = {
            "model": query_input.model,
            "messages": messages,
            "options": options,
            "stream": query_input.stream,
            "keep_alive": query_input.keep_alive,
        }

        if query_input.format:
            params["format"] = query_input.format

        return params

    # -------------------------------------------------------------- #
    # Session Management
    # -------------------------------------------------------------- #

    def get_session(self, session_id: str) -> ConversationHistory | None:
        """Get a conversation session by ID."""
        return self._sessions.get(session_id)

    def create_session(self, session_id: str) -> ConversationHistory:
        """Create a new conversation session."""
        if session_id in self._sessions:
            raise ValueError(f"Session {session_id} already exists")

        session = ConversationHistory(
            session_id=session_id,
            max_length=self._max_history_length,
            max_tokens=self._max_history_tokens,
        )
        self._sessions[session_id] = session
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a conversation session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def clear_all_sessions(self) -> None:
        """Clear all conversation sessions."""
        self._sessions.clear()

    # -------------------------------------------------------------- #
    # Utility Methods
    # -------------------------------------------------------------- #

    def get_statistics(self) -> dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_requests": self._total_requests,
            "total_tokens_generated": self._total_tokens_generated,
            "total_errors": self._total_errors,
            "model_usage": self._model_usage.copy(),
            "active_sessions": len(self._sessions),
        }

    async def list_models(self) -> list[dict[str, Any]]:
        """List available models from Ollama."""
        try:
            response = await self._client.list()
            return response.get("models", [])
        except Exception as e:
            if self.services:
                await self.services.logging_service.error(f"Failed to list models: {e}")
            return []

    async def pull_model(self, model: str) -> bool:
        """Pull a model from Ollama registry."""
        try:
            await self._client.pull(model)
            if self.services:
                await self.services.logging_service.info(f"Successfully pulled model: {model}")
            return True
        except Exception as e:
            if self.services:
                await self.services.logging_service.error(f"Failed to pull model {model}: {e}")
            return False
