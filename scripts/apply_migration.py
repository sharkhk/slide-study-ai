#!/usr/bin/env python3
"""Apply a .sql migration to the Alimne Supabase Postgres database.

Usage:
    python scripts/apply_migration.py <path-to.sql> [more.sql ...]

Connection string is read (in priority order) from:
    1. env var  SUPABASE_DB_URL
    2. file     scripts/.db_url   (single line, gitignored — never committed)

Get the string from Supabase → Project Settings → Database → "Connection
string" → URI (use the Session/Transaction pooler URI; it embeds the password).
It looks like:
    postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres

Nothing is printed except statement status — the credential is never echoed.
"""
import os
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def _connect(dsn):
    """Return a live DB connection using whichever driver is installed."""
    try:
        import psycopg  # psycopg 3
        return ("psycopg3", psycopg.connect(dsn, autocommit=True))
    except ImportError:
        pass
    try:
        import psycopg2  # psycopg 2
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return ("psycopg2", conn)
    except ImportError:
        sys.exit("No Postgres driver found. Install one:\n"
                 "    pip install \"psycopg[binary]\"   (recommended)\n"
                 "  or\n"
                 "    pip install psycopg2-binary")


def _load_dsn():
    dsn = os.environ.get("SUPABASE_DB_URL", "").strip()
    if dsn:
        return dsn
    f = HERE / ".db_url"
    if f.exists():
        dsn = f.read_text(encoding="utf-8").strip()
        if dsn:
            return dsn
    sys.exit("No connection string. Set SUPABASE_DB_URL or create scripts/.db_url "
             "with the Supabase pooler URI (see the header of this file).")


def main(argv):
    if not argv:
        sys.exit("Usage: python scripts/apply_migration.py <file.sql> [more.sql ...]")
    files = [pathlib.Path(a) for a in argv]
    for f in files:
        if not f.exists():
            sys.exit(f"Not found: {f}")

    dsn = _load_dsn()
    driver, conn = _connect(dsn)
    print(f"Connected via {driver}.")
    try:
        with conn.cursor() as cur:
            for f in files:
                sql = f.read_text(encoding="utf-8")
                print(f"\n── applying {f} ({len(sql)} bytes) ──")
                cur.execute(sql)
                # Surface any RETURNING / SELECT output from the last statement.
                try:
                    rows = cur.fetchall()
                    if rows:
                        print("result:", rows)
                except Exception:
                    pass
                print(f"✓ applied {f}")
    finally:
        conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main(sys.argv[1:])
