# Development Setup Guide

This guide will help you set up your development environment for the Discord Meeting Transcriptor bot.

## Prerequisites

- Python 3.13+
- pip
- git
- Discord Bot Token

## Quick Setup

```bash
# 1. Install all development dependencies
make install-dev

# 2. Install pre-commit hooks
make pre-commit-install

# 3. Create your .env file
cp .env.example .env
# Edit .env and add your DISCORD_API_TOKEN

# 4. Run the bot
make dev
```

## Manual Setup

If you prefer to set up manually:

```bash
# Install production dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

## Available Commands

Run `make help` to see all available commands. Here are the most useful ones:

### Code Quality
```bash
make format         # Format code with black and ruff
make lint           # Check code with ruff linter
make lint-fix       # Fix linting issues automatically
make type-check     # Run mypy type checking
make security       # Run security checks with bandit
make check-all      # Run all checks (format, lint, type-check, test)
```

### Testing
```bash
make test           # Run tests
make test-cov       # Run tests with coverage report
make test-quick     # Quick tests without coverage
```

### Development
```bash
make run            # Run the bot
make dev            # Run bot with auto-reload (recommended for development)
make clean          # Clean up cache and build artifacts
```

### Pre-commit
```bash
make pre-commit-run     # Run pre-commit on all files
make pre-commit-update  # Update pre-commit hooks
```

## Pre-commit Hooks

Pre-commit hooks run automatically before each commit to ensure code quality. They will:

1. ✨ Format your code with Black and Ruff
2. 🔍 Lint your code with Ruff
3. 🔒 Check for security issues with Bandit
4. 🔑 Scan for accidentally committed secrets
5. 📝 Check file formatting (trailing whitespace, line endings, etc.)
6. ⚡ Run type checks with MyPy

If any check fails, the commit will be blocked. Fix the issues and try again.

### Bypassing Pre-commit (Not Recommended)

In rare cases where you need to commit without running hooks:
```bash
git commit --no-verify -m "Your message"
```

## IDE Setup

### VS Code

Install these recommended extensions:
- Python (ms-python.python)
- Ruff (charliermarsh.ruff)
- Black Formatter (ms-python.black-formatter)
- Mypy Type Checker (ms-python.mypy-type-checker)
- EditorConfig (editorconfig.editorconfig)

The `.editorconfig` file will automatically configure formatting in VS Code.

### PyCharm

PyCharm should automatically detect the `pyproject.toml` configuration. Make sure to:
1. Set Python 3.13 as your interpreter
2. Enable "Optimize imports on the fly"
3. Enable "Reformat code on save" (optional)

## Configuration Files

- **`pyproject.toml`** - Central configuration for all Python tools (ruff, black, mypy, pytest, coverage)
- **`.pre-commit-config.yaml`** - Pre-commit hooks configuration
- **`.editorconfig`** - Editor configuration for consistent formatting
- **`Makefile`** - Convenient commands for development tasks
- **`mypy.ini`** - ⚠️ DEPRECATED - Configuration moved to `pyproject.toml`

## Code Style

This project uses:
- **Black** for code formatting (88 character line length)
- **Ruff** for linting and import sorting
- **MyPy** for static type checking

All code should be:
- Formatted with Black
- Pass Ruff linting
- Include type hints for function parameters and return values
- Pass MyPy type checking (where practical)

## Testing

Tests should be placed in the `tests/` directory (to be created). We use:
- **pytest** for test framework
- **pytest-asyncio** for async tests
- **pytest-cov** for coverage reports

Run tests before committing:
```bash
make test
```

## Security

Security is important! The pre-commit hooks include:
- **Bandit** - Scans for common security issues
- **detect-secrets** - Prevents accidentally committing secrets

To initialize the secrets baseline (first time only):
```bash
make init-secrets
```

## Troubleshooting

### Pre-commit hooks fail

If hooks fail, read the error messages carefully. Common fixes:
```bash
# Update hooks to latest versions
make pre-commit-update

# Clean and reinstall
pre-commit clean
pre-commit install
```

### Import errors after installing packages

```bash
# Clean cache and restart
make clean
```

### MyPy errors with discord.py

The project is configured to ignore missing imports for discord.py. If you get type errors, they might be legitimate issues to fix.

## Contributing

Before submitting a pull request:

1. Run all checks: `make check-all`
2. Ensure tests pass: `make test-cov`
3. Update documentation if needed
4. Write meaningful commit messages

Happy coding! 🚀
