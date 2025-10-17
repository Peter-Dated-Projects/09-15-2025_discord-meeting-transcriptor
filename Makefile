.PHONY: help install install-dev setup clean lint format type-check test test-cov run dev pre-commit-install pre-commit-run

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo '$(BLUE)Available commands:$(NC)'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

install: ## Install production dependencies
	@echo "$(BLUE)Installing production dependencies...$(NC)"
	pip install -r requirements.txt
	@echo "$(GREEN)✓ Production dependencies installed$(NC)"

install-dev: ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	pip install -r requirements.txt
	pip install -r requirements-dev.txt
	@echo "$(GREEN)✓ Development dependencies installed$(NC)"

setup: install-dev pre-commit-install ## Setup development environment
	@echo "$(GREEN)✓ Development environment setup complete!$(NC)"
	@echo "$(YELLOW)Don't forget to create your .env file with DISCORD_API_TOKEN$(NC)"

clean: ## Clean up cache and build artifacts
	@echo "$(BLUE)Cleaning up...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

lint: ## Run ruff linter (check only)
	@echo "$(BLUE)Running ruff linter...$(NC)"
	ruff check .
	@echo "$(GREEN)✓ Linting complete$(NC)"

lint-fix: ## Run ruff linter and auto-fix issues
	@echo "$(BLUE)Running ruff linter with auto-fix...$(NC)"
	ruff check --fix .
	@echo "$(GREEN)✓ Linting with fixes complete$(NC)"

format: ## Format code with black and ruff
	@echo "$(BLUE)Formatting code...$(NC)"
	black .
	ruff format .
	ruff check --fix --select I .
	@echo "$(GREEN)✓ Code formatted$(NC)"

format-check: ## Check code formatting without making changes
	@echo "$(BLUE)Checking code formatting...$(NC)"
	black --check .
	ruff format --check .
	@echo "$(GREEN)✓ Format check complete$(NC)"

type-check: ## Run mypy type checker
	@echo "$(BLUE)Running type checker...$(NC)"
	mypy .
	@echo "$(GREEN)✓ Type checking complete$(NC)"

security: ## Run security checks with bandit
	@echo "$(BLUE)Running security checks...$(NC)"
	bandit -r . -c pyproject.toml
	@echo "$(GREEN)✓ Security check complete$(NC)"

test: ## Run tests with pytest
	@echo "$(BLUE)Running tests...$(NC)"
	pytest
	@echo "$(GREEN)✓ Tests complete$(NC)"

test-cov: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	pytest --cov --cov-report=html --cov-report=term
	@echo "$(GREEN)✓ Tests with coverage complete$(NC)"
	@echo "$(YELLOW)View detailed report: open htmlcov/index.html$(NC)"

test-quick: ## Run tests without coverage (faster)
	@echo "$(BLUE)Running quick tests...$(NC)"
	pytest -v --tb=short
	@echo "$(GREEN)✓ Quick tests complete$(NC)"

pre-commit-install: ## Install pre-commit hooks
	@echo "$(BLUE)Installing pre-commit hooks...$(NC)"
	pre-commit install
	@echo "$(GREEN)✓ Pre-commit hooks installed$(NC)"

pre-commit-run: ## Run pre-commit hooks on all files
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit checks complete$(NC)"

pre-commit-update: ## Update pre-commit hooks to latest versions
	@echo "$(BLUE)Updating pre-commit hooks...$(NC)"
	pre-commit autoupdate
	@echo "$(GREEN)✓ Pre-commit hooks updated$(NC)"

check-all: format lint type-check test ## Run all checks (format, lint, type-check, test)
	@echo "$(GREEN)✓ All checks passed!$(NC)"

run: ## Run the Discord bot
	@echo "$(BLUE)Starting Discord bot...$(NC)"
	python main.py

dev: ## Run the bot with auto-reload on file changes
	@echo "$(BLUE)Starting Discord bot in development mode...$(NC)"
	@echo "$(YELLOW)Watching for file changes...$(NC)"
	watchfiles --ignore ".venv|.git|__pycache__|*.pyc" "python main.py"

dev-format: ## Run bot with auto-reload and format on save
	@echo "$(BLUE)Starting Discord bot with auto-format...$(NC)"
	@while true; do \
		watchfiles --ignore ".venv|.git|__pycache__|*.pyc" "make format && python main.py"; \
		sleep 1; \
	done

requirements-update: ## Update requirements.txt from current environment
	@echo "$(BLUE)Updating requirements.txt...$(NC)"
	pip freeze > requirements.txt
	@echo "$(GREEN)✓ Requirements updated$(NC)"

show-deps: ## Show installed package versions
	@echo "$(BLUE)Installed packages:$(NC)"
	pip list

init-secrets: ## Initialize secrets baseline for detect-secrets
	@echo "$(BLUE)Initializing secrets baseline...$(NC)"
	detect-secrets scan > .secrets.baseline
	@echo "$(GREEN)✓ Secrets baseline created$(NC)"

# Quick aliases
fmt: format ## Alias for format
tc: type-check ## Alias for type-check
t: test ## Alias for test
r: run ## Alias for run
d: dev ## Alias for dev
