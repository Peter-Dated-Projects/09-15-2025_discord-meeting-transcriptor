#!/usr/bin/env bash
set -euo pipefail

# run_dev.sh - robust developer run script with optional auto-reload
# Tries watchers in this order: watchfiles CLI, fd+entr, nodemon.
# If none are found it will run the app once and print instructions.

# Allow override: DEV_WATCHER environment variable can be set to 'watchfiles',
# 'fd-entr', 'nodemon' or 'none' to force behaviour.
DEV_CHOICE=${DEV_WATCHER:-}

# require `uv` runner and create a venv if missing
if command -v uv >/dev/null 2>&1; then
	# if a virtualenv directory doesn't exist, create it using `uv venv`
	if [ ! -d ".venv" ]; then
		echo "Virtualenv '.venv' not found — creating with: uv venv -p 3.10"
		uv venv -p 3.10
	fi
	EXEC_STR="uv run"
	echo "Using 'uv' runner: $EXEC_STR"
else
	echo "ERROR: 'uv' is required but not found on PATH. Please install 'uv' and try again." >&2
	exit 1
fi

run_watchfiles() {
	echo "Using watchfiles CLI (watchfiles) to auto-reload"
	# Ignore build/cache dirs to prevent infinite rebuild loops when uv installs/builds.
	# Use --ignore-paths for each directory to exclude, and --target-type command with --args.
	exec watchfiles \
		--ignore-paths .venv \
		--ignore-paths .git \
		--ignore-paths .uv \
		--ignore-paths build \
		--ignore-paths dist \
		--ignore-paths "*.egg-info" \
		--ignore-paths __pycache__ \
		--ignore-paths .pytest_cache \
		--target-type command \
		"$EXEC_STR main.py"
}

run_fd_entr() {
	echo "Using fd + entr to auto-reload"
	# entr expects the command and args; unquoted expansion is fine here
	exec fd -e py | entr -r $EXEC_STR main.py
}

run_nodemon() {
	echo "Using nodemon to auto-reload"
	exec nodemon --ext py --exec "$EXEC_STR main.py"
}

case "$DEV_CHOICE" in
	watchfiles)
		if command -v watchfiles >/dev/null 2>&1; then
			run_watchfiles
		else
			echo "DEV_WATCHER=watchfiles specified but 'watchfiles' not found on PATH" >&2
			exit 1
		fi
		;;
	fd-entr)
		if command -v fd >/dev/null 2>&1 && command -v entr >/dev/null 2>&1; then
			run_fd_entr
		else
			echo "DEV_WATCHER=fd-entr specified but 'fd' and/or 'entr' not found on PATH" >&2
			exit 1
		fi
		;;
	nodemon)
		if command -v nodemon >/dev/null 2>&1; then
			run_nodemon
		else
			echo "DEV_WATCHER=nodemon specified but 'nodemon' not found on PATH" >&2
			exit 1
		fi
		;;
		none)
			echo "DEV_WATCHER=none specified; running one-shot $EXEC_STR main.py"
			exec $EXEC_STR main.py
		;;
	"")
		# auto-detect preferred watcher (prefer fd+entr to avoid watchfiles rebuild loop with uv)
		if command -v fd >/dev/null 2>&1 && command -v entr >/dev/null 2>&1; then
			run_fd_entr
		elif command -v watchfiles >/dev/null 2>&1; then
			run_watchfiles
		elif command -v nodemon >/dev/null 2>&1; then
			run_nodemon
			else
				echo "No file-watcher detected. Running $EXEC_STR main.py once."
			echo "Install one of the following for auto-reload:"
			echo "  - watchfiles (python package)"
			echo "  - fd + entr (macOS: brew install fd entr)"
			echo "  - nodemon (npm install -g nodemon)"
				exec $EXEC_STR main.py
		fi
		;;
	*)
		echo "Unknown DEV_WATCHER value: $DEV_CHOICE" >&2
		exit 1
		;;
esac
