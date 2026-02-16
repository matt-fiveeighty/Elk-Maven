"""Tests for database connection, schema init, and migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from youtube_university.database.connection import get_connection, init_database
from youtube_university.database.migrator import run_migrations


class TestConnection:
    def test_get_connection_creates_file(self, tmp_path):
        db_path = str(tmp_path / "new.db")
        conn = get_connection(db_path)
        assert Path(db_path).exists()
        conn.close()

    def test_get_connection_wal_mode(self, tmp_path):
        db_path = str(tmp_path / "wal.db")
        conn = get_connection(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_get_connection_foreign_keys_on(self, tmp_path):
        db_path = str(tmp_path / "fk.db")
        conn = get_connection(db_path)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        conn.close()

    def test_get_connection_row_factory(self, tmp_path):
        db_path = str(tmp_path / "rows.db")
        conn = get_connection(db_path)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_creates_parent_directories(self, tmp_path):
        db_path = str(tmp_path / "deep" / "nested" / "db.sqlite3")
        conn = get_connection(db_path)
        assert Path(db_path).exists()
        conn.close()


class TestInitDatabase:
    def test_creates_all_core_tables(self, tmp_path):
        db_path = str(tmp_path / "schema.db")
        conn = init_database(db_path)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in tables}

        expected = {
            "channels", "videos", "transcripts",
            "categories", "tags",
            "knowledge_entries", "knowledge_categories", "knowledge_tags", "video_tags",
            "processing_log",
            # Migration tables
            "schema_version",
            "bias_flags", "optimization_queue", "optimization_log",
            "chat_sessions", "chat_messages", "uploaded_images",
        }
        for t in expected:
            assert t in table_names, f"Missing table: {t}"
        conn.close()

    def test_creates_fts_tables(self, tmp_path):
        db_path = str(tmp_path / "fts.db")
        conn = init_database(db_path)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts%'"
        ).fetchall()
        fts_names = {r["name"] for r in tables}

        # FTS5 creates helper tables like knowledge_fts_content, etc.
        assert any("knowledge_fts" in n for n in fts_names)
        assert any("transcript_fts" in n for n in fts_names)
        assert any("video_fts" in n for n in fts_names)
        conn.close()

    def test_creates_triggers(self, tmp_path):
        db_path = str(tmp_path / "triggers.db")
        conn = init_database(db_path)

        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        trigger_names = {r["name"] for r in triggers}

        expected_triggers = {
            "knowledge_ai", "knowledge_ad", "knowledge_au",
            "transcript_ai", "transcript_ad",
            "video_ai", "video_ad", "video_au",
        }
        for t in expected_triggers:
            assert t in trigger_names, f"Missing trigger: {t}"
        conn.close()

    def test_idempotent(self, tmp_path):
        """Calling init_database twice should not fail."""
        db_path = str(tmp_path / "idem.db")
        conn1 = init_database(db_path)
        conn1.close()
        conn2 = init_database(db_path)
        # Should not raise
        tables = conn2.execute(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table'"
        ).fetchone()
        assert tables["cnt"] > 0
        conn2.close()


class TestMigrations:
    def test_migrations_are_idempotent(self, tmp_path):
        """Running migrations twice should not fail."""
        db_path = str(tmp_path / "mig.db")
        conn = init_database(db_path)

        # Run again manually
        run_migrations(conn)

        # Check version table
        row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
        assert row["v"] >= 2  # We have at least 2 migration files
        conn.close()

    def test_schema_version_tracks_applied(self, tmp_path):
        db_path = str(tmp_path / "ver.db")
        conn = init_database(db_path)

        rows = conn.execute(
            "SELECT version, description FROM schema_version ORDER BY version"
        ).fetchall()
        assert len(rows) >= 2
        assert rows[0]["version"] == 1
        assert "bias" in rows[0]["description"].lower()
        assert rows[1]["version"] == 2
        assert "web" in rows[1]["description"].lower()
        conn.close()

    def test_bias_flags_table_schema(self, tmp_path):
        """Verify bias_flags table has expected columns."""
        db_path = str(tmp_path / "bias_schema.db")
        conn = init_database(db_path)

        cols = conn.execute("PRAGMA table_info(bias_flags)").fetchall()
        col_names = {c["name"] for c in cols}
        expected = {
            "id", "knowledge_id", "bias_type", "bias_severity",
            "brand_names", "bias_notes", "detected_by", "created_at",
        }
        for c in expected:
            assert c in col_names, f"Missing column in bias_flags: {c}"
        conn.close()

    def test_chat_sessions_table_schema(self, tmp_path):
        """Verify chat_sessions table has expected columns."""
        db_path = str(tmp_path / "chat_schema.db")
        conn = init_database(db_path)

        cols = conn.execute("PRAGMA table_info(chat_sessions)").fetchall()
        col_names = {c["name"] for c in cols}
        expected = {"id", "title", "created_at", "updated_at"}
        for c in expected:
            assert c in col_names, f"Missing column in chat_sessions: {c}"
        conn.close()
