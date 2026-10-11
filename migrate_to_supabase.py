#!/usr/bin/env python
"""Migrate data from local Postgres to Supabase.

Usage:
  uv run python migrate_to_supabase.py  # Copy data from local to Supabase
  uv run python migrate_to_supabase.py --init-only  # Only create tables in Supabase (no data copy)
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def get_local_conn():
    """Connect to local Postgres Docker."""
    import psycopg
    return psycopg.connect("postgresql://digest:digest@localhost:5432/digest")


def get_supabase_conn():
    """Connect to Supabase."""
    import psycopg
    
    # Read SUPABASE_DATABASE_URL from env, even if not loaded by config
    url = os.getenv("SUPABASE_DATABASE_URL")
    # If not in current env, try to read from a backup or ask user
    if not url:
        raise RuntimeError(
            "SUPABASE_DATABASE_URL not set in environment. "
            "Add it to .env temporarily to run migration."
        )
    return psycopg.connect(url)


def init_supabase_schema(conn):
    """Create all tables in Supabase (skip if they exist)."""
    schema_sql = Path(__file__).parent / "schema.sql"
    sql = schema_sql.read_text()
    with conn.cursor() as cur:
        try:
            cur.execute(sql)
        except Exception as e:
            if "already exists" in str(e):
                print("  (schema already exists, skipping)")
            else:
                raise
    conn.commit()
    print("✓ Supabase schema ready")


def migrate_data(local_conn, supabase_conn):
    """Copy all data from local Postgres to Supabase."""
    tables = ["users", "sources", "items", "digests", "digest_items"]
    
    # Columns to exclude (generated columns)
    exclude_cols = {
        "items": ["tsv"],  # generated tsvector
    }
    
    for table in tables:
        with local_conn.cursor() as local_cur:
            local_cur.execute(f"SELECT * FROM {table}")
            rows = local_cur.fetchall()
            all_col_names = [desc[0] for desc in local_cur.description]
        
        # Filter excluded columns
        excl = exclude_cols.get(table, [])
        col_names = [c for c in all_col_names if c not in excl]
        
        if not rows:
            print(f"  {table}: 0 rows (skipped)")
            continue
        
        # Filter row values to match column names
        filtered_rows = []
        for row in rows:
            filtered_row = tuple(v for k, v in zip(all_col_names, row) if k not in excl)
            filtered_rows.append(filtered_row)
        
        # Insert into Supabase
        with supabase_conn.cursor() as sup_cur:
            cols = ", ".join(col_names)
            placeholders = ", ".join(["%s"] * len(col_names))
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            sup_cur.executemany(sql, filtered_rows)
        supabase_conn.commit()
        print(f"  {table}: {len(filtered_rows)} rows")
    
    print("✓ Data migrated")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-only", action="store_true", help="Only init schema, skip data")
    args = parser.parse_args()
    
    print("Connecting to Supabase...")
    try:
        sup_conn = get_supabase_conn()
    except Exception as e:
        print(f"✗ Failed to connect to Supabase: {e}")
        sys.exit(1)
    
    try:
        print("Initializing Supabase schema...")
        init_supabase_schema(sup_conn)
        
        if not args.init_only:
            print("Connecting to local Postgres...")
            local_conn = get_local_conn()
            try:
                print("Migrating data...")
                migrate_data(local_conn, sup_conn)
            finally:
                local_conn.close()
        
        print("\n✓ Migration complete!")
    finally:
        sup_conn.close()


if __name__ == "__main__":
    main()
