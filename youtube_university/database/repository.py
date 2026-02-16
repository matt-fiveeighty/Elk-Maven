from __future__ import annotations

import json
import re
import sqlite3
import logging
from typing import Optional

from .connection import get_connection, init_database

logger = logging.getLogger(__name__)


class Repository:
    """All database CRUD and search operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = init_database(self.db_path)
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def upsert_channel(self, data: dict) -> int:
        """Insert or update a channel. Returns the channel's DB id."""
        cur = self.conn.execute(
            """INSERT INTO channels (channel_id, channel_name, channel_url, description,
                                     subscriber_count, video_count, thumbnail_url)
               VALUES (:channel_id, :channel_name, :channel_url, :description,
                       :subscriber_count, :video_count, :thumbnail_url)
               ON CONFLICT(channel_id) DO UPDATE SET
                   channel_name = excluded.channel_name,
                   description = excluded.description,
                   subscriber_count = excluded.subscriber_count,
                   video_count = excluded.video_count,
                   thumbnail_url = excluded.thumbnail_url,
                   updated_at = datetime('now')""",
            data,
        )
        self.conn.commit()
        # Fetch the id (works for both insert and update)
        row = self.conn.execute(
            "SELECT id FROM channels WHERE channel_id = ?", (data["channel_id"],)
        ).fetchone()
        return row["id"]

    def get_channel_by_youtube_id(self, channel_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_channels(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM videos v WHERE v.channel_id = c.id) as total_videos,
                      (SELECT COUNT(*) FROM videos v WHERE v.channel_id = c.id AND v.ingestion_status = 'analyzed') as analyzed_videos
               FROM channels c ORDER BY c.channel_name"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Videos
    # ------------------------------------------------------------------

    def insert_videos_batch(self, channel_db_id: int, videos: list[dict]) -> int:
        """Insert videos, skip duplicates. Returns count of newly inserted."""
        inserted = 0
        for v in videos:
            try:
                self.conn.execute(
                    """INSERT INTO videos (video_id, channel_id, title, description,
                                          published_at, thumbnail_url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        v["video_id"],
                        channel_db_id,
                        v["title"],
                        v.get("description"),
                        v.get("published_at"),
                        v.get("thumbnail_url"),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate video_id, skip
        self.conn.commit()
        return inserted

    def get_pending_videos(
        self, channel_db_id: Optional[int] = None, limit: Optional[int] = None
    ) -> list[dict]:
        """Get videos that need processing (pending or failed)."""
        sql = """SELECT v.*, c.channel_name, c.channel_id as youtube_channel_id
                 FROM videos v
                 JOIN channels c ON v.channel_id = c.id
                 WHERE v.ingestion_status IN ('pending', 'failed')"""
        params: list = []
        if channel_db_id is not None:
            sql += " AND v.channel_id = ?"
            params.append(channel_db_id)
        sql += " ORDER BY v.published_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_video_status(
        self, video_db_id: int, status: str, failure_reason: Optional[str] = None
    ):
        self.conn.execute(
            """UPDATE videos SET ingestion_status = ?, failure_reason = ?,
                                 updated_at = datetime('now')
               WHERE id = ?""",
            (status, failure_reason, video_db_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Transcripts
    # ------------------------------------------------------------------

    def insert_transcript(self, video_db_id: int, data: dict) -> int:
        cur = self.conn.execute(
            """INSERT INTO transcripts (video_id, language_code, is_generated,
                                        full_text, snippet_data, word_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                video_db_id,
                data["language_code"],
                data["is_generated"],
                data["full_text"],
                json.dumps(data["snippets"]),
                data["word_count"],
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def insert_knowledge_entry(self, entry: dict) -> int:
        cur = self.conn.execute(
            """INSERT INTO knowledge_entries
               (video_id, entry_type, title, content, source_start_time,
                source_end_time, source_quote, confidence, chunk_index)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["video_id"],
                entry["entry_type"],
                entry["title"],
                entry["content"],
                entry.get("source_start_time"),
                entry.get("source_end_time"),
                entry.get("source_quote"),
                entry.get("confidence", 0.8),
                entry.get("chunk_index"),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_or_create_category(self, name: str, parent_id: Optional[int] = None) -> int:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        row = self.conn.execute(
            "SELECT id FROM categories WHERE slug = ?", (slug,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO categories (name, slug, parent_id) VALUES (?, ?, ?)",
            (name, slug, parent_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_or_create_tag(self, name: str) -> int:
        tag_name = name.lower().strip()
        row = self.conn.execute(
            "SELECT id FROM tags WHERE name = ?", (tag_name,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,))
        self.conn.commit()
        return cur.lastrowid

    def link_knowledge_category(self, knowledge_id: int, category_id: int):
        try:
            self.conn.execute(
                "INSERT INTO knowledge_categories (knowledge_id, category_id) VALUES (?, ?)",
                (knowledge_id, category_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def link_knowledge_tag(self, knowledge_id: int, tag_id: int):
        try:
            self.conn.execute(
                "INSERT INTO knowledge_tags (knowledge_id, tag_id) VALUES (?, ?)",
                (knowledge_id, tag_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    # ------------------------------------------------------------------
    # Search (for future Query Agent and CLI)
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_fts_query(query: str) -> str:
        """Convert a natural language query into an FTS5 OR query.

        'elk hunting tips' -> 'elk OR hunting OR tips'
        This matches entries containing ANY of the words instead of
        requiring an exact phrase.
        """
        words = [w.strip() for w in query.split() if w.strip()]
        if not words:
            return query
        # Escape any FTS5 special characters
        safe = []
        for w in words:
            cleaned = re.sub(r'[^\w]', '', w)
            if cleaned:
                safe.append(cleaned)
        return " OR ".join(safe) if safe else query

    def search_knowledge(
        self,
        query: str,
        limit: int = 20,
        entry_type: Optional[str] = None,
    ) -> list[dict]:
        """Full-text search across knowledge entries with BM25 ranking."""
        fts_query = self._prepare_fts_query(query)
        sql = """
            SELECT ke.*, v.video_id as youtube_video_id, v.title as video_title,
                   c.channel_name,
                   rank
            FROM knowledge_fts fts
            JOIN knowledge_entries ke ON ke.id = fts.rowid
            JOIN videos v ON ke.video_id = v.id
            JOIN channels c ON v.channel_id = c.id
            WHERE knowledge_fts MATCH ?
        """
        params: list = [fts_query]
        if entry_type:
            sql += " AND ke.entry_type = ?"
            params.append(entry_type)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def search_transcripts(self, query: str, limit: int = 10) -> list[dict]:
        fts_query = self._prepare_fts_query(query)
        sql = """
            SELECT t.*, v.video_id as youtube_video_id, v.title as video_title,
                   c.channel_name, rank
            FROM transcript_fts fts
            JOIN transcripts t ON t.id = fts.rowid
            JOIN videos v ON t.video_id = v.id
            JOIN channels c ON v.channel_id = c.id
            WHERE transcript_fts MATCH ?
            ORDER BY rank LIMIT ?
        """
        rows = self.conn.execute(sql, (query, limit)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_ingestion_stats(self) -> dict:
        stats = {}
        # Channel count
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM channels").fetchone()
        stats["channels"] = row["cnt"]

        # Videos by status
        rows = self.conn.execute(
            "SELECT ingestion_status, COUNT(*) as cnt FROM videos GROUP BY ingestion_status"
        ).fetchall()
        stats["videos_by_status"] = {r["ingestion_status"]: r["cnt"] for r in rows}
        stats["total_videos"] = sum(stats["videos_by_status"].values())

        # Knowledge entries
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_entries"
        ).fetchone()
        stats["knowledge_entries"] = row["cnt"]

        # Total tokens used
        row = self.conn.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) as total FROM processing_log"
        ).fetchone()
        stats["total_tokens"] = row["total"]

        # Categories and tags
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM categories").fetchone()
        stats["categories"] = row["cnt"]
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM tags").fetchone()
        stats["tags"] = row["cnt"]

        return stats

    # ------------------------------------------------------------------
    # Processing log
    # ------------------------------------------------------------------

    def log_processing_step(
        self,
        video_db_id: int,
        step: str,
        chunk_index: Optional[int] = None,
        status: str = "started",
        tokens_used: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO processing_log (video_id, step, chunk_index, status,
                                           tokens_used, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (video_db_id, step, chunk_index, status, tokens_used, error_message),
        )
        self.conn.commit()
        return cur.lastrowid

    def complete_processing_step(
        self, log_id: int, tokens_used: Optional[int] = None
    ):
        self.conn.execute(
            """UPDATE processing_log
               SET status = 'completed', tokens_used = ?,
                   completed_at = datetime('now')
               WHERE id = ?""",
            (tokens_used, log_id),
        )
        self.conn.commit()

    def seed_default_categories(self, categories: list[dict]):
        """Seed default categories from config, skip if already exist."""
        for cat in categories:
            self.get_or_create_category(cat["name"])

    # ------------------------------------------------------------------
    # Bias Detection
    # ------------------------------------------------------------------

    def get_unflagged_entries(self) -> list[dict]:
        """Get knowledge entries that haven't been scanned for bias yet."""
        rows = self.conn.execute("""
            SELECT ke.*, v.title as video_title, c.channel_name
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            JOIN channels c ON v.channel_id = c.id
            WHERE ke.id NOT IN (SELECT knowledge_id FROM bias_flags)
            ORDER BY ke.id
        """).fetchall()
        return [dict(r) for r in rows]

    def insert_bias_flag(self, flag: dict):
        """Insert a bias flag for a knowledge entry."""
        try:
            self.conn.execute("""
                INSERT INTO bias_flags
                    (knowledge_id, bias_type, bias_severity, brand_names, bias_notes, detected_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                flag["knowledge_id"], flag["bias_type"], flag["bias_severity"],
                json.dumps(flag.get("brand_names", [])), flag["bias_notes"],
                flag.get("detected_by", "bias_agent"),
            ))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass  # Already flagged for this type

    def get_bias_flags_for_entry(self, knowledge_id: int) -> list[dict]:
        """Get all bias flags for a specific knowledge entry."""
        rows = self.conn.execute(
            "SELECT * FROM bias_flags WHERE knowledge_id = ?", (knowledge_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_bias_summary(self) -> dict:
        """Get summary statistics about bias flags."""
        stats = {}
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM bias_flags").fetchone()
        stats["total_flags"] = row["cnt"]

        rows = self.conn.execute("""
            SELECT bias_type, COUNT(*) as cnt FROM bias_flags GROUP BY bias_type
        """).fetchall()
        stats["by_type"] = {r["bias_type"]: r["cnt"] for r in rows}

        rows = self.conn.execute("""
            SELECT bias_severity, COUNT(*) as cnt FROM bias_flags GROUP BY bias_severity
        """).fetchall()
        stats["by_severity"] = {r["bias_severity"]: r["cnt"] for r in rows}

        row = self.conn.execute("""
            SELECT COUNT(DISTINCT knowledge_id) as cnt FROM bias_flags
        """).fetchone()
        stats["flagged_entries"] = row["cnt"]

        return stats

    # ------------------------------------------------------------------
    # Optimization Queue
    # ------------------------------------------------------------------

    def insert_queue_item(self, item: dict) -> int:
        """Insert an item into the optimization queue."""
        cur = self.conn.execute("""
            INSERT INTO optimization_queue
                (action_type, severity, target_type, target_id, description, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item["action_type"], item["severity"], item["target_type"],
            item.get("target_id"), item["description"],
            json.dumps(item.get("details", {})),
        ))
        self.conn.commit()
        return cur.lastrowid

    def get_pending_queue_items(self) -> list[dict]:
        """Get all pending optimization suggestions."""
        rows = self.conn.execute("""
            SELECT * FROM optimization_queue WHERE status = 'pending'
            ORDER BY created_at
        """).fetchall()
        return [dict(r) for r in rows]

    def get_approved_queue_items(self) -> list[dict]:
        """Get all approved items ready for execution."""
        rows = self.conn.execute("""
            SELECT * FROM optimization_queue WHERE status = 'approved'
            ORDER BY created_at
        """).fetchall()
        return [dict(r) for r in rows]

    def update_queue_status(self, queue_id: int, status: str,
                            resolved_by: str = "auto"):
        """Update the status of a queue item."""
        self.conn.execute("""
            UPDATE optimization_queue
            SET status = ?, resolved_at = datetime('now'), resolved_by = ?
            WHERE id = ?
        """, (status, resolved_by, queue_id))
        self.conn.commit()

    def log_optimization(self, queue_id: Optional[int], action_type: str,
                         description: str, details: Optional[dict] = None):
        """Log an optimization action that was executed."""
        self.conn.execute("""
            INSERT INTO optimization_log (queue_id, action_type, description, details)
            VALUES (?, ?, ?, ?)
        """, (queue_id, action_type, description, json.dumps(details or {})))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Optimization Helpers
    # ------------------------------------------------------------------

    def get_all_tags_with_counts(self) -> list[dict]:
        """Get all tags with their usage counts."""
        rows = self.conn.execute("""
            SELECT t.id, t.name, COUNT(kt.knowledge_id) as usage_count
            FROM tags t LEFT JOIN knowledge_tags kt ON t.id = kt.tag_id
            GROUP BY t.id ORDER BY t.name
        """).fetchall()
        return [dict(r) for r in rows]

    def merge_tags(self, keep_id: int, remove_ids: list[int]):
        """Merge tags: repoint all references to keep_id, delete remove_ids."""
        for rid in remove_ids:
            # Repoint knowledge_tags (ignore conflicts with existing links)
            self.conn.execute("""
                UPDATE OR IGNORE knowledge_tags SET tag_id = ? WHERE tag_id = ?
            """, (keep_id, rid))
            # Delete orphaned links and the tag itself
            self.conn.execute("DELETE FROM knowledge_tags WHERE tag_id = ?", (rid,))
            self.conn.execute("DELETE FROM tags WHERE id = ?", (rid,))
        self.conn.commit()

    def get_entries_without_categories(self) -> list[dict]:
        """Get entries that have no category links."""
        rows = self.conn.execute("""
            SELECT ke.*, v.title as video_title
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            WHERE ke.id NOT IN (SELECT knowledge_id FROM knowledge_categories)
        """).fetchall()
        return [dict(r) for r in rows]

    def get_entries_without_tags(self) -> list[dict]:
        """Get entries that have no tag links."""
        rows = self.conn.execute("""
            SELECT ke.*, v.title as video_title
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            WHERE ke.id NOT IN (SELECT knowledge_id FROM knowledge_tags)
        """).fetchall()
        return [dict(r) for r in rows]

    def update_entry_confidence(self, entry_id: int, new_confidence: float):
        """Update confidence score for an entry."""
        clamped = min(1.0, max(0.0, new_confidence))
        self.conn.execute(
            "UPDATE knowledge_entries SET confidence = ? WHERE id = ?",
            (clamped, entry_id),
        )
        self.conn.commit()

    def delete_knowledge_entry(self, entry_id: int):
        """Delete a knowledge entry and its category/tag links."""
        self.conn.execute("DELETE FROM knowledge_entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    def get_videos_with_low_entry_stats(self) -> list[dict]:
        """Find analyzed videos with few entries or low avg confidence."""
        rows = self.conn.execute("""
            SELECT v.id, v.video_id, v.title,
                   COUNT(ke.id) as entry_count,
                   AVG(ke.confidence) as avg_confidence
            FROM videos v
            LEFT JOIN knowledge_entries ke ON v.id = ke.video_id
            WHERE v.ingestion_status = 'analyzed'
            GROUP BY v.id
            HAVING entry_count < 3 OR avg_confidence < 0.5
        """).fetchall()
        return [dict(r) for r in rows]

    def get_low_quality_entries(self) -> list[dict]:
        """Find entries with very low confidence and short content."""
        rows = self.conn.execute("""
            SELECT ke.*, v.title as video_title
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            WHERE ke.confidence < 0.3 AND LENGTH(ke.content) < 50
        """).fetchall()
        return [dict(r) for r in rows]

    def get_all_entries_for_comparison(self) -> list[dict]:
        """Get all entries with basic fields for duplicate comparison."""
        rows = self.conn.execute("""
            SELECT ke.id, ke.title, ke.content, ke.confidence,
                   ke.video_id, ke.entry_type, v.title as video_title
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            ORDER BY ke.title
        """).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Chat Sessions & Messages (Web UI)
    # ------------------------------------------------------------------

    def create_chat_session(self, title: Optional[str] = None) -> int:
        """Create a new chat session."""
        cur = self.conn.execute(
            "INSERT INTO chat_sessions (title) VALUES (?)",
            (title or "New Chat",),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_all_sessions(self) -> list[dict]:
        """Get all chat sessions with last message preview."""
        rows = self.conn.execute("""
            SELECT cs.*,
                   (SELECT content FROM chat_messages cm
                    WHERE cm.session_id = cs.id
                    ORDER BY cm.created_at DESC LIMIT 1) as last_message,
                   (SELECT COUNT(*) FROM chat_messages cm
                    WHERE cm.session_id = cs.id) as message_count
            FROM chat_sessions cs ORDER BY cs.updated_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_session_messages(self, session_id: int,
                             limit: Optional[int] = None) -> list[dict]:
        """Get messages for a chat session."""
        sql = "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at"
        params: list = [session_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def insert_chat_message(self, session_id: int, role: str, content: str,
                            image_ids: Optional[list[int]] = None,
                            metadata: Optional[dict] = None) -> int:
        """Insert a chat message and update session timestamp."""
        cur = self.conn.execute("""
            INSERT INTO chat_messages (session_id, role, content, image_ids, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_id, role, content,
            json.dumps(image_ids) if image_ids else None,
            json.dumps(metadata) if metadata else None,
        ))
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_session(self, session_id: int):
        """Delete a chat session and all its messages."""
        self.conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        self.conn.commit()

    def rename_session(self, session_id: int, title: str):
        """Rename a chat session."""
        self.conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = datetime('now') WHERE id = ?",
            (title, session_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Uploaded Images (Web UI)
    # ------------------------------------------------------------------

    def insert_uploaded_image(self, data: dict) -> int:
        """Store metadata for an uploaded image."""
        cur = self.conn.execute("""
            INSERT INTO uploaded_images
                (session_id, filename, mime_type, file_path, file_size,
                 width, height, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("session_id"), data["filename"], data["mime_type"],
            data["file_path"], data["file_size"],
            data.get("width"), data.get("height"), data.get("description"),
        ))
        self.conn.commit()
        return cur.lastrowid

    def get_image(self, image_id: int) -> Optional[dict]:
        """Get image metadata by ID."""
        row = self.conn.execute(
            "SELECT * FROM uploaded_images WHERE id = ?", (image_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_image_markup(self, image_id: int, markup_data: dict):
        """Save canvas markup annotations for an image."""
        self.conn.execute(
            "UPDATE uploaded_images SET markup_data = ? WHERE id = ?",
            (json.dumps(markup_data), image_id),
        )
        self.conn.commit()

    def update_image_description(self, image_id: int, description: str):
        """Update the description for an image."""
        self.conn.execute(
            "UPDATE uploaded_images SET description = ? WHERE id = ?",
            (description, image_id),
        )
        self.conn.commit()
