# Agent Development Guide

This document provides guidance for AI agents and developers working on the Discord Meeting Transcriptor bot.

## Project Overview

A Discord bot that records voice channel meetings and provides:
- Real-time transcription of voice conversations
- Meeting summaries and insights
- RAG (Retrieval-Augmented Generation) powered question answering
- PostgreSQL storage for transcripts and metadata

---

## Testing Strategy

### What We Test

We focus on testing **business logic and core services**, not Discord.py framework code:

#### ✅ **Unit Tests** (tests/unit/)
- **RAG Service** (`test_rag.py`)
  - Text embedding generation
  - Transcript chunk storage and retrieval
  - Semantic search functionality
  - Context retrieval for LLM queries
  - Meeting summarization logic
  - Question answering logic
  - Transcript chunking with overlap

- **Transcription Service** (`test_transcription.py`)
  - Audio-to-text conversion
  - Speaker identification/diarization
  - Timestamp alignment
  - Audio preprocessing
  - Confidence scoring
  - Language detection

- **PostgreSQL Service** (`test_postgresql.py`)
  - Database connection handling
  - Connection pool management
  - Query execution
  - Health checks
  - Error handling
  - Transaction management

- **Server Management** (`test_server.py`)
  - Base server handler functionality
  - Server manager coordination
  - Service health monitoring

#### ✅ **Integration Tests** (tests/integration/)
- Database operations with real PostgreSQL instance
- RAG pipeline with actual embeddings
- Transcription with real audio files
- End-to-end workflows (audio → transcript → RAG → query)

### What We DON'T Test

❌ **Discord.py Framework Code**
- Bot commands and event handlers
- Discord API interactions
- Voice channel connections
- User interactions and responses
- Cog loading/setup

**Reasoning:** Discord.py is a well-tested framework. Testing it would be:
- Redundant (framework already tested)
- Brittle (requires extensive mocking)
- Low value (not our business logic)
- Hard to maintain (Discord API changes)

Instead, we keep Discord integration thin and test the services it calls.

---

## Dependencies Management

### Production Dependencies (`requirements.txt`)

**Purpose:** Only dependencies needed to run the bot in production

```txt
discord.py>=2.6.4          # Discord bot framework
python-dotenv>=1.1.1       # Environment variable management
asyncpg>=0.29.0            # PostgreSQL async driver
audioop-lts>=0.2.2         # Audio operations
```

**When to add:**
- Dependencies required for the bot to function
- Libraries used in production code
- Runtime requirements

**Installation:**
```bash
pip install -r requirements.txt
```

### Development Dependencies (`requirements-dev.txt`)

**Purpose:** Tools for development, testing, and code quality (NOT needed in production)

```txt
# Code Quality & Linting
ruff>=0.8.0                # Fast Python linter
black>=24.0.0              # Code formatter
mypy>=1.18.2               # Static type checker

# Testing
pytest>=8.0.0              # Test framework
pytest-asyncio>=0.24.0     # Async test support
pytest-cov>=6.0.0          # Coverage reporting
pytest-mock>=3.14.0        # Mocking utilities

# Pre-commit
pre-commit>=4.0.0          # Git hooks management

# Security
bandit[toml]>=1.7.10       # Security issue scanner

# Development Tools
watchfiles>=1.1.1          # File watching for auto-reload
ipython>=8.20.0            # Enhanced Python REPL

# Type Stubs
types-python-dotenv>=1.0.0 # Type hints for python-dotenv
```

**When to add:**
- Testing frameworks and tools
- Linters, formatters, type checkers
- Development utilities
- Documentation generators
- Debugging tools

**Installation:**
```bash
pip install -r requirements-dev.txt
```

### Why Separate Files?

1. **Lean Production Deployments**
   - Smaller Docker images
   - Faster deployment times
   - Reduced attack surface
   - Lower memory footprint

2. **Clear Separation of Concerns**
   - Explicit about what's needed where
   - Prevents accidentally deploying dev tools
   - Makes CI/CD configuration clearer

3. **Cost Efficiency**
   - Don't pay for unused dependencies in production
   - Faster cold starts in serverless environments

4. **Security**
   - Fewer dependencies = fewer potential vulnerabilities
   - Dev tools might have security issues that don't matter locally

### Alternative: pyproject.toml

The project also defines dependencies in `pyproject.toml`:

```toml
[project]
dependencies = [...]  # Production deps

[project.optional-dependencies]
dev = [...]  # Development deps
```

**To use pyproject.toml instead:**
```bash
# Production
pip install .

# Development
pip install ".[dev]"
```

**Note:** We maintain both approaches for flexibility. Choose the one that fits your workflow.

---

## Test Writing Guidelines

### Good Test Practices

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_specific_behavior() -> None:
    """Test description explaining WHAT and WHY."""
    # Arrange: Set up test data
    service = RAGService()
    
    # Act: Perform the action
    result = await service.embed_text("test")
    
    # Assert: Verify behavior
    assert isinstance(result, list)
    assert len(result) > 0
```

### Test Fixtures (tests/conftest.py)

Reusable test components:
- `sample_transcript` - Example meeting transcript
- `sample_meeting_id` - Test meeting ID
- `mock_postgres_pool` - Mock database pool
- `mock_postgres_connection` - Mock database connection

**Usage:**
```python
async def test_something(sample_transcript: str, sample_meeting_id: str) -> None:
    # Fixtures automatically injected by pytest
    pass
```

### Markers

- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Tests requiring external services
- `@pytest.mark.slow` - Long-running tests

**Run specific markers:**
```bash
pytest -m unit          # Only unit tests
pytest -m "not slow"    # Skip slow tests
```

---

## Development Workflow

### Initial Setup

```bash
# 1. Install dependencies
make install-dev

# 2. Set up pre-commit hooks
make pre-commit-install

# 3. Create environment file
cp .env.example .env
# Edit .env with your tokens
```

### Daily Development

```bash
# Run bot in development mode (auto-reload)
make dev

# Before committing
make check-all        # Format, lint, type-check, test

# Or individually
make format          # Auto-format code
make lint            # Check code quality
make type-check      # Run mypy
make test            # Run tests
make test-cov        # With coverage report
```

### Pre-commit Hooks

Automatically run before each commit:
- ✨ Format code (Black, Ruff)
- 🔍 Lint code (Ruff)
- 🔒 Security scan (Bandit)
- 🔑 Secret detection
- 📝 File formatting checks
- ⚡ Type checking (MyPy)

---

## Code Style

- **Line Length:** 88 characters (Black default)
- **Type Hints:** Required for all function signatures
- **Docstrings:** Required for public classes and functions
- **Import Sorting:** Automatic via Ruff
- **Formatting:** Automatic via Black

### Example

```python
"""Module docstring explaining purpose."""

from typing import Optional, List
from datetime import datetime


async def process_transcript(
    transcript: str,
    meeting_id: str,
    timestamp: Optional[datetime] = None,
) -> List[str]:
    """
    Process a meeting transcript.
    
    Args:
        transcript: The raw transcript text
        meeting_id: Unique meeting identifier
        timestamp: Optional timestamp override
        
    Returns:
        List of processed transcript chunks
    """
    # Implementation
    pass
```

---

## Common Tasks

### Adding a New Service

1. Create service class in `source/services/`
2. Add type hints and docstrings
3. Create corresponding test file in `tests/unit/`
4. Write tests using appropriate fixtures
5. Update this guide if needed

### Adding a New Dependency

**Production dependency:**
```bash
# Add to requirements.txt
echo "new-package>=1.0.0" >> requirements.txt
pip install -r requirements.txt
```

**Development dependency:**
```bash
# Add to requirements-dev.txt
echo "new-dev-package>=1.0.0" >> requirements-dev.txt
pip install -r requirements-dev.txt
```

### Running Tests

```bash
# All tests
pytest

# Specific file
pytest tests/unit/test_rag.py

# Specific test
pytest tests/unit/test_rag.py::TestRAGService::test_embed_text

# With coverage
pytest --cov --cov-report=html
open htmlcov/index.html

# Watch mode (rerun on file changes)
pytest-watch
```

---

## File Structure Reference

```
.
├── main.py                      # Bot entry point (Discord integration)
├── requirements.txt             # Production dependencies ONLY
├── requirements-dev.txt         # Development dependencies ONLY
├── pyproject.toml              # All tool configurations
├── .pre-commit-config.yaml     # Pre-commit hooks
├── Makefile                    # Common development commands
├── AGENT.md                    # This file
├── DEVELOPMENT.md              # Detailed setup guide
│
├── cogs/                       # Discord command modules (not tested)
│   ├── general.py
│   └── voice.py
│
├── source/                     # Core business logic (tested!)
│   ├── utils.py
│   ├── services/               # Service layer
│   │   ├── transcribe.py       # Audio → Text
│   │   └── rag.py              # RAG/LLM operations
│   └── server/                 # External service handlers
│       ├── server.py           # Base server classes
│       ├── postgresql.py       # Database handler
│       └── vectordb.py         # Vector database handler
│
└── tests/                      # Test suite
    ├── conftest.py             # Shared fixtures
    ├── unit/                   # Unit tests
    │   ├── test_rag.py
    │   ├── test_transcription.py
    │   └── test_postgresql.py
    └── integration/            # Integration tests
        └── (to be added)
```

---

## Questions?

For more details:
- See `DEVELOPMENT.md` for setup instructions
- See `README.md` for project overview
- Run `make help` for available commands
- Check `pyproject.toml` for tool configurations

Happy coding! 🚀
