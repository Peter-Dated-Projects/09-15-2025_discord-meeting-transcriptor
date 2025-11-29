# Development Setup Guide

This guide will help you set up your development environment for the Discord Meeting Transcriptor bot.

## 1. Prerequisites

- Python 3.10+
- `uv` package manager (`pip install uv`)
- `git`
- A Discord Bot Token ([how to get one](https://discord.com/developers/applications))
- Docker (for running PostgreSQL and other services)

## 2. Initial Project Setup

```bash
# Clone the repository
git clone https://github.com/Peter-Dated-Projects/09-15-2025_discord-meeting-transcriptor.git
cd 09-15-2025_discord-meeting-transcriptor

# Create a virtual environment and install all dependencies
uv pip install -e ".[dev]"

# Set up pre-commit hooks for code quality
uv run pre-commit install
```

## 3. Environment Configuration

The bot uses a `.env` file for configuration.

```bash
# Create your .env file from the example
cp .env.example .env
```

Now, open `.env` and add your `DISCORD_API_TOKEN`. You can also configure database settings and other options.

## 4. Running Dependent Services

This project requires external services like PostgreSQL and Whisper to run. The easiest way to manage these is with Docker.

```bash
# Start all services (PostgreSQL, ChromaDB, etc.) in the background
docker-compose -f docker-compose.local.yml up -d
```
*Note: The Whisper transcription service can also be run locally. See the `README.md` for instructions.*

## 5. Running the Bot for Development

To run the bot with automatic reloading when you make code changes:

```bash
# Run the bot in development mode
make dev
```

## 6. Development Workflow & Commands

This project uses `make` for common development tasks. Run `make help` to see all available commands.

### The Edit-Lint-Test Cycle

1.  **Write Code**: Make your changes in the `source/` or `cogs/` directories.
2.  **Format & Lint**: Before committing, ensure your code meets our quality standards.
    ```bash
    # Auto-format your code
    make format

    # Run all linters and quality checks
    make lint
    ```
3.  **Test**: Run the test suite to make sure your changes didn't break anything.
    ```bash
    # Run all tests
    make test

    # Run tests with a coverage report
    make test-cov
    ```

### Committing Your Changes

This project uses **pre-commit hooks** that will automatically run `make format` and `make lint` on the files you've changed. If the hooks fail, review the output, fix the issues, and `git add` your files again before re-running `git commit`.

To bypass hooks (not recommended): `git commit --no-verify`.

### Useful `make` commands

-   `make check-all`: Run all formatters, linters, and tests.
-   `make type-check`: Run MyPy for static type checking.
-   `make clean`: Remove cache and build files.

## 7. IDE Setup (VS Code Recommended)

Install these VS Code extensions for the best experience:
- `ms-python.python` (Python)
- `charliermarsh.ruff` (Ruff)
- `ms-python.black-formatter` (Black Formatter)
- `ms-python.mypy-type-checker` (Mypy Type Checker)

These extensions will automatically use the project's `pyproject.toml` file to format and lint your code as you save it.

## 8. Testing in Detail

-   **Location**: All tests are in the `tests/` directory.
-   **Framework**: We use `pytest`.
-   **Running Tests**:
    ```bash
    # Run all tests
    make test

    # Run a specific file
    uv run pytest tests/unit/services/test_rag.py

    # Run a specific test by name
    uv run pytest -k "test_specific_behavior"
    ```
-   **Test Markers**:
    -   `@pytest.mark.unit`: Fast, isolated unit tests.
    -   `@pytest.mark.integration`: Tests requiring external services (like a database).
    -   Run specific markers: `uv run pytest -m unit`

## 9. Dependency Management

Dependencies are managed in `pyproject.toml` under the `[project]` and `[project.optional-dependencies]` sections.

-   **Production `dependencies`**: Required to run the bot.
-   **`dev` dependencies**: Required for testing, linting, and development.

To add a new dependency:

1.  Add the package to the appropriate list in `pyproject.toml`.
2.  Re-install the dependencies:
    ```bash
    # If you added a production dependency
    uv pip install -e .

    # If you added a development dependency
    uv pip install -e ".[dev]"
    ```