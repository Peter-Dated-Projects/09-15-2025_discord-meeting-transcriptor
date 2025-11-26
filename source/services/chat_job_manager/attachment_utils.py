"""
Utilities for processing Discord message attachments in chat conversations.

This module provides functions to:
- Extract attachment metadata from Discord messages
- Download and process images
- Extract text from URLs
- Handle file attachments
"""

import io
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
) -> str | None:
    """
    Download an attachment from a URL to temporary storage.

    Args:
        url: Attachment URL
        temp_dir: Temporary directory to save the file
        filename: Optional filename, will be extracted from URL if not provided
        max_size_mb: Maximum file size in MB

    Returns:
        Absolute path to downloaded file or None if download failed
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    try:
        # Determine filename
        if not filename:
            # Extract filename from URL
            parsed = urlparse(url)
            filename = unquote(os.path.basename(parsed.path))
            if not filename or filename == "":
                filename = f"attachment_{hash(url)}"

        # Ensure temp directory exists
        os.makedirs(temp_dir, exist_ok=True)

        # Build full path
        file_path = os.path.join(temp_dir, filename)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    return None

                # Check content length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_size_bytes:
                    return None

                # Download to file in chunks
                total_size = 0
                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        total_size += len(chunk)
                        if total_size > max_size_bytes:
                            # Clean up partial file
                            f.close()
                            os.remove(file_path)
                            return None
                        f.write(chunk)

                return os.path.abspath(file_path)

    except Exception as e:
        # Clean up on error if file exists
        if filename:
            file_path = os.path.join(temp_dir, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        return None


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
            status = "Failed" if downloaded is False else "Not attempted"
            lines.append(f"   Downloaded: {status}")

        # Add URL on next line if present
        if url:
            lines.append(f"   URL: {url}")

    return "\n".join(lines)


async def download_attachments_batch(
    attachments: list[dict[str, Any]],
    temp_dir: str,
    max_size_mb: int = 50,
) -> list[dict[str, Any]]:
    """
    Download multiple attachments and update their metadata with local paths.

    Args:
        attachments: List of attachment metadata
        temp_dir: Temporary directory for downloads
        max_size_mb: Maximum file size per attachment in MB

    Returns:
        Updated attachment list with 'local_path' added to successfully downloaded files
    """
    updated_attachments = []

    for att in attachments:
        att_copy = att.copy()
        att_type = att.get("type")
        url = att.get("url")

        # Download file attachments, images, videos, and audio
        if att_type in ["file", "image", "video", "audio"] and url:
            filename = att.get("filename")
            local_path = await download_attachment(
                url=url,
                temp_dir=temp_dir,
                filename=filename,
                max_size_mb=max_size_mb,
            )

            if local_path:
                att_copy["local_path"] = local_path
                att_copy["downloaded"] = True
            else:
                att_copy["downloaded"] = False
        else:
            # URLs and embeds don't need downloading
            att_copy["downloaded"] = False

        updated_attachments.append(att_copy)

    return updated_attachments


async def cleanup_attachment_files(attachments: list[dict[str, Any]]) -> int:
    """
    Clean up downloaded attachment files.

    Args:
        attachments: List of attachment metadata with 'local_path' fields

    Returns:
        Number of files successfully deleted
    """
    deleted_count = 0

    for att in attachments:
        local_path = att.get("local_path")
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                deleted_count += 1
            except Exception:
                pass  # Ignore cleanup errors

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
