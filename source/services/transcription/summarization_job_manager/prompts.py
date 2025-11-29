"""
Prompt templates for summarization tasks.

This module contains system messages and user content templates used
during the recursive summarization process.
"""

# -------------------------------------------------------------- #
# Level 0: Initial Transcript Summarization
# -------------------------------------------------------------- #

LEVEL_0_SYSTEM_MESSAGE = """You are an expert at summarizing meeting transcripts. Extract key topics, decisions, and action items concisely."""

LEVEL_0_USER_CONTENT_TEMPLATE = """Summarize this meeting transcript section (part {chunk_number} of {total_chunks}).
Provide a 200-500 word summary covering:
- Main topics discussed
- Key points and decisions for each topic discussed
- Important action items
- Notable speakers/perspectives

Transcript:
{chunk_text}"""

# -------------------------------------------------------------- #
# Level 1+: Recursive Summary Consolidation
# -------------------------------------------------------------- #

LEVEL_N_SYSTEM_MESSAGE = """You are an expert at summarizing summaries of meeting transcripts. Create a concise overview that preserves the most important information from multiple summaries."""

LEVEL_N_USER_CONTENT_TEMPLATE = """Create a consolidated summary from this summary section (part {chunk_number} of {total_chunks}).
Provide a 200-500 word overview that combines and preserves the most important information:

Summary section:
{chunk_text}"""
