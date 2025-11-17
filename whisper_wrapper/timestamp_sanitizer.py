"""
Timestamp sanitizer for Whisper transcription results.

Fixes common issues with whisper-cpp timestamps on long audio files:
- Negative timestamps
- Inverted timestamps (end < start)
- Non-monotonic segments
- Word-level timestamp misalignment
- Extra whitespace in text
"""

import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace.

    - Strips leading/trailing whitespace
    - Collapses multiple spaces into single space
    - Preserves single spaces between words

    Args:
        text: Text to clean

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Replace multiple whitespace (spaces, tabs, newlines) with single space
    text = re.sub(r"\s+", " ", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def sanitize_whisper_segments(
    segments: List[Dict[str, Any]],
    audio_duration: Optional[float] = None,
    max_backtrack: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Heuristic sanitizer for Whisper segments + words.

    Uses segment IDs as the source of truth for ordering, then:
    - Keeps timestamps that look sane and monotonic.
    - Fixes obviously broken ones (negative, inverted, huge jumps).
    - Uses word-level timing as fallback where reliable.
    - Otherwise, makes segments sequential using a speech-rate heuristic.

    Args:
        segments: List of segment dictionaries from Whisper output
        audio_duration: Total audio duration in seconds (optional)
        max_backtrack: Maximum allowed backward jump in seconds

    Returns:
        List of sanitized segment dictionaries
    """
    if not segments:
        return []

    # Step 1: Sort by ID to establish correct ordering
    # IDs are the source of truth for segment order
    sorted_segments = sorted(segments, key=lambda s: int(s.get("id", 0)))

    fixed = []
    last_end = 0.0
    fixed_count = 0  # Track how many segments we had to fix

    # If duration isn't provided, estimate from existing ends
    if audio_duration is None:
        audio_duration = max(
            (float(s.get("end", 0.0)) for s in sorted_segments if s.get("end", 0.0) > 0),
            default=0.0,
        )

    for seg in sorted_segments:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        text = seg.get("text", "") or ""
        words = seg.get("words") or []
        seg_dur = max(s_end - s_start, 0.0)

        # Clean the segment text
        cleaned_text = clean_text(text)
        seg["text"] = cleaned_text

        # Clean word-level text as well
        for w in words:
            if "word" in w:
                w["word"] = clean_text(w["word"])

        # Word stats
        if words:
            w_starts = [float(w["start"]) for w in words]
            w_ends = [float(w["end"]) for w in words]
            w_min = min(w_starts)
            w_max = max(w_ends)
            word_span = max(w_max - w_min, 0.0)
        else:
            w_min = 0.0
            w_max = 0.0
            word_span = 0.0

        # Are word times global (already aligned to segment) or local (0-based)?
        words_global = False
        if words and s_end > s_start and s_start >= -1.0:
            if w_min >= s_start - 1.0 and w_max <= s_end + 1.0:
                words_global = True

        def looks_reasonable(s: float, e: float) -> bool:
            if s < -1e-3 or e <= s:  # negative or inverted
                return False
            if audio_duration and (s > audio_duration + 5 or e > audio_duration + 5):
                return False
            # large backwards jump?
            if s < last_end - max_backtrack:
                return False
            return True

        use_raw = looks_reasonable(s_start, s_end)

        if use_raw:
            # Mostly trust Whisper, but smooth tiny overlaps/gaps
            new_start = max(s_start, last_end - 0.2)
            new_start = max(0.0, new_start)

            est_dur = max(seg_dur, word_span, 0.05)
            # keep something close to original but ensure min duration
            new_end = max(new_start + 0.05, min(s_end + 0.2, new_start + est_dur + 0.5))
        else:
            # Broken timestamps: place segment sequentially after last_end
            seg_id = seg.get("id", "?")
            logger.warning(
                f"Segment {seg_id} has broken timestamps (start={s_start:.2f}, end={s_end:.2f}). "
                f"Fixing to follow segment ordering. Placing after {last_end:.2f}s"
            )

            fixed_count += 1
            new_start = last_end

            if word_span > 0.05:
                est_dur = word_span
            else:
                # Rough speech rate ~15 chars/sec, clipped
                # Use cleaned text for duration estimate
                est_dur = max(min(len(cleaned_text) / 15.0, 10.0), 0.3)

            new_end = new_start + est_dur

        # Clip into audio duration if we know it
        if audio_duration:
            if new_start > audio_duration:
                new_start = max(audio_duration - 0.5, 0.0)
            new_end = min(new_end, audio_duration)

        seg["start"] = round(new_start, 3)
        seg["end"] = round(new_end, 3)

        # Fix words as well
        if words:
            if words_global and use_raw:
                # Already global – just clamp into the segment
                for w in words:
                    ws = max(new_start, min(float(w["start"]), new_end))
                    we = max(ws, min(float(w["end"]), new_end))
                    w["start"], w["end"] = round(ws, 3), round(we, 3)
            else:
                # Treat words as local times; scale into [new_start, new_end]
                if word_span > 0.01:
                    scale = (new_end - new_start) / word_span
                else:
                    scale = 1.0

                for w in words:
                    ws_local = float(w["start"]) - w_min
                    we_local = float(w["end"]) - w_min
                    ws = new_start + ws_local * scale
                    we = new_start + we_local * scale
                    if we < ws:
                        we = ws
                    w["start"], w["end"] = round(ws, 3), round(we, 3)

        last_end = seg["end"]
        fixed.append(seg)

    if fixed_count > 0:
        logger.info(f"Fixed {fixed_count} segments with broken timestamps")

    return fixed


def sanitize_whisper_result(result: dict) -> dict:
    """
    Apply segment/word timestamp sanitization to a whisper-server result dict.

    Args:
        result: Raw result dictionary from whisper-server

    Returns:
        Sanitized result dictionary with fixed timestamps
    """
    if not isinstance(result, dict):
        return result

    segments = result.get("segments")
    if not segments:
        return result

    duration = float(result.get("duration", 0.0) or 0.0)

    logger.info(f"Sanitizing {len(segments)} segments (audio duration: {duration:.2f}s)")

    # First pass: ensure segments are sorted by ID
    sorted_segments = sorted(segments, key=lambda s: int(s.get("id", 0)))

    result["segments"] = sanitize_whisper_segments(sorted_segments, audio_duration=duration)

    logger.info("Timestamp sanitization complete")

    return result
