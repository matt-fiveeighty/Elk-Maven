import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create a SQLite connection with WAL mode and foreign keys enabled."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database(db_path: str) -> sqlite3.Connection:
    """Initialize the database: create tables, indexes, FTS, and triggers."""
    conn = get_connection(db_path)
    schema_sql = SCHEMA_PATH.read_text()

    # Remove PRAGMA lines (already set by get_connection) then use executescript
    # which correctly handles multi-statement SQL including triggers with BEGIN/END
    lines = schema_sql.splitlines()
    filtered = "\n".join(l for l in lines if not l.strip().upper().startswith("PRAGMA"))
    conn.executescript(filtered)

    # Run any pending migrations
    from .migrator import run_migrations
    run_migrations(conn)

    logger.info(f"Database initialized at {db_path}")
    return conn
