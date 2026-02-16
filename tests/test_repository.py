"""Tests for the Repository class — CRUD, search, bias, optimization, chat."""
from __future__ import annotations

import json

import pytest


class TestChannels:
    def test_upsert_channel_creates_new(self, repo):
        ch_id = repo.upsert_channel({
            "channel_id": "UC_abc",
            "channel_name": "Alpha Channel",
            "channel_url": "https://youtube.com/@alpha",
            "description": "Test",
            "subscriber_count": 1000,
            "video_count": 10,
            "thumbnail_url": None,
        })
        assert ch_id is not None
        assert ch_id > 0

    def test_upsert_channel_updates_existing(self, repo):
        data = {
            "channel_id": "UC_abc",
            "channel_name": "Alpha Channel",
            "channel_url": "https://youtube.com/@alpha",
            "description": "Test",
            "subscriber_count": 1000,
            "video_count": 10,
            "thumbnail_url": None,
        }
        id1 = repo.upsert_channel(data)
        data["channel_name"] = "Alpha Channel v2"
        data["subscriber_count"] = 2000
        id2 = repo.upsert_channel(data)
        assert id1 == id2
        ch = repo.get_channel_by_youtube_id("UC_abc")
        assert ch["channel_name"] == "Alpha Channel v2"
        assert ch["subscriber_count"] == 2000

    def test_get_channel_by_youtube_id_missing(self, repo):
        assert repo.get_channel_by_youtube_id("nonexistent") is None

    def test_get_all_channels(self, seeded_repo):
        channels = seeded_repo.get_all_channels()
        assert len(channels) == 1
        assert channels[0]["channel_name"] == "Test Hunting Channel"
        assert "total_videos" in channels[0]
        assert "analyzed_videos" in channels[0]


class TestVideos:
    def test_insert_videos_batch(self, repo):
        ch_id = repo.upsert_channel({
            "channel_id": "UC_vid_test",
            "channel_name": "Vid Channel",
            "channel_url": "https://youtube.com/@vid",
            "description": "",
            "subscriber_count": 0,
            "video_count": 0,
            "thumbnail_url": None,
        })
        videos = [
            {"video_id": f"v{i}", "title": f"Video {i}"}
            for i in range(5)
        ]
        count = repo.insert_videos_batch(ch_id, videos)
        assert count == 5

    def test_insert_videos_batch_skips_duplicates(self, repo):
        ch_id = repo.upsert_channel({
            "channel_id": "UC_dup_test",
            "channel_name": "Dup Channel",
            "channel_url": "https://youtube.com/@dup",
            "description": "",
            "subscriber_count": 0,
            "video_count": 0,
            "thumbnail_url": None,
        })
        videos = [{"video_id": "dup_v1", "title": "Duplicate Test"}]
        assert repo.insert_videos_batch(ch_id, videos) == 1
        assert repo.insert_videos_batch(ch_id, videos) == 0  # Duplicate skipped

    def test_get_pending_videos(self, seeded_repo):
        pending = seeded_repo.get_pending_videos()
        # 5 total, 3 analyzed = 2 pending
        assert len(pending) == 2

    def test_get_pending_videos_with_limit(self, seeded_repo):
        pending = seeded_repo.get_pending_videos(limit=1)
        assert len(pending) == 1

    def test_update_video_status(self, seeded_repo):
        pending = seeded_repo.get_pending_videos(limit=1)
        vid_id = pending[0]["id"]
        seeded_repo.update_video_status(vid_id, "analyzed")
        # Should now have one fewer pending
        new_pending = seeded_repo.get_pending_videos()
        assert len(new_pending) == 1


class TestKnowledge:
    def test_insert_knowledge_entry(self, seeded_repo):
        rows = seeded_repo.conn.execute("SELECT id FROM videos LIMIT 1").fetchall()
        eid = seeded_repo.insert_knowledge_entry({
            "video_id": rows[0]["id"],
            "entry_type": "tip",
            "title": "New tip",
            "content": "Brand new knowledge entry for testing.",
            "confidence": 0.9,
        })
        assert eid > 0

    def test_get_or_create_category_idempotent(self, repo):
        id1 = repo.get_or_create_category("Elk Hunting")
        id2 = repo.get_or_create_category("Elk Hunting")
        assert id1 == id2

    def test_get_or_create_tag_idempotent(self, repo):
        id1 = repo.get_or_create_tag("thermals")
        id2 = repo.get_or_create_tag("thermals")
        assert id1 == id2

    def test_link_knowledge_category_no_duplicate_error(self, seeded_repo):
        ke = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries LIMIT 1"
        ).fetchone()
        cat_id = seeded_repo.get_or_create_category("Test Cat")
        seeded_repo.link_knowledge_category(ke["id"], cat_id)
        # Should not raise on duplicate
        seeded_repo.link_knowledge_category(ke["id"], cat_id)

    def test_link_knowledge_tag_no_duplicate_error(self, seeded_repo):
        ke = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries LIMIT 1"
        ).fetchone()
        tag_id = seeded_repo.get_or_create_tag("test_tag")
        seeded_repo.link_knowledge_tag(ke["id"], tag_id)
        seeded_repo.link_knowledge_tag(ke["id"], tag_id)


class TestSearch:
    def test_search_knowledge_returns_results(self, seeded_repo):
        results = seeded_repo.search_knowledge("elk wind thermals")
        assert len(results) > 0

    def test_search_knowledge_with_type_filter(self, seeded_repo):
        results = seeded_repo.search_knowledge("elk", entry_type="tip")
        for r in results:
            assert r["entry_type"] == "tip"

    def test_search_knowledge_no_results(self, seeded_repo):
        results = seeded_repo.search_knowledge("xylophone kazoo")
        assert len(results) == 0

    def test_prepare_fts_query(self):
        from youtube_university.database.repository import Repository
        assert Repository._prepare_fts_query("elk hunting tips") == "elk OR hunting OR tips"
        assert Repository._prepare_fts_query("") == ""
        assert Repository._prepare_fts_query("single") == "single"


class TestStats:
    def test_get_ingestion_stats(self, seeded_repo):
        stats = seeded_repo.get_ingestion_stats()
        assert stats["channels"] == 1
        assert stats["total_videos"] == 5
        assert stats["knowledge_entries"] == 6
        assert "videos_by_status" in stats
        assert stats["videos_by_status"].get("analyzed", 0) == 3

    def test_get_ingestion_stats_empty_db(self, repo):
        stats = repo.get_ingestion_stats()
        assert stats["channels"] == 0
        assert stats["total_videos"] == 0
        assert stats["knowledge_entries"] == 0


class TestBias:
    def test_get_unflagged_entries(self, seeded_repo):
        entries = seeded_repo.get_unflagged_entries()
        assert len(entries) == 6  # All 6 are unflagged initially

    def test_insert_and_get_bias_flag(self, seeded_repo):
        entries = seeded_repo.get_unflagged_entries()
        flag = {
            "knowledge_id": entries[0]["id"],
            "bias_type": "brand_promotion",
            "bias_severity": "low",
            "brand_names": ["Sitka"],
            "bias_notes": "Mentions Sitka brand",
            "detected_by": "test",
        }
        seeded_repo.insert_bias_flag(flag)

        flags = seeded_repo.get_bias_flags_for_entry(entries[0]["id"])
        assert len(flags) == 1
        assert flags[0]["bias_type"] == "brand_promotion"
        assert flags[0]["bias_severity"] == "low"
        brands = json.loads(flags[0]["brand_names"])
        assert "Sitka" in brands

    def test_insert_bias_flag_no_duplicate(self, seeded_repo):
        entries = seeded_repo.get_unflagged_entries()
        flag = {
            "knowledge_id": entries[0]["id"],
            "bias_type": "brand_promotion",
            "bias_severity": "low",
            "brand_names": [],
            "bias_notes": "Test",
        }
        seeded_repo.insert_bias_flag(flag)
        # Insert same type for same entry — should not raise
        seeded_repo.insert_bias_flag(flag)

    def test_unflagged_entries_shrink_after_flagging(self, seeded_repo):
        entries = seeded_repo.get_unflagged_entries()
        initial_count = len(entries)

        seeded_repo.insert_bias_flag({
            "knowledge_id": entries[0]["id"],
            "bias_type": "brand_promotion",
            "bias_severity": "low",
            "brand_names": [],
            "bias_notes": "Test",
        })

        remaining = seeded_repo.get_unflagged_entries()
        assert len(remaining) == initial_count - 1

    def test_get_bias_summary(self, seeded_repo):
        entries = seeded_repo.get_unflagged_entries()
        seeded_repo.insert_bias_flag({
            "knowledge_id": entries[0]["id"],
            "bias_type": "brand_promotion",
            "bias_severity": "medium",
            "brand_names": ["Sitka"],
            "bias_notes": "Brand push",
        })
        summary = seeded_repo.get_bias_summary()
        assert summary["total_flags"] == 1
        assert summary["flagged_entries"] == 1
        assert summary["by_type"]["brand_promotion"] == 1
        assert summary["by_severity"]["medium"] == 1


class TestOptimizationQueue:
    def test_insert_and_get_queue_item(self, seeded_repo):
        qid = seeded_repo.insert_queue_item({
            "action_type": "delete_entry",
            "severity": "destructive",
            "target_type": "knowledge_entry",
            "target_id": 1,
            "description": "Delete low quality entry",
            "details": {"reason": "too short"},
        })
        assert qid > 0
        items = seeded_repo.get_pending_queue_items()
        assert len(items) == 1
        assert items[0]["action_type"] == "delete_entry"

    def test_approve_and_get_approved(self, seeded_repo):
        qid = seeded_repo.insert_queue_item({
            "action_type": "re_ingest",
            "severity": "destructive",
            "target_type": "video",
            "target_id": 1,
            "description": "Re-ingest video",
        })
        seeded_repo.update_queue_status(qid, "approved", "test_user")
        approved = seeded_repo.get_approved_queue_items()
        assert len(approved) == 1
        assert approved[0]["status"] == "approved"

        # Should no longer be in pending
        pending = seeded_repo.get_pending_queue_items()
        assert len(pending) == 0

    def test_reject_queue_item(self, seeded_repo):
        qid = seeded_repo.insert_queue_item({
            "action_type": "delete_entry",
            "severity": "destructive",
            "target_type": "knowledge_entry",
            "target_id": 1,
            "description": "Delete",
        })
        seeded_repo.update_queue_status(qid, "rejected", "test_user")
        assert len(seeded_repo.get_pending_queue_items()) == 0
        assert len(seeded_repo.get_approved_queue_items()) == 0

    def test_log_optimization(self, seeded_repo):
        seeded_repo.log_optimization(
            None, "normalize_tags", "Merged 5 tags",
            {"merged": ["elk hunting", "elk-hunting"]},
        )
        # Verify the log was written
        row = seeded_repo.conn.execute(
            "SELECT * FROM optimization_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["action_type"] == "normalize_tags"


class TestOptimizationHelpers:
    def test_get_all_tags_with_counts(self, seeded_repo):
        tags = seeded_repo.get_all_tags_with_counts()
        assert len(tags) >= 4  # elk, wind, thermals, calling
        # elk should have usage_count >= 1
        elk_tag = next((t for t in tags if t["name"] == "elk"), None)
        assert elk_tag is not None
        assert elk_tag["usage_count"] >= 1

    def test_merge_tags(self, seeded_repo):
        # Create duplicates
        id1 = seeded_repo.get_or_create_tag("elk hunting")
        id2 = seeded_repo.get_or_create_tag("elk-hunting")
        id3 = seeded_repo.get_or_create_tag("elk_hunting")

        seeded_repo.merge_tags(id1, [id2, id3])

        # Merged tags should be gone
        tags = seeded_repo.get_all_tags_with_counts()
        names = [t["name"] for t in tags]
        assert "elk hunting" in names
        assert "elk-hunting" not in names
        assert "elk_hunting" not in names

    def test_get_entries_without_categories(self, seeded_repo):
        uncategorized = seeded_repo.get_entries_without_categories()
        # 6 entries, only 1 has a category link
        assert len(uncategorized) == 5

    def test_get_entries_without_tags(self, seeded_repo):
        untagged = seeded_repo.get_entries_without_tags()
        # 6 entries, only 1 has tag links
        assert len(untagged) == 5

    def test_update_entry_confidence_clamps(self, seeded_repo):
        ke = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries LIMIT 1"
        ).fetchone()

        # Test clamping at 1.0
        seeded_repo.update_entry_confidence(ke["id"], 5.0)
        row = seeded_repo.conn.execute(
            "SELECT confidence FROM knowledge_entries WHERE id = ?", (ke["id"],)
        ).fetchone()
        assert row["confidence"] == 1.0

        # Test clamping at 0.0
        seeded_repo.update_entry_confidence(ke["id"], -1.0)
        row = seeded_repo.conn.execute(
            "SELECT confidence FROM knowledge_entries WHERE id = ?", (ke["id"],)
        ).fetchone()
        assert row["confidence"] == 0.0

    def test_delete_knowledge_entry(self, seeded_repo):
        initial = seeded_repo.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_entries"
        ).fetchone()["cnt"]

        ke = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries LIMIT 1"
        ).fetchone()
        seeded_repo.delete_knowledge_entry(ke["id"])

        after = seeded_repo.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_entries"
        ).fetchone()["cnt"]
        assert after == initial - 1

    def test_get_low_quality_entries(self, seeded_repo):
        low_q = seeded_repo.get_low_quality_entries()
        # We have one entry with confidence 0.2 and content "Elk." (4 chars)
        assert len(low_q) >= 1
        for entry in low_q:
            assert entry["confidence"] < 0.3
            assert len(entry["content"]) < 50


class TestChatSessions:
    def test_create_and_list_sessions(self, seeded_repo):
        sid = seeded_repo.create_chat_session("Test Chat")
        sessions = seeded_repo.get_all_sessions()
        assert any(s["id"] == sid for s in sessions)
        session = next(s for s in sessions if s["id"] == sid)
        assert session["title"] == "Test Chat"

    def test_session_messages(self, seeded_repo):
        sid = seeded_repo.create_chat_session()
        mid1 = seeded_repo.insert_chat_message(sid, "user", "Hello guru!")
        mid2 = seeded_repo.insert_chat_message(
            sid, "assistant", "How can I help?",
            metadata={"route": "general"},
        )
        messages = seeded_repo.get_session_messages(sid)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_delete_session_cascades(self, seeded_repo):
        sid = seeded_repo.create_chat_session()
        seeded_repo.insert_chat_message(sid, "user", "Hello")
        seeded_repo.delete_session(sid)
        messages = seeded_repo.get_session_messages(sid)
        assert len(messages) == 0

    def test_rename_session(self, seeded_repo):
        sid = seeded_repo.create_chat_session("Old Name")
        seeded_repo.rename_session(sid, "New Name")
        sessions = seeded_repo.get_all_sessions()
        session = next(s for s in sessions if s["id"] == sid)
        assert session["title"] == "New Name"

    def test_insert_message_with_image_ids(self, seeded_repo):
        sid = seeded_repo.create_chat_session()
        mid = seeded_repo.insert_chat_message(
            sid, "user", "Look at this map",
            image_ids=[1, 2, 3],
        )
        messages = seeded_repo.get_session_messages(sid)
        assert messages[0]["image_ids"] == json.dumps([1, 2, 3])


class TestImages:
    def test_insert_and_get_image(self, seeded_repo):
        img_id = seeded_repo.insert_uploaded_image({
            "session_id": None,
            "filename": "test_map.jpg",
            "mime_type": "image/jpeg",
            "file_path": "abc123.jpg",
            "file_size": 102400,
            "width": 800,
            "height": 600,
        })
        assert img_id > 0

        img = seeded_repo.get_image(img_id)
        assert img["filename"] == "test_map.jpg"
        assert img["width"] == 800

    def test_get_image_missing(self, seeded_repo):
        assert seeded_repo.get_image(9999) is None

    def test_update_image_markup(self, seeded_repo):
        img_id = seeded_repo.insert_uploaded_image({
            "session_id": None,
            "filename": "map.png",
            "mime_type": "image/png",
            "file_path": "xyz.png",
            "file_size": 5000,
        })
        markup = {"annotations": [{"type": "arrow", "x": 10, "y": 20}], "version": 1}
        seeded_repo.update_image_markup(img_id, markup)

        img = seeded_repo.get_image(img_id)
        saved_markup = json.loads(img["markup_data"])
        assert saved_markup["version"] == 1
        assert len(saved_markup["annotations"]) == 1

    def test_update_image_description(self, seeded_repo):
        img_id = seeded_repo.insert_uploaded_image({
            "session_id": None,
            "filename": "map.png",
            "mime_type": "image/png",
            "file_path": "xyz.png",
            "file_size": 5000,
        })
        seeded_repo.update_image_description(img_id, "Hunting area north of ridge")
        img = seeded_repo.get_image(img_id)
        assert img["description"] == "Hunting area north of ridge"


class TestProcessingLog:
    def test_log_and_complete_processing(self, seeded_repo):
        vid = seeded_repo.conn.execute("SELECT id FROM videos LIMIT 1").fetchone()
        log_id = seeded_repo.log_processing_step(
            vid["id"], "fetch_transcript", status="started"
        )
        assert log_id > 0
        seeded_repo.complete_processing_step(log_id, tokens_used=500)
        row = seeded_repo.conn.execute(
            "SELECT * FROM processing_log WHERE id = ?", (log_id,)
        ).fetchone()
        assert row["status"] == "completed"
        assert row["tokens_used"] == 500
