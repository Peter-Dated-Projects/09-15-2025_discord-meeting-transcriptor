#!/usr/bin/env python3
"""
SQL Database Viewer Script

This script allows you to:
- Connect to the SQL database created by the constructor
- List out tables in the database (--list flag)
- List out items inside a specific table (--table {tablename} flag)

Usage:
    python scripts/sql_viewer.py --list
    python scripts/sql_viewer.py --table {tablename}
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add the parent directory to the path so we can import source modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from source.server.dev.mysql import MySQLServer


# -------------------------------------------------------------- #
# SQL Viewer Functions
# -------------------------------------------------------------- #


async def connect_to_db() -> MySQLServer:
    """Connect to the SQL database."""
    # Load environment variables
    load_dotenv(dotenv_path=".env.local")

    host = os.getenv("SQL_HOST")
    port = int(os.getenv("SQL_PORT", "3306"))
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    database = os.getenv("SQL_DATABASE")

    if not host or not user or not password or not database:
        raise ValueError("Missing required SQL environment variables in .env.local")

    # Create and connect to database
    sql_server = MySQLServer(host=host, port=port, user=user, password=password, database=database)
    await sql_server.connect()

    return sql_server


async def list_tables(sql_server: MySQLServer) -> None:
    """List all tables in the database."""
    print("\n" + "=" * 60)
    print("TABLES IN DATABASE")
    print("=" * 60)

    try:
        query = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = DATABASE();"
        results = await sql_server.query(query)

        if not results:
            print("No tables found in the database.")
            return

        print(f"\nFound {len(results)} table(s):\n")
        for i, row in enumerate(results, 1):
            table_name = row.get("TABLE_NAME", "Unknown")
            print(f"  {i}. {table_name}")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"Error listing tables: {e}")


async def list_table_contents(sql_server: MySQLServer, table_name: str) -> None:
    """List all items in a specific table."""
    print("\n" + "=" * 60)
    print(f"CONTENTS OF TABLE: {table_name}")
    print("=" * 60)

    try:
        # First, check if table exists
        check_query = f"""
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
        """
        table_exists = await sql_server.query(check_query)

        if not table_exists:
            print(f"\nError: Table '{table_name}' not found in the database.")
            return

        # Get the contents of the table
        query = f"SELECT * FROM {table_name}"
        results = await sql_server.query(query)

        if not results:
            print(f"\nTable '{table_name}' is empty.")
            print("=" * 60)
            return

        # Display results
        print(f"\nFound {len(results)} row(s):\n")

        # Print column headers
        if results:
            headers = list(results[0].keys())
            col_widths = [max(len(str(h)), 20) for h in headers]

            # Print header
            header_str = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
            print(header_str)
            print("-" * len(header_str))

            # Print rows
            for row in results:
                row_values = [str(row.get(h, "NULL")).ljust(w) for h, w in zip(headers, col_widths)]
                print(" | ".join(row_values))

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"Error listing table contents: {e}")


async def main():
    """Main function to parse arguments and execute commands."""
    parser = argparse.ArgumentParser(
        description="SQL Database Viewer - Connect to and view database contents"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all tables in the database",
    )

    parser.add_argument(
        "--table",
        type=str,
        help="List all items in a specific table",
        metavar="TABLENAME",
    )

    args = parser.parse_args()

    # Ensure at least one argument is provided
    if not args.list and not args.table:
        parser.print_help()
        sys.exit(1)

    try:
        # Connect to database
        print("Connecting to database...")
        sql_server = await connect_to_db()
        print("✓ Successfully connected to database")

        # Execute requested operation
        if args.list:
            await list_tables(sql_server)

        if args.table:
            await list_table_contents(sql_server, args.table)

        # Disconnect
        await sql_server.disconnect()
        print("\n✓ Disconnected from database")

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
