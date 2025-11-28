"""Utilities for processing Discord message attachments in chat conversations.

This module provides functions to:
- Extract attachment metadata from Discord messages
- Download and process images
- Extract text from URLs
- Handle file attachments
- Build Ollama-compatible prompts with text documents and images

Ollama API Contract:
- Text documents → merged into prompt `content` (no separate `documents` field)
- Images → base64 encoded in `images` field (vision model required)
- No `documents` or `attachments` field exists in Ollama's chat API
"""

import base64
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

import aiohttp
import discord


# -------------------------------------------------------------- #
# Attachment Extraction
# -------------------------------------------------------------- #


async def extract_attachments_from_message(message: discord.Message) -> list[dict[str, Any]]:
    """
    Extract all attachments and URLs from a Discord message.

    This includes:
    - Discord file attachments (images, documents, etc.)
    - URLs embedded in message content
    - Embeds with images or thumbnails

    Args:
        message: Discord message object

    Returns:
        List of attachment metadata dictionaries with structure:
        {
            "type": "image" | "file" | "url" | "embed",
            "url": str,
            "filename": str (optional),
            "content_type": str (optional),
            "size": int (optional, in bytes),
            "description": str (optional)
        }
    """
    attachments = []

    # Process Discord attachments
    for attachment in message.attachments:
        att_data = {
            "type": _get_attachment_type(attachment.content_type),
            "url": attachment.url,
            "filename": attachment.filename,
            "content_type": attachment.content_type or "unknown",
            "size": attachment.size,
        }

        # Add description if available
        if attachment.description:
            att_data["description"] = attachment.description

        attachments.append(att_data)

    # Extract URLs from message content
    urls = extract_urls_from_text(message.content)
    for url in urls:
        attachments.append(
            {
                "type": "url",
                "url": url,
            }
        )

    # Process embeds (images, videos, etc.)
    for embed in message.embeds:
        if embed.image:
            attachments.append(
                {
                    "type": "embed",
                    "url": embed.image.url,
                    "description": "Embedded image",
                }
            )
        if embed.thumbnail:
            attachments.append(
                {
                    "type": "embed",
                    "url": embed.thumbnail.url,
                    "description": "Embedded thumbnail",
                }
            )
        if embed.video:
            attachments.append(
                {
                    "type": "embed",
                    "url": embed.video.url,
                    "description": "Embedded video",
                }
            )

    return attachments


def _get_attachment_type(content_type: str | None) -> str:
    """
    Determine attachment type from content type.

    Args:
        content_type: MIME type string

    Returns:
        "image", "video", "audio", or "file"
    """
    if not content_type:
        return "file"

    content_type = content_type.lower()

    if content_type.startswith("image/"):
        return "image"
    elif content_type.startswith("video/"):
        return "video"
    elif content_type.startswith("audio/"):
        return "audio"
    else:
        return "file"


def extract_urls_from_text(text: str) -> list[str]:
    """
    Extract URLs from text using regex.

    Args:
        text: Text content to search

    Returns:
        List of URL strings
    """
    # URL regex pattern
    url_pattern = re.compile(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    )

    return url_pattern.findall(text)


# -------------------------------------------------------------- #
# Attachment Processing
# -------------------------------------------------------------- #


async def download_attachment(
    url: str,
    temp_dir: str,
    filename: str | None = None,
    max_size_mb: int = 50,
    logger=None,
) -> tuple[str | None, str | None]:
    """
    Download an attachment from a URL to temporary storage.

    Args:
        url: Attachment URL
        temp_dir: Temporary directory to save the file
        filename: Optional filename, will be extracted from URL if not provided
        max_size_mb: Maximum file size in MB
        logger: Optional logger for debugging

    Returns:
        Tuple of (absolute path to downloaded file or None, error message or None)
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    try:
        # Determine filename from URL if not provided
        if not filename:
            # Extract filename from URL path
            parsed = urlparse(url)
            filename = unquote(os.path.basename(parsed.path))
            if not filename or filename == "":
                filename = "attachment.bin"

        if logger:
            logger.debug(f"[DOWNLOAD] Starting download: {filename} from {url[:100]}...")

        # Ensure temp directory exists
        os.makedirs(temp_dir, exist_ok=True)

        # Build full path
        file_path = os.path.join(temp_dir, filename)

        if logger:
            logger.debug(f"[DOWNLOAD] Target path: {file_path}")

        async with aiohttp.ClientSession() as session:
            if logger:
                logger.debug(f"[DOWNLOAD] Sending GET request to {url[:100]}...")

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if logger:
                    logger.debug(f"[DOWNLOAD] Response status: {response.status}")
                    logger.debug(f"[DOWNLOAD] Response headers: {dict(response.headers)}")

                if response.status != 200:
                    error_msg = f"HTTP {response.status}: {response.reason}"
                    if logger:
                        logger.warning(f"[DOWNLOAD] Failed - {error_msg}")
                    return None, error_msg

                # Check content length
                content_length = response.headers.get("Content-Length")
                if logger:
                    logger.debug(f"[DOWNLOAD] Content-Length: {content_length} bytes")

                if content_length and int(content_length) > max_size_bytes:
                    error_msg = f"File too large: {content_length} bytes (max: {max_size_bytes})"
                    if logger:
                        logger.warning(f"[DOWNLOAD] Failed - {error_msg}")
                    return None, error_msg

                # Download to file in chunks
                total_size = 0
                if logger:
                    logger.debug(f"[DOWNLOAD] Starting chunk download...")

                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        total_size += len(chunk)
                        if total_size > max_size_bytes:
                            # Clean up partial file
                            f.close()
                            os.remove(file_path)
                            error_msg = (
                                f"File exceeded size limit during download: {total_size} bytes"
                            )
                            if logger:
                                logger.warning(f"[DOWNLOAD] Failed - {error_msg}")
                            return None, error_msg
                        f.write(chunk)

                if logger:
                    logger.info(
                        f"[DOWNLOAD] Success: {filename} ({total_size} bytes) -> {file_path}"
                    )

                return os.path.abspath(file_path), None

    except aiohttp.ClientError as e:
        error_msg = f"Network error: {type(e).__name__}: {str(e)}"
        if logger:
            logger.error(f"[DOWNLOAD] Failed - {error_msg}")
        # Clean up on error if file exists
        if filename:
            file_path = os.path.join(temp_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return None, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
        if logger:
            logger.error(f"[DOWNLOAD] Failed - {error_msg}")
        # Clean up on error if file exists
        if filename:
            file_path = os.path.join(temp_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return None, error_msg


async def download_image_as_bytes(url: str, max_size_mb: int = 10) -> bytes | None:
    """
    Download an image from a URL as bytes (for in-memory processing).

    Args:
        url: Image URL
        max_size_mb: Maximum file size in MB

    Returns:
        Image bytes or None if download failed
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None

                # Check content length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_size_bytes:
                    return None

                # Download in chunks to respect max size
                chunks = []
                total_size = 0

                async for chunk in response.content.iter_chunked(8192):
                    total_size += len(chunk)
                    if total_size > max_size_bytes:
                        return None
                    chunks.append(chunk)

                return b"".join(chunks)

    except Exception:
        return None


async def fetch_url_content(url: str, max_length: int = 5000) -> str | None:
    """
    Fetch text content from a URL.

    Args:
        url: URL to fetch
        max_length: Maximum content length in characters

    Returns:
        Text content or None if fetch failed
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get("Content-Type", "").lower()

                # Only process text content
                if "text" not in content_type and "json" not in content_type:
                    return None

                text = await response.text()

                # Truncate if too long
                if len(text) > max_length:
                    text = text[:max_length] + "... (truncated)"

                return text

    except Exception:
        return None


# -------------------------------------------------------------- #
# Attachment Formatting for LLM
# -------------------------------------------------------------- #


def format_attachments_for_llm(attachments: list[dict[str, Any]]) -> str:
    """
    Format attachment metadata into a string for LLM context.

    Args:
        attachments: List of attachment metadata dictionaries

    Returns:
        Formatted string describing attachments
    """
    if not attachments:
        return ""

    lines = ["\n[Attachments:]"]

    for i, att in enumerate(attachments, 1):
        att_type = att.get("type", "unknown")
        url = att.get("url", "")
        filename = att.get("filename", "")
        description = att.get("description", "")
        local_path = att.get("local_path")
        downloaded = att.get("downloaded", False)

        # Build attachment description
        parts = [f"{i}. {att_type.upper()}"]

        if filename:
            parts.append(f"'{filename}'")

        if description:
            parts.append(f"- {description}")

        lines.append(" ".join(parts))

        # Add download status if applicable
        if local_path:
            lines.append(f"   Downloaded: Yes (available for processing)")
            lines.append(f"   Local Path: {local_path}")
        elif att_type in ["file", "image", "video", "audio"]:
            if downloaded is False:
                error = att.get("download_error", "Unknown error")
                lines.append(f"   Downloaded: Failed - {error}")
            else:
                lines.append(f"   Downloaded: Not attempted")

        # Add URL on next line if present
        if url:
            lines.append(f"   URL: {url}")

    return "\n".join(lines)


async def download_attachments_batch(
    attachments: list[dict[str, Any]],
    temp_dir: str,
    max_size_mb: int = 50,
    logger=None,
) -> list[dict[str, Any]]:
    """
    Download multiple attachments and update their metadata with local paths.

    Args:
        attachments: List of attachment metadata
        temp_dir: Temporary directory for downloads
        max_size_mb: Maximum file size per attachment in MB
        logger: Optional logger for debugging

    Returns:
        Updated attachment list with 'local_path' added to successfully downloaded files
    """
    updated_attachments = []

    if logger:
        logger.info(f"[DOWNLOAD_BATCH] Starting batch download of {len(attachments)} attachments")

    for i, att in enumerate(attachments, 1):
        att_copy = att.copy()
        att_type = att.get("type")
        url = att.get("url")
        filename = att.get("filename", "unknown")

        if logger:
            logger.debug(
                f"[DOWNLOAD_BATCH] Processing {i}/{len(attachments)}: {att_type} - {filename}"
            )

        # Download file attachments, images, videos, and audio
        if att_type in ["file", "image", "video", "audio"] and url:
            local_path, error = await download_attachment(
                url=url,
                temp_dir=temp_dir,
                filename=att.get("filename"),
                max_size_mb=max_size_mb,
                logger=logger,
            )

            if local_path:
                att_copy["local_path"] = local_path
                att_copy["downloaded"] = True
                if logger:
                    logger.info(f"[DOWNLOAD_BATCH] ✓ Downloaded {i}/{len(attachments)}: {filename}")
            else:
                att_copy["downloaded"] = False
                att_copy["download_error"] = error
                if logger:
                    logger.warning(
                        f"[DOWNLOAD_BATCH] ✗ Failed {i}/{len(attachments)}: {filename} - {error}"
                    )
        else:
            # URLs and embeds don't need downloading
            att_copy["downloaded"] = False
            if logger:
                logger.debug(
                    f"[DOWNLOAD_BATCH] - Skipping {i}/{len(attachments)}: {att_type} (no download needed)"
                )

        updated_attachments.append(att_copy)

    successful = sum(1 for att in updated_attachments if att.get("downloaded") is True)
    if logger:
        logger.info(f"[DOWNLOAD_BATCH] Completed: {successful}/{len(attachments)} successful")

    return updated_attachments


async def cleanup_attachment_files(attachments: list[dict[str, Any]], logger=None) -> int:
    """
    Clean up downloaded attachment files.

    Args:
        attachments: List of attachment metadata with 'local_path' fields
        logger: Optional logger for debugging

    Returns:
        Number of files successfully deleted
    """
    deleted_count = 0

    if logger:
        files_to_delete = sum(1 for att in attachments if att.get("local_path"))
        logger.debug(f"[CLEANUP] Starting cleanup of {files_to_delete} attachment files")

    for att in attachments:
        local_path = att.get("local_path")
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                deleted_count += 1
                if logger:
                    logger.debug(f"[CLEANUP] Deleted: {local_path}")
            except Exception as e:
                if logger:
                    logger.warning(f"[CLEANUP] Failed to delete {local_path}: {e}")

    if logger:
        logger.debug(f"[CLEANUP] Completed: {deleted_count} files deleted")

    return deleted_count


async def process_attachments_for_context(
    attachments: list[dict[str, Any]], download_images: bool = False
) -> tuple[str, list[bytes]]:
    """
    Process attachments and prepare them for LLM context.

    Args:
        attachments: List of attachment metadata
        download_images: Whether to download images

    Returns:
        Tuple of (formatted text description, list of image bytes)
    """
    formatted_text = format_attachments_for_llm(attachments)
    image_bytes_list = []

    if download_images:
        for att in attachments:
            if att.get("type") == "image":
                image_data = await download_image_as_bytes(att["url"])
                if image_data:
                    image_bytes_list.append(image_data)

    return formatted_text, image_bytes_list


# -------------------------------------------------------------- #
# Ollama-Compatible Prompt Building
# -------------------------------------------------------------- #

# File extensions considered as text documents
TEXT_DOCUMENT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".log",
    ".csv",
    ".tsv",
    ".ini",
    ".cfg",
    ".conf",
    ".toml",
}

# File extensions considered as images
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".svg",
}


def is_text_document(filename: str) -> bool:
    """
    Check if a file is a text document based on extension.

    Args:
        filename: Name of the file

    Returns:
        True if file is a text document
    """
    ext = Path(filename).suffix.lower()
    return ext in TEXT_DOCUMENT_EXTENSIONS


def is_image_file(filename: str) -> bool:
    """
    Check if a file is an image based on extension.

    Args:
        filename: Name of the file

    Returns:
        True if file is an image
    """
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def read_text_document(file_path: str, encoding: str = "utf-8") -> str | None:
    """
    Read a text document file and return its contents.

    Args:
        file_path: Path to the text file
        encoding: Text encoding (default: utf-8)

    Returns:
        File contents as string, or None if read failed
    """
    try:
        return Path(file_path).read_text(encoding=encoding)
    except Exception:
        # Try with latin-1 as fallback
        try:
            return Path(file_path).read_text(encoding="latin-1")
        except Exception:
            return None


def encode_image_to_base64(file_path: str) -> str | None:
    """
    Encode an image file to base64 string for Ollama vision models.

    Args:
        file_path: Path to the image file

    Returns:
        Base64 encoded string, or None if encoding failed
    """
    try:
        data = Path(file_path).read_bytes()
        return base64.b64encode(data).decode("utf-8")
    except Exception:
        return None


def build_text_documents_block(docs: dict[str, str]) -> str:
    """
    Build a formatted text block from multiple documents.

    This follows the Ollama pattern where text documents are injected
    directly into the prompt content.

    Args:
        docs: Dictionary mapping document names to their text content

    Returns:
        Formatted string with all documents
    """
    if not docs:
        return ""

    return "\n\n".join(f"### {name}\n{content}" for name, content in docs.items())


def build_text_doc_prompt(question: str, docs: dict[str, str]) -> list[dict]:
    """
    Build Ollama-compatible messages with text documents injected into content.

    For text-only models like gemma3:12b, this is the only supported way
    to use text documents. Documents are merged into the prompt text.

    Args:
        question: The user's question or message
        docs: Dictionary mapping document names to their text content

    Returns:
        List of message dicts for Ollama chat API
    """
    docs_block = build_text_documents_block(docs)

    if docs_block:
        content = (
            "Use the following text documents to help answer.\n\n" f"{docs_block}\n\n" f"{question}"
        )
    else:
        content = question

    return [{"role": "user", "content": content}]


def build_vision_prompt(
    question: str,
    image_paths: list[str],
    docs: dict[str, str] | None = None,
) -> list[dict]:
    """
    Build Ollama-compatible messages with images for vision models.

    For vision models (llava, llama3.2-vision, etc.), images are base64
    encoded and placed in the 'images' field. Text documents are still
    merged into the content.

    Args:
        question: The user's question or message
        image_paths: List of paths to image files
        docs: Optional dictionary mapping document names to text content

    Returns:
        List of message dicts for Ollama chat API with 'images' field
    """
    # Encode all images to base64
    encoded_images = []
    for path in image_paths:
        encoded = encode_image_to_base64(path)
        if encoded:
            encoded_images.append(encoded)

    # Build content with optional text documents
    if docs:
        docs_block = build_text_documents_block(docs)
        content = (
            "Use the following text and images to help answer.\n\n"
            f"{docs_block}\n\n"
            f"{question}"
        )
    else:
        content = question

    message = {"role": "user", "content": content}

    # Add images if any were successfully encoded
    if encoded_images:
        message["images"] = encoded_images

    return [message]


def extract_documents_and_images_from_attachments(
    attachments: list[dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """
    Extract text documents and image paths from downloaded attachments.

    This processes attachment metadata and reads/identifies files that
    have been downloaded to local paths.

    Args:
        attachments: List of attachment metadata with 'local_path' fields

    Returns:
        Tuple of:
        - docs: Dictionary mapping filenames to text content
        - image_paths: List of local paths to image files
    """
    docs: dict[str, str] = {}
    image_paths: list[str] = []

    for att in attachments:
        local_path = att.get("local_path")
        if not local_path or not os.path.exists(local_path):
            continue

        filename = att.get("filename", os.path.basename(local_path))
        att_type = att.get("type", "")

        # Check if it's an image
        if att_type == "image" or is_image_file(filename):
            image_paths.append(local_path)

        # Check if it's a text document
        elif att_type == "file" and is_text_document(filename):
            content = read_text_document(local_path)
            if content:
                # Use original filename as the document name
                docs[filename] = content

    return docs, image_paths


def build_ollama_message_with_attachments(
    content: str,
    attachments: list[dict[str, Any]],
    include_attachment_summary: bool = True,
) -> dict[str, Any]:
    """
    Build a single Ollama-compatible message with text docs and images.

    This is the main function for preparing a user message with attachments
    for the Ollama chat API. It:
    1. Extracts text documents and reads their content
    2. Extracts image paths and base64 encodes them
    3. Merges text documents into the content
    4. Places encoded images in the 'images' field

    Args:
        content: The user's message content
        attachments: List of attachment metadata with 'local_path' fields
        include_attachment_summary: Whether to include a summary of attachments

    Returns:
        Message dict with 'role', 'content', and optionally 'images'
    """
    docs, image_paths = extract_documents_and_images_from_attachments(attachments)

    # Build content with text documents
    parts = []

    if docs:
        docs_block = build_text_documents_block(docs)
        parts.append(f"[Attached Documents]\n{docs_block}")

    if include_attachment_summary and (docs or image_paths):
        summary_parts = []
        if docs:
            summary_parts.append(f"{len(docs)} text document(s)")
        if image_paths:
            summary_parts.append(f"{len(image_paths)} image(s)")
        parts.append(f"[Attachments: {', '.join(summary_parts)}]")

    parts.append(content)

    final_content = "\n\n".join(parts)

    # Build message
    message: dict[str, Any] = {
        "role": "user",
        "content": final_content,
    }

    # Encode and add images
    if image_paths:
        encoded_images = []
        for path in image_paths:
            encoded = encode_image_to_base64(path)
            if encoded:
                encoded_images.append(encoded)
        if encoded_images:
            message["images"] = encoded_images

    return message
