"""Shared test fixtures for YouTube University tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from youtube_university.database.connection import init_database
from youtube_university.database.repository import Repository


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database with full schema + migrations."""
    db_path = str(tmp_path / "test.db")
    conn = init_database(db_path)
    conn.close()
    return db_path


@pytest.fixture
def repo(tmp_db):
    """Create a Repository backed by the temp database."""
    r = Repository(tmp_db)
    yield r
    r.close()


@pytest.fixture
def seeded_repo(repo):
    """Repository pre-loaded with a channel, videos, and knowledge entries."""
    # Insert a channel
    channel_id = repo.upsert_channel({
        "channel_id": "UC_test123",
        "channel_name": "Test Hunting Channel",
        "channel_url": "https://youtube.com/@test",
        "description": "Test channel for elk hunting content",
        "subscriber_count": 100000,
        "video_count": 50,
        "thumbnail_url": "https://example.com/thumb.jpg",
    })

    # Insert videos
    videos = [
        {"video_id": f"vid_{i}", "title": f"Test Video {i}",
         "description": f"Description for video {i}",
         "published_at": f"2024-01-{i:02d}T00:00:00Z",
         "thumbnail_url": f"https://example.com/v{i}.jpg"}
        for i in range(1, 6)
    ]
    repo.insert_videos_batch(channel_id, videos)

    # Mark some videos as analyzed
    rows = repo.conn.execute("SELECT id FROM videos ORDER BY id").fetchall()
    for row in rows[:3]:
        repo.update_video_status(row["id"], "analyzed")

    # Insert knowledge entries for the analyzed videos
    entries = [
        {"video_id": rows[0]["id"], "entry_type": "tip",
         "title": "Wind direction for elk hunting",
         "content": "Always approach elk from downwind. Thermals rise in the morning.",
         "confidence": 0.85},
        {"video_id": rows[0]["id"], "entry_type": "technique",
         "title": "Cow calling strategy",
         "content": "Use cow calls sparingly in the first hour. Let the bulls come to you.",
         "confidence": 0.9},
        {"video_id": rows[1]["id"], "entry_type": "insight",
         "title": "Sitka Gear Review - Best Camo",
         "content": "Sitka is hands down the best camo on the market. Use my code HUNT20 for discount.",
         "confidence": 0.7},
        {"video_id": rows[1]["id"], "entry_type": "warning",
         "title": "Avoid high pressure midday",
         "content": "Elk bed down in heavy timber during midday high pressure periods.",
         "confidence": 0.8},
        {"video_id": rows[2]["id"], "entry_type": "tip",
         "title": "Wind direction and thermals",
         "content": "Thermals reverse in evening. Always check wind before approaching.",
         "confidence": 0.82},
        {"video_id": rows[2]["id"], "entry_type": "concept",
         "title": "Low quality entry",
         "content": "Elk.",
         "confidence": 0.2},
    ]
    for entry in entries:
        repo.insert_knowledge_entry(entry)

    # Add some tags and categories
    tag_ids = [repo.get_or_create_tag(t) for t in ["elk", "wind", "thermals", "calling"]]
    cat_id = repo.get_or_create_category("Elk Hunting")

    # Link some entries
    ke_rows = repo.conn.execute("SELECT id FROM knowledge_entries ORDER BY id").fetchall()
    repo.link_knowledge_tag(ke_rows[0]["id"], tag_ids[0])
    repo.link_knowledge_tag(ke_rows[0]["id"], tag_ids[1])
    repo.link_knowledge_category(ke_rows[0]["id"], cat_id)

    return repo


@pytest.fixture
def upload_dir(tmp_path):
    """Create a temporary upload directory."""
    d = tmp_path / "uploads"
    d.mkdir()
    return d


@pytest.fixture
def flask_app(tmp_db, upload_dir):
    """Create a Flask test app with all routes registered."""
    from youtube_university.web.app import create_app

    config = {
        "db_path": tmp_db,
        "ollama": {
            "url": "http://localhost:11434",
            "model": "llama3.2",
        },
    }
    app = create_app(config)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()
