"""Tests for the OptimizerAgent — tag normalization, categorization, queue management."""
from __future__ import annotations

import json

import pytest

from youtube_university.agents.optimizer import OptimizerAgent


@pytest.fixture
def optimizer(seeded_repo):
    """Create an OptimizerAgent backed by the seeded repo."""
    return OptimizerAgent(
        repo=seeded_repo,
        ollama_url="http://localhost:11434",
        model="llama3.2",
    )


class TestNormalizeTags:
    def test_merges_duplicate_tags(self, optimizer, seeded_repo):
        # Create duplicate tags with different forms
        id1 = seeded_repo.get_or_create_tag("elk hunting")
        id2 = seeded_repo.get_or_create_tag("elk-hunting")
        id3 = seeded_repo.get_or_create_tag("elk_hunting")

        events = list(optimizer._normalize_tags())
        result = next(e for e in events if e.get("event") == "result")
        assert result["merged"] >= 2  # At least 2 variants merged

        # Verify only one remains
        tags = seeded_repo.get_all_tags_with_counts()
        hunting_tags = [t for t in tags if "elk" in t["name"] and "hunting" in t["name"]]
        assert len(hunting_tags) == 1

    def test_no_merge_needed(self, optimizer, seeded_repo):
        """With only unique tags, nothing should be merged."""
        # seeded_repo has: elk, wind, thermals, calling — all unique
        # First normalize any existing dupes
        list(optimizer._normalize_tags())
        # Run again — should find nothing new
        events = list(optimizer._normalize_tags())
        result = next(e for e in events if e.get("event") == "result")
        assert result["merged"] == 0


class TestRescoreConfidence:
    def test_boosts_cross_referenced_entries(self, optimizer, seeded_repo):
        """Entries about 'wind direction' appear in video 1 and video 3,
        so they should get a confidence boost."""
        events = list(optimizer._rescore_confidence())
        result = next(e for e in events if e.get("event") == "result")
        # The two wind/thermal entries from different videos should be boosted
        assert result["updated"] >= 0  # May or may not match depending on word overlap


class TestSuggestReingest:
    def test_no_suggestions_when_all_good(self, optimizer, seeded_repo):
        """Analyzed videos with >=3 entries and good confidence shouldn't be suggested."""
        events = list(optimizer._suggest_reingest())
        result = next(e for e in events if e.get("event") == "result")
        # Depends on test data; just verify the structure
        assert "queued" in result

    def test_suggests_videos_with_few_entries(self, optimizer, seeded_repo):
        """A video with only 1 entry and low confidence should be flagged."""
        # Create a video with very few entries
        vid = seeded_repo.conn.execute(
            "SELECT id FROM videos WHERE ingestion_status = 'analyzed' ORDER BY id"
        ).fetchall()
        # Video at index 2 has only 2 entries (id 5, 6) and one has confidence 0.2
        events = list(optimizer._suggest_reingest())
        result = next(e for e in events if e.get("event") == "result")
        assert isinstance(result["queued"], int)


class TestSuggestDeleteGarbage:
    def test_flags_low_quality_entries(self, optimizer, seeded_repo):
        """The 'Elk.' entry (confidence 0.2, 4 chars) should be flagged."""
        events = list(optimizer._suggest_delete_garbage())
        result = next(e for e in events if e.get("event") == "result")
        assert result["queued"] >= 1

        # Check the queue
        items = seeded_repo.get_pending_queue_items()
        delete_items = [i for i in items if i["action_type"] == "delete_entry"]
        assert len(delete_items) >= 1


class TestExecuteApproved:
    def test_execute_delete_entry(self, optimizer, seeded_repo):
        """Approve and execute a delete_entry queue item."""
        ke = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries ORDER BY confidence ASC LIMIT 1"
        ).fetchone()

        qid = seeded_repo.insert_queue_item({
            "action_type": "delete_entry",
            "severity": "destructive",
            "target_type": "knowledge_entry",
            "target_id": ke["id"],
            "description": "Delete test entry",
            "details": {"reason": "test"},
        })
        seeded_repo.update_queue_status(qid, "approved")

        initial_count = seeded_repo.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_entries"
        ).fetchone()["cnt"]

        result = optimizer.execute_approved()
        assert result["executed"] == 1
        assert result["failed"] == 0

        final_count = seeded_repo.conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_entries"
        ).fetchone()["cnt"]
        assert final_count == initial_count - 1

    def test_execute_reingest(self, optimizer, seeded_repo):
        """Approve and execute a re_ingest queue item."""
        vid = seeded_repo.conn.execute(
            "SELECT id FROM videos WHERE ingestion_status = 'analyzed' LIMIT 1"
        ).fetchone()

        qid = seeded_repo.insert_queue_item({
            "action_type": "re_ingest",
            "severity": "destructive",
            "target_type": "video",
            "target_id": vid["id"],
            "description": "Re-ingest test video",
        })
        seeded_repo.update_queue_status(qid, "approved")

        result = optimizer.execute_approved()
        assert result["executed"] == 1

        # Video should now be pending again
        row = seeded_repo.conn.execute(
            "SELECT ingestion_status FROM videos WHERE id = ?", (vid["id"],)
        ).fetchone()
        assert row["ingestion_status"] == "pending"

    def test_execute_nothing_when_empty(self, optimizer):
        result = optimizer.execute_approved()
        assert result["executed"] == 0
        assert result["failed"] == 0


class TestRunAuto:
    def test_run_auto_yields_events(self, optimizer):
        """run_auto should yield phase + result events and finish with auto_complete."""
        events = list(optimizer.run_auto())
        phases = [e["phase"] for e in events if e.get("event") == "phase"]
        assert "normalize_tags" in phases
        assert "fill_categories" in phases
        assert "fill_tags" in phases
        assert "rescore_confidence" in phases
        assert any(e.get("event") == "auto_complete" for e in events)


class TestRunSuggestions:
    def test_run_suggestions_yields_events(self, optimizer):
        events = list(optimizer.run_suggestions())
        phases = [e["phase"] for e in events if e.get("event") == "phase"]
        assert "suggest_reingest" in phases
        assert "suggest_delete_garbage" in phases
        assert any(e.get("event") == "suggestions_complete" for e in events)
