# Database Connection Tests

This directory contains comprehensive pytest tests for verifying PostgreSQL and MySQL database connections.

## Test Structure

### Unit Tests

Located in `tests/unit/`:

- **`test_postgresql_connection.py`** - Tests PostgreSQL connection handling
  - Initialization with various parameter combinations
  - Connection pool creation and management
  - Health checks
  - Error handling
  - Environment variable fallback

- **`test_mysql_connection.py`** - Tests MySQL connection handling
  - Initialization with various parameter combinations
  - Connection pool creation and management
  - Health checks
  - Error handling
  - Environment variable fallback

### Integration Tests

Located in `tests/integration/`:

- **`test_database_connections.py`** - Tests actual database connections
  - Real PostgreSQL connection (requires running instance)
  - Real MySQL connection (requires running instance)
  - Query execution
  - Connection failure scenarios
  - Independent connections for both databases

## Running the Tests

### Run All Unit Tests (Mocked)

```bash
pytest tests/unit/ -v
```

### Run Only PostgreSQL Unit Tests

```bash
pytest tests/unit/test_postgresql_connection.py -v
```

### Run Only MySQL Unit Tests

```bash
pytest tests/unit/test_mysql_connection.py -v
```

### Run Integration Tests (Requires Running Databases)

```bash
pytest tests/integration/ -v -m integration
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ --cov=source/server --cov-report=html
```

## Environment Variables

For integration tests, the following environment variables can be set:

### PostgreSQL

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
export POSTGRES_DB=postgres
```

### MySQL

```bash
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_PASSWORD=root
export MYSQL_DB=mysql
```

## Running Databases Locally

### PostgreSQL with Docker

```bash
./run_docker_compose.sh
```

Or manually:

```bash
docker run --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  -d postgres:15
```

### MySQL with Docker

```bash
docker run --name mysql \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=mysql \
  -p 3306:3306 \
  -d mysql:8.0
```

## Test Markers

Tests are marked with markers to allow selective running:

- `@pytest.mark.unit` - Unit tests (mocked)
- `@pytest.mark.integration` - Integration tests (require real databases)
- `@pytest.mark.asyncio` - Async tests

### Run Only Unit Tests (Skip Integration)

```bash
pytest tests/ -v -m "not integration"
```

### Run Only Integration Tests

```bash
pytest tests/ -v -m integration
```

## Test Coverage

### PostgreSQL Connection Tests

- ✅ Initialization with individual parameters
- ✅ Initialization with connection string
- ✅ Initialization with environment variables
- ✅ Successful connection establishment
- ✅ Connection failure handling
- ✅ Successful disconnection
- ✅ Disconnection without pool
- ✅ Disconnection failure handling
- ✅ Health check - healthy
- ✅ Health check - unhealthy
- ✅ Health check - no pool
- ✅ Health check - exception handling
- ✅ Connection pool retrieval
- ✅ Connection pool release on exception
- ✅ Connection string format validation

### MySQL Connection Tests

- ✅ Initialization with individual parameters
- ✅ Initialization with connection string
- ✅ Initialization with environment variables
- ✅ Successful connection establishment
- ✅ Connection failure handling
- ✅ Successful disconnection
- ✅ Disconnection without pool
- ✅ Disconnection failure handling
- ✅ Health check - healthy
- ✅ Health check - unhealthy
- ✅ Health check - no pool
- ✅ Health check - exception handling
- ✅ Connection pool retrieval
- ✅ Connection pool release on exception
- ✅ Connection string format validation

### Integration Tests

- ✅ Real PostgreSQL connection
- ✅ Real MySQL connection
- ✅ Query execution on PostgreSQL
- ✅ Query execution on MySQL
- ✅ Failed connection handling
- ✅ Independent database connections

## Troubleshooting

### Import Errors

If you see import errors, ensure:

1. The project root is in your Python path
2. All dependencies are installed: `pip install -e .`
3. pytest-asyncio is installed: `pip install pytest-asyncio`

### Connection Tests Failing

For integration tests failing:

1. Verify databases are running
2. Check environment variables are set correctly
3. Verify connection credentials
4. Check firewall/network connectivity

### Async Test Issues

If async tests fail:

- Ensure `pytest-asyncio` is installed
- Check that all async functions use `async def`
- Verify `@pytest.mark.asyncio` decorator is present

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: root
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=3
        ports:
          - 3306:3306

    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run unit tests
        run: pytest tests/unit/ -v

      - name: Run integration tests
        run: pytest tests/integration/ -v -m integration
        env:
          POSTGRES_HOST: localhost
          MYSQL_HOST: localhost
```

## Notes

- Unit tests use mocked database connections and can run without database instances
- Integration tests require actual database instances to be running
- All async tests require `pytest-asyncio` plugin
- Connection strings are built safely without SQL injection risks (using parameterized queries)
