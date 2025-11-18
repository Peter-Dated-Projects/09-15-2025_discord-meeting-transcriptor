#!/usr/bin/env python3
"""
Formatting script for the project.
Runs ruff, black, and isort to automatically fix formatting issues.
"""

import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], description: str) -> bool:
    """
    Run a command and return whether it succeeded.

    Args:
        command: Command to run as a list of strings
        description: Description of what the command does

    Returns:
        True if command succeeded, False otherwise
    """
    print(f"\n{'=' * 80}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(command)}")
    print(f"{'=' * 80}\n")

    result = subprocess.run(command, cwd=Path(__file__).parent)

    if result.returncode == 0:
        print(f"\n✅ {description} completed\n")
        return True
    else:
        print(f"\n❌ {description} failed\n")
        return False


def main() -> int:
    """
    Run all formatting fixes.

    Returns:
        0 if all formatting succeeds, 1 if any formatting fails
    """
    # Directories to format
    targets = ["source", "cogs", "tests", "format.py", "main.py", "playground"]

    formatters = [
        # Ruff fix (auto-fix issues)
        (["ruff", "check", "--fix"] + targets, "Ruff auto-fix"),
        # isort (sort imports)
        (["isort"] + targets, "isort import sorting"),
        # Black (format code)
        (["black"] + targets, "Black code formatting"),
    ]

    results = []
    for command, description in formatters:
        results.append(run_command(command, description))

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}\n")

    for (_, description), passed in zip(formatters, results):
        status = "✅ COMPLETED" if passed else "❌ FAILED"
        print(f"{status}: {description}")

    if all(results):
        print("\n🎉 All formatting completed successfully!\n")
        return 0
    else:
        print("\n⚠️  Some formatting operations failed.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
