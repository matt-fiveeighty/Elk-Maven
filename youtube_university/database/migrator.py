from __future__ import annotations

"""Database migration runner. Applies numbered SQL migration files in order,
tracking which have been applied via the schema_version table."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations(conn):
    """Run all pending migrations in order."""
    # Ensure schema_version table exists
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Get current version
    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    current = row["v"] if row["v"] is not None else 0

    # Find and run pending migrations
    if not MIGRATIONS_DIR.exists():
        return

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for mf in migration_files:
        # Extract version number from filename like 001_description.sql
        try:
            version = int(mf.stem.split("_")[0])
        except (ValueError, IndexError):
            logger.warning(f"Skipping non-numbered migration file: {mf.name}")
            continue

        if version <= current:
            continue

        logger.info(f"Applying migration {version}: {mf.name}")
        sql = mf.read_text()
        # Strip PRAGMA lines (same pattern as main schema)
        lines = sql.splitlines()
        filtered = "\n".join(l for l in lines if not l.strip().upper().startswith("PRAGMA"))
        conn.executescript(filtered)

        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, mf.stem),
        )
        conn.commit()
        logger.info(f"Migration {version} applied successfully")
