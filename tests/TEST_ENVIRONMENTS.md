# Test Environments Guide

⚠️ **IMPORTANT**: You **MUST** specify either `local` or `prod` when running tests. Tests will not run without specifying an environment.

## Quick Start

```bash
# Run tests with local (MySQL) database
pytest --db-env local

# Run tests with production (PostgreSQL) database
pytest --db-env prod

# Or use the helper script
./run_tests_env.sh local
./run_tests_env.sh prod
```

## Environment Modes

### 1. **Local Environment** (MySQL)
- **Database**: MySQL
- **Use Case**: Development and local testing
- **Location**: `source/server/dev/mysql.py`
- **Required**: YES - Must specify `--db-env local` or `TEST_ENV=local`

```bash
# Using --db-env option (RECOMMENDED)
pytest --db-env local

# Run unit tests only (no database required)
pytest --db-env local tests/unit -m "not integration"

# Run specific test file
pytest --db-env local tests/unit/test_mysql_connection.py

# Using TEST_ENV environment variable (alternative)
TEST_ENV=local pytest

# Using helper script
./run_tests_env.sh local
./run_tests_env.sh local -k health_check
```

### 2. **Production Environment** (PostgreSQL)
- **Database**: PostgreSQL
- **Use Case**: Testing production-like infrastructure
- **Location**: `source/server/production/postgresql.py`
- **Required**: YES - Must specify `--db-env prod` or `TEST_ENV=prod`

```bash
# Using --db-env option (RECOMMENDED)
pytest --db-env prod

# Run unit tests only (no database required)
pytest --db-env prod tests/unit -m "not integration"

# Run specific test file
pytest --db-env prod tests/unit/test_postgresql_connection.py

# Using TEST_ENV environment variable (alternative)
TEST_ENV=prod pytest

# Using helper script
./run_tests_env.sh prod
./run_tests_env.sh prod tests/integration
```

## Specifying the Environment

You have **two ways** to specify the environment:

### Option 1: Using `--db-env` flag (RECOMMENDED)
```bash
pytest --db-env local
pytest --db-env prod
```

### Option 2: Using `TEST_ENV` environment variable
```bash
TEST_ENV=local pytest
TEST_ENV=prod pytest
```

### Option 3: Using the helper script
```bash
./run_tests_env.sh local
./run_tests_env.sh prod
```

## Error: Environment Not Specified

If you try to run tests without specifying an environment, you'll get this error:

```
❌ TEST ENVIRONMENT NOT SPECIFIED

You must specify which test environment to use. Choose one:

  Local (MySQL):
    pytest --db-env local

  Production (PostgreSQL):
    pytest --db-env prod

Or use environment variables:
    TEST_ENV=local pytest
    TEST_ENV=prod pytest

Examples:
  pytest --db-env local tests/unit
  pytest --db-env prod tests/integration
  TEST_ENV=local pytest -m 'not integration'
```

**Solution**: Always specify `--db-env local` or `--db-env prod`

## Integration Test Structure

Integration tests have been organized by environment for clarity and separation of concerns:

### Local Integration Tests (MySQL)
- **File**: `tests/integration/test_database_connections_local.py`
- **Markers**: `@pytest.mark.local @pytest.mark.integration`
- **Run with**: `pytest --db-env local tests/integration/test_database_connections_local.py`
- **Tests**:
  - MySQL real connection
  - MySQL query execution
  - MySQL connection failure handling
  - MySQL connection pool properties
  - MySQL multiple sequential queries

### Production Integration Tests (PostgreSQL)
- **File**: `tests/integration/test_database_connections_prod.py`
- **Markers**: `@pytest.mark.prod @pytest.mark.integration`
- **Run with**: `pytest --db-env prod tests/integration/test_database_connections_prod.py`
- **Tests**:
  - PostgreSQL real connection
  - PostgreSQL query execution
  - PostgreSQL connection failure handling
  - PostgreSQL connection pool properties
  - PostgreSQL multiple sequential queries
  - PostgreSQL transaction support

### Shared Compatibility Tests
- **File**: `tests/integration/test_database_connections.py`
- **Purpose**: Tests that work in either environment
- **Tests**:
  - Independent connection handling (gracefully handles unavailable database)

## Test Markers

Tests can be marked with `@pytest.mark.local` or `@pytest.mark.prod` to specify which environment they should run in.

### Marking Tests for Specific Environments

```python
import pytest

# This test runs only in local environment (MySQL)
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_specific_feature():
    pass

# This test runs only in production environment (PostgreSQL)
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_specific_feature():
    pass

# This test runs in both environments (default)
@pytest.mark.asyncio
async def test_shared_functionality():
    pass
```

## Environment-Aware Fixtures

The test framework provides environment-aware fixtures that automatically use the correct database backend:

### Fixtures Available

| Fixture | Type | Description |
|---------|------|-------------|
| `test_environment` | str | Current test environment ('local' or 'prod') - REQUIRED |
| `database_server` | class | Appropriate database server class (MySQLServer or PostgreSQLServer) |
| `database_config` | dict | Configuration dict for the current environment |
| `database_connection` | async | Real database connection (for integration tests) |

### Using Environment-Aware Fixtures

```python
import pytest

@pytest.mark.asyncio
async def test_database_operations(database_server, database_config):
    """This test will use MySQL in local mode, PostgreSQL in prod mode."""
    server = database_server(**database_config)
    await server.connect()
    
    # Your test code here
    assert server.is_connected
    
    await server.disconnect()
```

## Running Tests in Different Scenarios

### Local Development (MySQL)
```bash
# Run all unit tests (no DB required)
pytest --db-env local tests/unit -m "not integration"

# Run unit + integration tests with local MySQL
pytest --db-env local tests/ -m "not slow"

# Run specific unit test
pytest --db-env local tests/unit/test_mysql_connection.py -v
```

### Production Testing (PostgreSQL)
```bash
# Run all unit tests with prod configuration
pytest --db-env prod tests/unit -m "not integration"

# Run unit + integration tests with production PostgreSQL
pytest --db-env prod tests/ -m "not slow"

# Run specific prod test
pytest --db-env prod tests/unit/test_postgresql_connection.py -v
```

### Only Integration Tests

Integration tests are organized by environment:

```bash
# Local (MySQL) integration tests
pytest --db-env local tests/integration/test_database_connections_local.py

# Production (PostgreSQL) integration tests
pytest --db-env prod tests/integration/test_database_connections_prod.py

# All integration tests in local environment
pytest --db-env local tests/integration/ -m integration

# All integration tests in prod environment
pytest --db-env prod tests/integration/ -m integration

# Shared compatibility tests
pytest --db-env local tests/integration/test_database_connections.py
pytest --db-env prod tests/integration/test_database_connections.py
```

### All Markers Combined
```bash
# Local unit tests, skipping slow tests
pytest --db-env local -m "unit and not slow"

# Prod async tests
pytest --db-env prod -m asyncio

# Both with various filters
pytest --db-env local -k "health_check" -v
pytest --db-env prod -k "connection" --tb=short
```

## Environment Variables

The following environment variables control test behavior:

### Database Configuration

**Local (MySQL):**
```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=test_password
MYSQL_DB=test_db
```

**Production (PostgreSQL):**
```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=test_db
```

### Test Environment Control

```bash
# Set test environment (REQUIRED)
TEST_ENV=local    # Use MySQL
TEST_ENV=prod     # Use PostgreSQL
```

## Quick Reference

| Task | Command |
|------|---------|
| Run all local tests | `pytest --db-env local` |
| Run all prod tests | `pytest --db-env prod` |
| Run local unit tests only | `pytest --db-env local tests/unit -m "not integration"` |
| Run prod unit tests only | `pytest --db-env prod tests/unit -m "not integration"` |
| Run with verbose output (local) | `pytest --db-env local -v` |
| Run specific file (local) | `pytest --db-env local tests/unit/test_mysql_connection.py` |
| Run tests matching pattern (prod) | `pytest --db-env prod -k "health_check"` |
| Show test coverage (local) | `pytest --db-env local --cov=source` |
| Using helper script (local) | `./run_tests_env.sh local` |
| Using helper script (prod) | `./run_tests_env.sh prod` |

## Troubleshooting

### "TEST ENVIRONMENT NOT SPECIFIED" error

**Cause**: You didn't specify `--db-env local`, `--db-env prod`, or `TEST_ENV` environment variable

**Solution**: Always add `--db-env local` or `--db-env prod` to your pytest command:
```bash
pytest --db-env local tests/
```

### "Connect call failed" errors

This typically means the database service isn't running. For integration tests:

**Local (MySQL):**
```bash
# Start MySQL (if using Docker)
docker-compose -f docker-compose.local.yml up mysql
```

**Production (PostgreSQL):**
```bash
# Start PostgreSQL (if using Docker)
docker-compose -f docker-compose.local.yml up postgres
```

### ModuleNotFoundError for database packages

Ensure all dependencies are installed:
```bash
uv sync
```

### Tests are being skipped

If you see tests being skipped, verify:

1. Tests are marked correctly:
   ```bash
   pytest --markers | grep -E "local|prod"
   ```

2. The environment is set correctly:
   ```bash
   echo $TEST_ENV  # Should show 'local' or 'prod'
   ```

## CI/CD Integration

For continuous integration pipelines:

```yaml
# Example GitHub Actions
jobs:
  test-local:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pytest --db-env local tests/unit

  test-prod:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pytest --db-env prod tests/unit
```

## Best Practices

1. **Always specify environment**: Never run `pytest` without `--db-env local` or `--db-env prod`
2. **Mark environment-specific tests**: Use `@pytest.mark.local` or `@pytest.mark.prod` for tests that only work with specific backends
3. **Use shared fixtures for integration**: When possible, use the `database_connection` fixture so tests work in both environments
4. **Run unit tests first**: Unit tests should pass regardless of `--db-env` setting
5. **Document backend dependencies**: Add comments to tests that require specific database features
6. **Keep backends in sync**: When updating schemas, update both MySQL and PostgreSQL versions
7. **Use the helper script**: `./run_tests_env.sh local` is easier to remember and validate than typing full pytest commands

## Test Markers

Tests can be marked with `@pytest.mark.local` or `@pytest.mark.prod` to specify which environment they should run in.

### Marking Tests for Specific Environments

```python
import pytest

# This test runs only in local environment (MySQL)
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_specific_feature():
    pass

# This test runs only in production environment (PostgreSQL)
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_specific_feature():
    pass

# This test runs in both environments (default)
@pytest.mark.asyncio
async def test_shared_functionality():
    pass
```

## Environment-Aware Fixtures

The test framework provides environment-aware fixtures that automatically use the correct database backend:

### Fixtures Available

| Fixture | Type | Description |
|---------|------|-------------|
| `test_environment` | str | Current test environment ('local', 'prod', or 'auto') |
| `database_server` | class | Appropriate database server class (MySQLServer or PostgreSQLServer) |
| `database_config` | dict | Configuration dict for the current environment |
| `database_connection` | async | Real database connection (for integration tests) |

### Using Environment-Aware Fixtures

```python
import pytest

@pytest.mark.asyncio
async def test_database_operations(database_server, database_config):
    """This test will use MySQL in local mode, PostgreSQL in prod mode."""
    server = database_server(**database_config)
    await server.connect()
    
    # Your test code here
    assert server.is_connected
    
    await server.disconnect()
```

## Running Tests in Different Scenarios

### Local Development (MySQL)
```bash
# Run all unit tests (no DB required)
TEST_ENV=local uv run pytest tests/unit -m "not integration"

# Run unit + integration tests with local MySQL
TEST_ENV=local uv run pytest tests/ -m "not slow"

# Run specific unit test
TEST_ENV=local uv run pytest tests/unit/test_mysql_connection.py -v
```

### Production Testing (PostgreSQL)
```bash
# Run all unit tests with prod configuration
TEST_ENV=prod uv run pytest tests/unit -m "not integration"

# Run unit + integration tests with production PostgreSQL
TEST_ENV=prod uv run pytest tests/ -m "not slow"

# Run specific prod test
TEST_ENV=prod uv run pytest tests/unit/test_postgresql_connection.py -v
```

### Testing Both Backends
```bash
# Run all tests without specifying environment (auto mode)
uv run pytest

# Run unit tests across both backends
uv run pytest tests/unit -m "not integration"

# Run with verbose output
uv run pytest -v
```

### Only Integration Tests
```bash
# Local integration tests only
TEST_ENV=local uv run pytest tests/integration -m integration

# Prod integration tests only
TEST_ENV=prod uv run pytest tests/integration -m integration

# Both
uv run pytest tests/integration -m integration
```

## Environment Variables

The following environment variables control test behavior:

### Database Configuration

**Local (MySQL):**
```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=test_password
MYSQL_DB=test_db
```

**Production (PostgreSQL):**
```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=test_db
```

### Test Environment Control

```bash
# Set test environment
TEST_ENV=local    # Use MySQL
TEST_ENV=prod     # Use PostgreSQL
TEST_ENV=auto     # Use both (default)
```

## Quick Reference

| Task | Command |
|------|---------|
| Run all tests (both envs) | `uv run pytest` |
| Run unit tests only | `uv run pytest tests/unit -m "not integration"` |
| Run local (MySQL) tests | `TEST_ENV=local uv run pytest` |
| Run prod (PostgreSQL) tests | `TEST_ENV=prod uv run pytest` |
| Run with verbose output | `uv run pytest -v` |
| Run specific file | `uv run pytest tests/unit/test_mysql_connection.py` |
| Run tests matching pattern | `uv run pytest -k "health_check"` |
| Show test coverage | `uv run pytest --cov=source` |

## Troubleshooting

### Tests are being skipped in environment mode

If you see tests being skipped, verify:

1. Tests are marked correctly:
   ```bash
   uv run pytest --markers | grep -E "local|prod"
   ```

2. The `TEST_ENV` variable is set correctly:
   ```bash
   echo $TEST_ENV  # Should show 'local', 'prod', or be empty (auto)
   ```

3. Database configuration environment variables match your setup

### "Connect call failed" errors

This typically means the database service isn't running. For integration tests:

**Local (MySQL):**
```bash
# Start MySQL (if using Docker)
docker-compose -f docker-compose.local.yml up mysql
```

**Production (PostgreSQL):**
```bash
# Start PostgreSQL (if using Docker)
docker-compose -f docker-compose.local.yml up postgres
```

### ModuleNotFoundError for database packages

Ensure all dependencies are installed:
```bash
uv sync
```

## CI/CD Integration

For continuous integration pipelines:

```yaml
# Example GitHub Actions
jobs:
  test-local:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: |
          TEST_ENV=local uv run pytest tests/ -m "not integration"

  test-prod:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: |
          TEST_ENV=prod uv run pytest tests/ -m "not integration"
```

## Best Practices

1. **Mark environment-specific tests**: Use `@pytest.mark.local` or `@pytest.mark.prod` for tests that only work with specific backends
2. **Use shared fixtures for integration**: When possible, use the `database_connection` fixture so tests work in both environments
3. **Run unit tests first**: Unit tests should pass regardless of `TEST_ENV` setting
4. **Document backend dependencies**: Add comments to tests that require specific database features
5. **Keep backends in sync**: When updating schemas, update both MySQL and PostgreSQL versions
