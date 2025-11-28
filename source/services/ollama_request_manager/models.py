"""
Message and Conversation Models.

This module defines the core data models for stateful conversations:
- Message: Individual messages with full metadata and observability
- Conversation: Conversation metadata and tracking
- MessageChunk: Streaming message chunks
- Document: Attachments/documents with type-based handling for Ollama

These models support:
- Full LangChain integration
- RAG context tracking
- Tool/function calling metadata
- Observability (tokens, latency, tracing)
- Threading and parent-child relationships
- Document/attachment management for Ollama API
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Any

Role = Literal["system", "user", "assistant", "tool"]


# -------------------------------------------------------------- #
# Document Management System
# -------------------------------------------------------------- #


class DocumentType(Enum):
    """
    Type of document for Ollama processing.

    Determines how the document is handled when building Ollama requests:
    - TEXT: Injected into message content (e.g., .txt, .md, .json files)
    - IMAGE: Base64 encoded and added to 'images' field (vision models)
    - RAG: Injected as context into the prompt (retrieved documents)
    """

    TEXT = "text"  # Text files injected into content
    IMAGE = "image"  # Images base64 encoded for vision models
    RAG = "rag"  # RAG context injected into prompt


@dataclass
class Document:
    """
    A document/attachment for Ollama processing.

    This provides a unified interface for handling different types of
    attachments (text files, images, RAG context) and preparing them
    for the Ollama API.

    Ollama API Contract:
    - TEXT/RAG: Merged into message 'content' (no separate documents field)
    - IMAGE: Base64 encoded and placed in 'images' field (vision model required)
    """

    id: str
    doc_type: DocumentType
    name: str  # Display name or filename

    # Content (one of these should be set based on type)
    content: str | None = None  # For TEXT/RAG: the text content
    file_path: str | None = None  # For IMAGE/TEXT: path to file
    base64_data: str | None = None  # For IMAGE: pre-encoded base64

    # Metadata
    source_url: str | None = None  # Original URL if downloaded
    mime_type: str | None = None  # MIME type if known
    size_bytes: int | None = None  # File size if known
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        name: str,
        content: str,
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> Document:
        """Create a text document from string content."""
        return cls(
            id=str(uuid.uuid4()),
            doc_type=DocumentType.TEXT,
            name=name,
            content=content,
            source_url=source_url,
            metadata=metadata or {},
        )

    @classmethod
    def from_text_file(
        cls,
        file_path: str,
        name: str | None = None,
        encoding: str = "utf-8",
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> Document | None:
        """
        Create a text document from a file.

        Returns None if file cannot be read.
        """
        path = Path(file_path)
        if not path.exists():
            return None

        try:
            content = path.read_text(encoding=encoding)
        except Exception:
            # Try fallback encoding
            try:
                content = path.read_text(encoding="latin-1")
            except Exception:
                return None

        return cls(
            id=str(uuid.uuid4()),
            doc_type=DocumentType.TEXT,
            name=name or path.name,
            content=content,
            file_path=file_path,
            source_url=source_url,
            size_bytes=path.stat().st_size,
            metadata=metadata or {},
        )

    @classmethod
    def from_image_file(
        cls,
        file_path: str,
        name: str | None = None,
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> Document | None:
        """
        Create an image document from a file.

        The image will be base64 encoded for Ollama vision models.
        Returns None if file cannot be read.
        """
        path = Path(file_path)
        if not path.exists():
            return None

        try:
            data = path.read_bytes()
            base64_data = base64.b64encode(data).decode("utf-8")
        except Exception:
            return None

        # Determine MIME type from extension
        ext = path.suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }

        return cls(
            id=str(uuid.uuid4()),
            doc_type=DocumentType.IMAGE,
            name=name or path.name,
            file_path=file_path,
            base64_data=base64_data,
            source_url=source_url,
            mime_type=mime_types.get(ext, "image/unknown"),
            size_bytes=path.stat().st_size,
            metadata=metadata or {},
        )

    @classmethod
    def from_image_bytes(
        cls,
        data: bytes,
        name: str,
        mime_type: str = "image/png",
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> Document:
        """Create an image document from raw bytes."""
        base64_data = base64.b64encode(data).decode("utf-8")

        return cls(
            id=str(uuid.uuid4()),
            doc_type=DocumentType.IMAGE,
            name=name,
            base64_data=base64_data,
            source_url=source_url,
            mime_type=mime_type,
            size_bytes=len(data),
            metadata=metadata or {},
        )

    @classmethod
    def from_rag_context(
        cls,
        name: str,
        content: str,
        source: str | None = None,
        relevance_score: float | None = None,
        metadata: dict | None = None,
    ) -> Document:
        """
        Create a RAG context document.

        Used for retrieved documents that should be injected as context.
        """
        meta = metadata or {}
        if relevance_score is not None:
            meta["relevance_score"] = relevance_score
        if source:
            meta["source"] = source

        return cls(
            id=str(uuid.uuid4()),
            doc_type=DocumentType.RAG,
            name=name,
            content=content,
            metadata=meta,
        )

    def get_text_content(self) -> str | None:
        """Get text content for TEXT/RAG documents."""
        if self.doc_type in (DocumentType.TEXT, DocumentType.RAG):
            return self.content
        return None

    def get_base64_image(self) -> str | None:
        """Get base64 encoded image data for IMAGE documents."""
        if self.doc_type == DocumentType.IMAGE:
            return self.base64_data
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "doc_type": self.doc_type.value,
            "name": self.name,
            "content": self.content,
            "file_path": self.file_path,
            "base64_data": self.base64_data,
            "source_url": self.source_url,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Document:
        """Create Document from dictionary."""
        return cls(
            id=data["id"],
            doc_type=DocumentType(data["doc_type"]),
            name=data["name"],
            content=data.get("content"),
            file_path=data.get("file_path"),
            base64_data=data.get("base64_data"),
            source_url=data.get("source_url"),
            mime_type=data.get("mime_type"),
            size_bytes=data.get("size_bytes"),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        return f"Document(id={self.id[:8]}..., type={self.doc_type.value}, name={self.name})"


@dataclass
class DocumentCollection:
    """
    A collection of documents for Ollama processing.

    Provides utilities for managing multiple documents and preparing
    them for Ollama API requests.
    """

    documents: list[Document] = field(default_factory=list)

    def add(self, document: Document) -> None:
        """Add a document to the collection."""
        self.documents.append(document)

    def add_text(
        self,
        name: str,
        content: str,
        source_url: str | None = None,
    ) -> Document:
        """Add a text document and return it."""
        doc = Document.from_text(name, content, source_url)
        self.documents.append(doc)
        return doc

    def add_text_file(
        self,
        file_path: str,
        name: str | None = None,
    ) -> Document | None:
        """Add a text document from file and return it."""
        doc = Document.from_text_file(file_path, name)
        if doc:
            self.documents.append(doc)
        return doc

    def add_image_file(
        self,
        file_path: str,
        name: str | None = None,
    ) -> Document | None:
        """Add an image document from file and return it."""
        doc = Document.from_image_file(file_path, name)
        if doc:
            self.documents.append(doc)
        return doc

    def add_rag_context(
        self,
        name: str,
        content: str,
        source: str | None = None,
        relevance_score: float | None = None,
    ) -> Document:
        """Add a RAG context document and return it."""
        doc = Document.from_rag_context(name, content, source, relevance_score)
        self.documents.append(doc)
        return doc

    def get_by_type(self, doc_type: DocumentType) -> list[Document]:
        """Get all documents of a specific type."""
        return [d for d in self.documents if d.doc_type == doc_type]

    def get_text_documents(self) -> list[Document]:
        """Get all TEXT type documents."""
        return self.get_by_type(DocumentType.TEXT)

    def get_image_documents(self) -> list[Document]:
        """Get all IMAGE type documents."""
        return self.get_by_type(DocumentType.IMAGE)

    def get_rag_documents(self) -> list[Document]:
        """Get all RAG type documents."""
        return self.get_by_type(DocumentType.RAG)

    def build_text_block(self) -> str:
        """
        Build a formatted text block from all TEXT documents.

        Returns formatted string for injection into message content.
        """
        text_docs = self.get_text_documents()
        if not text_docs:
            return ""

        blocks = []
        for doc in text_docs:
            content = doc.get_text_content()
            if content:
                blocks.append(f"### {doc.name}\n{content}")

        return "\n\n".join(blocks)

    def build_rag_context(self) -> str:
        """
        Build a formatted RAG context block.

        Returns formatted string for injection into message content.
        """
        rag_docs = self.get_rag_documents()
        if not rag_docs:
            return ""

        blocks = []
        for doc in rag_docs:
            content = doc.get_text_content()
            if content:
                source = doc.metadata.get("source", doc.name)
                score = doc.metadata.get("relevance_score")
                header = f"### {source}"
                if score is not None:
                    header += f" (relevance: {score:.2f})"
                blocks.append(f"{header}\n{content}")

        return "\n\n".join(blocks)

    def get_base64_images(self) -> list[str]:
        """
        Get all base64 encoded images.

        Returns list of base64 strings for Ollama 'images' field.
        """
        images = []
        for doc in self.get_image_documents():
            b64 = doc.get_base64_image()
            if b64:
                images.append(b64)
        return images

    def build_ollama_content_injection(self) -> str:
        """
        Build the complete text injection for Ollama message content.

        Combines both TEXT documents and RAG context.
        """
        parts = []

        # Add text documents
        text_block = self.build_text_block()
        if text_block:
            parts.append(f"[Attached Documents]\n{text_block}")

        # Add RAG context
        rag_block = self.build_rag_context()
        if rag_block:
            parts.append(f"[Retrieved Context]\n{rag_block}")

        return "\n\n".join(parts)

    def prepare_for_ollama(self) -> tuple[str, list[str]]:
        """
        Prepare documents for Ollama API.

        Returns:
            Tuple of (text_injection, base64_images)
            - text_injection: String to inject into message content
            - base64_images: List of base64 strings for 'images' field
        """
        text_injection = self.build_ollama_content_injection()
        base64_images = self.get_base64_images()
        return text_injection, base64_images

    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self):
        return iter(self.documents)

    def __repr__(self) -> str:
        counts = {
            "text": len(self.get_text_documents()),
            "image": len(self.get_image_documents()),
            "rag": len(self.get_rag_documents()),
        }
        return f"DocumentCollection({counts})"


# -------------------------------------------------------------- #
# Message Models
# -------------------------------------------------------------- #


@dataclass
class MessageUsage:
    """Token usage information for a message."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class Message:
    """
    A single message in a conversation with full metadata.

    This is the universal message format that can be converted to/from:
    - LangChain BaseMessage
    - Ollama {role, content} format
    - Database records
    """

    id: str
    conversation_id: str
    role: Role
    content: str
    created_at: datetime

    # Who/what produced it
    model: str | None = None
    run_id: str | None = None  # LangChain run/trace ID
    parent_id: str | None = None  # For threading

    # Observability
    usage: MessageUsage | None = None
    latency_ms: float | None = None
    error: str | None = None

    # Metadata
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create_user_message(
        cls,
        conversation_id: str,
        content: str,
        metadata: dict | None = None,
        parent_id: str | None = None,
    ) -> Message:
        """Create a new user message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=content,
            created_at=datetime.utcnow(),
            parent_id=parent_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_assistant_message(
        cls,
        conversation_id: str,
        content: str,
        model: str | None = None,
        usage: MessageUsage | None = None,
        latency_ms: float | None = None,
        run_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new assistant message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            created_at=datetime.utcnow(),
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            run_id=run_id,
            parent_id=parent_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_system_message(
        cls,
        conversation_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new system message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="system",
            content=content,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )

    @classmethod
    def create_tool_message(
        cls,
        conversation_id: str,
        content: str,
        tool_name: str,
        tool_call_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new tool message."""
        metadata = metadata or {}
        metadata.update({"tool_name": tool_name, "tool_call_id": tool_call_id})

        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="tool",
            content=content,
            created_at=datetime.utcnow(),
            parent_id=parent_id,
            metadata=metadata,
        )

    def to_ollama_format(self) -> dict[str, str]:
        """Convert to Ollama message format."""
        return {"role": self.role, "content": self.content}

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "model": self.model,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "usage": (
                {
                    "prompt_tokens": self.usage.prompt_tokens,
                    "completion_tokens": self.usage.completion_tokens,
                    "total_tokens": self.usage.total_tokens,
                }
                if self.usage
                else None
            ),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        """Create Message from dictionary."""
        usage = None
        if data.get("usage"):
            usage = MessageUsage(
                prompt_tokens=data["usage"].get("prompt_tokens"),
                completion_tokens=data["usage"].get("completion_tokens"),
                total_tokens=data["usage"].get("total_tokens"),
            )

        return cls(
            id=data["id"],
            conversation_id=data["conversation_id"],
            role=data["role"],
            content=data["content"],
            created_at=datetime.fromisoformat(data["created_at"]),
            model=data.get("model"),
            run_id=data.get("run_id"),
            parent_id=data.get("parent_id"),
            usage=usage,
            latency_ms=data.get("latency_ms"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        return f"Message(id={self.id[:8]}..., role={self.role}, content={self.content[:50]}...)"


@dataclass
class Conversation:
    """
    Conversation metadata and tracking.

    Represents a multi-turn conversation session with metadata,
    timestamps, and optional title/description.
    """

    id: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    metadata: dict = field(default_factory=dict)

    # Statistics
    message_count: int = 0
    total_tokens: int = 0

    @classmethod
    def create(cls, title: str | None = None, metadata: dict | None = None) -> Conversation:
        """Create a new conversation."""
        now = datetime.utcnow()
        return cls(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            title=title,
            metadata=metadata or {},
        )

    def update_metadata(self, updates: dict) -> None:
        """Update conversation metadata."""
        self.metadata.update(updates)
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "title": self.title,
            "metadata": self.metadata,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Conversation:
        """Create Conversation from dictionary."""
        return cls(
            id=data["id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            title=data.get("title"),
            metadata=data.get("metadata", {}),
            message_count=data.get("message_count", 0),
            total_tokens=data.get("total_tokens", 0),
        )

    def __repr__(self) -> str:
        return (
            f"Conversation(id={self.id[:8]}..., title={self.title}, messages={self.message_count})"
        )


@dataclass
class MessageChunk:
    """
    A streaming chunk of a message.

    Used for real-time streaming responses.
    """

    conversation_id: str
    message_id: str
    content: str
    done: bool = False
    metadata: dict = field(default_factory=dict)
