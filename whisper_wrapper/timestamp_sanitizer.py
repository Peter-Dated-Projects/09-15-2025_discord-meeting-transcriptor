"""
Timestamp sanitizer for Whisper transcription results.

Fixes common issues with whisper-cpp timestamps on long audio files:
- Negative timestamps
- Inverted timestamps (end < start)
- Non-monotonic segments
- Word-level timestamp misalignment
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def sanitize_whisper_segments(
    segments: List[Dict[str, Any]],
    audio_duration: Optional[float] = None,
    max_backtrack: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Heuristic sanitizer for Whisper segments + words.

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
    fixed = []
    last_end = 0.0

    # If duration isn't provided, estimate from existing ends
    if audio_duration is None:
        audio_duration = max(
            (float(s.get("end", 0.0)) for s in segments if s.get("end", 0.0) > 0),
            default=0.0,
        )

    for seg in segments:
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", 0.0))
        text = seg.get("text", "") or ""
        words = seg.get("words") or []
        seg_dur = max(s_end - s_start, 0.0)

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
            new_start = last_end

            if word_span > 0.05:
                est_dur = word_span
            else:
                # Rough speech rate ~15 chars/sec, clipped
                est_dur = max(min(len(text) / 15.0, 10.0), 0.3)

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

    result["segments"] = sanitize_whisper_segments(segments, audio_duration=duration)

    logger.info("Timestamp sanitization complete")

    return result
