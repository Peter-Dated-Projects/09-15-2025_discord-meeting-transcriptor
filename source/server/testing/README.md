# Testing Environment

This directory contains in-memory implementations of all external services for testing purposes.

## Overview

The testing environment provides lightweight, in-memory versions of:
- **SQL Database**: In-memory SQLite that mimics MySQL behavior
- **Vector Database**: In-memory ChromaDB for vector storage
- **Whisper Server**: Real Whisper server client (uses common implementation)

## Purpose

The testing environment enables:
1. **Fast unit tests** with minimal external dependencies
2. **Isolated test execution** with fresh databases for each test
3. **Minimal infrastructure requirements** - only Whisper server needed (if testing transcription)
4. **Deterministic behavior** through in-memory databases

## Architecture

```
source/server/testing/
├── __init__.py              # Package initialization
├── constructor.py           # ServerManager constructor for tests
├── mysql.py                 # In-memory SQLite (MySQL-compatible)
├── vector_db.py            # In-memory ChromaDB client
└── whisper_server.py       # Mock Whisper server (kept for reference)
```

**Note**: The testing constructor uses the common Whisper server implementation from `source/server/common/whisper_server.py`, not the mock.

## Usage

### In pytest fixtures (recommended)

```python
import pytest

@pytest.mark.unit
@pytest.mark.asyncio
async def test_my_feature(test_server_manager):
    """Test using the in-memory server manager."""
    # test_server_manager is already connected
    sql_client = test_server_manager.sql_client
    vector_db = test_server_manager.vector_db_client
    whisper = test_server_manager.whisper_server_client
    
    # Use them in your tests
    ...
```

### Manual construction

```python
from source.context import Context
from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager

# Create context
context = Context()

# Construct test server manager
server = construct_server_manager(ServerManagerType.TESTING, context)
context.set_server_manager(server)

# Connect all services
await server.connect_all()

try:
    # Use the server
    ...
finally:
    # Clean up
    await server.disconnect_all()
```

## Available Fixtures

### `test_context`
- Returns: `Context` instance
- Scope: Function
- Description: Basic context object for tests

### `test_server_manager`
- Returns: `ServerManager` with all in-memory services
- Scope: Function
- Description: Fully initialized server manager with:
  - In-memory SQL database with tables created
  - In-memory ChromaDB client
  - Mock Whisper server
- Automatically connects on setup and disconnects on teardown

### `test_sql_client`
- Returns: `InMemoryMySQLServer`
- Scope: Function
- Description: Direct access to the SQL client from test_server_manager

### `test_vector_db_client`
- Returns: `InMemoryChromaDBClient`
- Scope: Function
- Description: Direct access to the vector DB client

### `test_whisper_client`
- Returns: `MockWhisperServerClient`
- Scope: Function
- Description: Direct access to the mock Whisper client

## Implementation Details

### In-Memory SQL Database

Uses SQLite with aiosqlite as an in-memory database. Key features:
- Mimics MySQL behavior for testing
- Supports SQLAlchemy ORM models
- Full CRUD operations
- Transaction support
- Automatic table creation from models

Limitations:
- Some MySQL-specific features may not work identically
- Performance characteristics differ from MySQL

### In-Memory ChromaDB

Uses ChromaDB's built-in in-memory client. Key features:
- Full ChromaDB API support
- Collection management
- Vector operations
- No persistence (resets between tests)

### Whisper Server Client

Uses the real Whisper server client from `source/server/common/whisper_server.py`. Key features:
- Connects to actual Whisper server (default: localhost:50021)
- Configurable via `WHISPER_HOST` and `WHISPER_PORT` environment variables
- Full transcription capabilities
- Requires running Whisper server for tests that use transcription

**Note**: Tests that require Whisper server functionality will need the server running. You can:
1. Run the Whisper server locally before running tests
2. Mock the Whisper client in specific tests if needed
3. Skip tests that require Whisper if not available

## Dependencies

The testing environment requires:
- `aiosqlite` - For in-memory SQLite database
- `chromadb` - For in-memory vector database
- `sqlalchemy` - For query building and compilation
- `aiohttp` - For Whisper server communication

These are typically already installed as they're required by the dev environment.

## Best Practices

1. **Use appropriate fixtures**: Use `test_server_manager` for integration-style unit tests, individual client fixtures for focused tests

2. **Test isolation**: Each test gets fresh instances, ensuring no test pollution

3. **Handle Whisper server availability**: For tests that use transcription, either ensure the Whisper server is running or mock the client

4. **Leverage async/await**: All fixtures are async-compatible

5. **Clean up**: Fixtures handle cleanup automatically, but you can manually reset if needed:
   ```python
   test_vector_db_client.reset()
   ```

## Running Tests

Run unit tests (no --db-env required):
```bash
pytest tests/unit
```

Run specific test file:
```bash
pytest tests/unit/test_testing_environment.py
```

Run with verbose output:
```bash
pytest tests/unit -v
```

## Debugging

Enable debug logging to see database operations:
```python
import logging
logging.getLogger("source.server.testing").setLevel(logging.DEBUG)
```

## Migration from Mocks

If you have existing tests using mocks, you can migrate to the testing environment:

**Before:**
```python
@pytest.fixture
def mock_sql_client():
    return MagicMock()
```

**After:**
```python
# Just use the test_sql_client fixture - no mock needed!
async def test_feature(test_sql_client):
    # Real SQL operations, in-memory
    ...
```

The testing environment provides real implementations (in-memory for databases, real client for Whisper), which catches more bugs while remaining fast for databases. Note that Whisper tests require a running server or additional mocking.
