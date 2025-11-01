#!/usr/bin/env python3
"""
Linting script for the project.
Runs ruff, black, and isort to auto-fix issues by default.
Pass --check flag to only check without modifying files.
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
    Run all linting and formatting.

    Returns:
        0 if all operations succeed, 1 if any operation fails
    """
    # Check if --check flag is passed
    check_only = "--check" in sys.argv

    # Directories to lint
    targets = ["source", "cogs", "tests", "lint.py", "format.py", "main.py", "playground.py"]

    if check_only:
        print("\n🔍 Running in CHECK-ONLY mode (no files will be modified)\n")
        operations = [
            # Ruff check
            (["ruff", "check"] + targets, "Ruff linting"),
            # Black check (without modifying files)
            (["black", "--check"] + targets, "Black formatting check"),
            # isort check (without modifying files)
            (["isort", "--check-only"] + targets, "isort import sorting check"),
        ]
    else:
        print("\n🔧 Running in AUTO-FIX mode (files will be modified)\n")
        operations = [
            # Ruff fix (auto-fix issues)
            (["ruff", "check", "--fix"] + targets, "Ruff auto-fix"),
            # isort (sort imports)
            (["isort"] + targets, "isort import sorting"),
            # Black (format code)
            (["black"] + targets, "Black code formatting"),
        ]

    results = []
    for command, description in operations:
        results.append(run_command(command, description))

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}\n")

    for (_, description), passed in zip(operations, results):
        status = "✅ COMPLETED" if passed else "❌ FAILED"
        print(f"{status}: {description}")

    if all(results):
        if check_only:
            print("\n🎉 All linting checks passed!\n")
        else:
            print("\n🎉 All formatting completed successfully!\n")
        return 0
    else:
        if check_only:
            print(
                "\n⚠️  Some linting checks failed. Run 'uv run lint.py' (without --check) to auto-fix.\n"
            )
        else:
            print("\n⚠️  Some operations failed. Please review the errors above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
