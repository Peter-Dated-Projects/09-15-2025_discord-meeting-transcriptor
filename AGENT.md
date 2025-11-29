# Agent Architecture Guide

This document provides a high-level overview of the internal architecture of the Discord Meeting Transcriptor, focusing on its AI-powered "agent" capabilities.

## System Overview

The project is a Discord bot that combines several services to provide real-time transcription, summarization, and question-answering about meetings. The core components are:

1.  **Discord Bot (`cogs/`)**: The user-facing component, built with Py-Cord. It handles user commands, voice channel recording, and presenting information back to the user.
2.  **Whisper Transcription Service (`whisper_wrapper/`)**: A separate service that takes audio recordings and transcribes them into text using a Whisper model.
3.  **Core Services (`source/services/`)**: The business logic of the application. This is where the "agent" capabilities live.
4.  **Server (`source/server/`)**: Manages interactions with external services like the database and vector store.

## Agent Capabilities & Data Flow

The "agent" is not a single component, but an orchestration of services to perform complex tasks. Here's a typical data flow for a recorded meeting:

1.  **Recording**: The Discord bot (`cogs/voice.py`) records audio from a voice channel and saves it as an audio file.
2.  **Transcription**: The audio file is sent to the **Whisper Transcription Service**. This service can be run locally or remotely. The service returns a structured transcript with speaker diarization and timestamps. (`source/services/transcribe.py`)
3.  **Storage**: The transcript is stored in a **PostgreSQL** database. This includes the full text, speaker information, and meeting metadata. (`source/server/sql_models.py`, `source/server/production/postgresql.py`)
4.  **Embedding & Indexing (RAG)**: The transcript is chunked into smaller pieces. Each chunk is converted into a vector embedding and stored in a **ChromaDB** vector store. This process is the "retrieval" part of Retrieval-Augmented Generation (RAG). (`source/services/rag.py`, `source/server/common/chroma.py`)
5.  **Summarization**: An LLM (powered by Ollama) is used to generate a concise summary of the entire transcript. This summary is also stored. (`source/services/rag.py`)
6.  **Question Answering (RAG)**: When a user asks a question about a meeting:
    *   The user's question is converted into a vector embedding.
    *   A semantic search is performed on the ChromaDB vector store to find the most relevant transcript chunks.
    *   These chunks are passed to an LLM, along with the user's original question, as context.
    *   The LLM generates an answer based on the provided context. (`source/services/rag.py`)

## Key Source Code Modules

-   **`main.py`**: The main entry point for the Discord bot.
-   **`cogs/voice.py`**: Handles all voice-related commands like `/join`, `/leave`, and recording.
-   **`source/services/transcribe.py`**: Manages the transcription process, interacting with the Whisper service.
-   **`source/services/rag.py`**: Contains the core logic for all LLM-related tasks: summarization, question-answering, and RAG.
-   **`source/server/server.py`**: Defines the base classes for interacting with external services.
-   **`source/server/production/postgresql.py`**: The implementation for interacting with the PostgreSQL database.
-   **`source/server/common/chroma.py`**: The implementation for interacting with the ChromaDB vector store.
-   **`whisper_wrapper/app.py`**: The FastAPI application for the Whisper transcription service.

## Testing Philosophy

Our testing strategy focuses on the core business logic within the `source/` directory.

-   **Unit Tests (`tests/unit/`)**: Test individual services in isolation (e.g., testing the RAG service with mock data).
-   **Integration Tests (`tests/integration/`)**: Test the interaction between services (e.g., testing the full flow from a transcript to a database entry and a vector store index).

We do **not** write tests for the Discord bot UI (`cogs/`) because it is difficult to maintain and primarily tests the Py-Cord framework itself.