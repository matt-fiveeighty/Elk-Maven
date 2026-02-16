from __future__ import annotations

"""Agent 7: Optimizer — Continuously improves knowledge base quality.
Auto-executes safe operations (tag normalization, fill metadata, rescore).
Queues destructive operations (re-ingest, delete, merge) for user approval."""

import json
import logging
import re
from collections import defaultdict

import requests

from ..database.repository import Repository
from ..prompts.optimization import (
    OPTIMIZER_SYSTEM_PROMPT,
    build_categorize_prompt,
    build_tag_prompt,
    build_duplicate_check_prompt,
)

logger = logging.getLogger(__name__)


class OptimizerAgent:
    """Continuously improves the knowledge base quality."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    # ==================================================================
    # AUTO-EXECUTE: Safe operations
    # ==================================================================

    def run_auto(self):
        """Execute all safe optimizations. Yields progress events."""
        yield {"event": "phase", "phase": "normalize_tags"}
        yield from self._normalize_tags()

        yield {"event": "phase", "phase": "fill_categories"}
        yield from self._fill_missing_categories()

        yield {"event": "phase", "phase": "fill_tags"}
        yield from self._fill_missing_tags()

        yield {"event": "phase", "phase": "rescore_confidence"}
        yield from self._rescore_confidence()

        yield {"event": "auto_complete"}

    def _normalize_tags(self):
        """Merge duplicate/similar tags into canonical forms."""
        tags = self.repo.get_all_tags_with_counts()
        if not tags:
            yield {"event": "skip", "reason": "No tags to normalize"}
            return

        # Group tags by normalized form
        groups = defaultdict(list)
        for tag in tags:
            # Normalize: lowercase, replace hyphens/underscores with spaces, strip
            normalized = re.sub(r'[-_]+', ' ', tag["name"].lower()).strip()
            # Further normalize: remove extra spaces
            normalized = re.sub(r'\s+', ' ', normalized)
            groups[normalized].append(tag)

        merged_count = 0
        for normalized, group in groups.items():
            if len(group) <= 1:
                continue

            # Keep the tag with highest usage count
            group.sort(key=lambda t: t["usage_count"], reverse=True)
            keep = group[0]
            remove = group[1:]
            remove_ids = [t["id"] for t in remove]

            self.repo.merge_tags(keep["id"], remove_ids)
            self.repo.log_optimization(
                None, "normalize_tags",
                f"Merged {len(remove)} tags into '{keep['name']}': "
                f"{[t['name'] for t in remove]}",
                {"keep_id": keep["id"], "removed": remove_ids},
            )
            merged_count += len(remove)

        yield {"event": "result", "action": "normalize_tags", "merged": merged_count}

    def _fill_missing_categories(self):
        """Use LLM to assign categories to uncategorized entries."""
        entries = self.repo.get_entries_without_categories()
        if not entries:
            yield {"event": "skip", "reason": "All entries have categories"}
            return

        # Get existing category names
        rows = self.repo.conn.execute("SELECT name FROM categories").fetchall()
        categories = [r["name"] for r in rows]

        assigned = 0
        batch_size = 10
        for i in range(0, len(entries), batch_size):
            batch = entries[i:i + batch_size]
            try:
                prompt = build_categorize_prompt(batch, categories)
                resp = self._call_ollama(prompt)
                data = json.loads(resp)

                for assignment in data.get("assignments", []):
                    entry_id = assignment.get("id")
                    cats = assignment.get("categories", [])
                    for cat_name in cats:
                        cat_id = self.repo.get_or_create_category(cat_name)
                        self.repo.link_knowledge_category(entry_id, cat_id)
                        assigned += 1

            except Exception as e:
                logger.warning(f"Failed to categorize batch: {e}")

        if assigned > 0:
            self.repo.log_optimization(
                None, "fill_metadata",
                f"Assigned categories to {assigned} entry-category links",
            )
        yield {"event": "result", "action": "fill_categories", "assigned": assigned}

    def _fill_missing_tags(self):
        """Use LLM to assign tags to untagged entries."""
        entries = self.repo.get_entries_without_tags()
        if not entries:
            yield {"event": "skip", "reason": "All entries have tags"}
            return

        assigned = 0
        batch_size = 10
        for i in range(0, len(entries), batch_size):
            batch = entries[i:i + batch_size]
            try:
                prompt = build_tag_prompt(batch)
                resp = self._call_ollama(prompt)
                data = json.loads(resp)

                for assignment in data.get("assignments", []):
                    entry_id = assignment.get("id")
                    tags = assignment.get("tags", [])
                    for tag_name in tags:
                        tag_id = self.repo.get_or_create_tag(tag_name)
                        self.repo.link_knowledge_tag(entry_id, tag_id)
                        assigned += 1

            except Exception as e:
                logger.warning(f"Failed to tag batch: {e}")

        if assigned > 0:
            self.repo.log_optimization(
                None, "fill_metadata",
                f"Assigned {assigned} entry-tag links",
            )
        yield {"event": "result", "action": "fill_tags", "assigned": assigned}

    def _rescore_confidence(self):
        """Boost confidence for entries corroborated across multiple videos."""
        entries = self.repo.get_all_entries_for_comparison()
        if not entries:
            yield {"event": "skip", "reason": "No entries to rescore"}
            return

        # Group entries by similar title (simple word overlap)
        title_groups = defaultdict(list)
        for entry in entries:
            # Create a key from the main words in the title
            words = set(re.findall(r'\w{4,}', entry["title"].lower()))
            # Use frozenset of significant words as a grouping key
            if len(words) >= 2:
                key = frozenset(list(sorted(words))[:4])
                title_groups[key].append(entry)

        rescored = 0
        for key, group in title_groups.items():
            if len(group) < 2:
                continue

            # Check if entries come from different videos
            video_ids = set(e["video_id"] for e in group)
            if len(video_ids) < 2:
                continue

            # Multiple videos corroborate → boost confidence
            boost = min(0.15, 0.05 * len(video_ids))
            for entry in group:
                new_conf = min(0.95, entry["confidence"] + boost)
                if new_conf > entry["confidence"]:
                    self.repo.update_entry_confidence(entry["id"], new_conf)
                    rescored += 1

        if rescored > 0:
            self.repo.log_optimization(
                None, "rescore",
                f"Boosted confidence for {rescored} cross-referenced entries",
            )
        yield {"event": "result", "action": "rescore", "updated": rescored}

    # ==================================================================
    # QUEUE: Destructive operations (need user approval)
    # ==================================================================

    def run_suggestions(self):
        """Analyze and queue destructive optimization suggestions."""
        yield {"event": "phase", "phase": "suggest_reingest"}
        yield from self._suggest_reingest()

        yield {"event": "phase", "phase": "suggest_delete_garbage"}
        yield from self._suggest_delete_garbage()

        yield {"event": "suggestions_complete"}

    def _suggest_reingest(self):
        """Queue suggestions to re-ingest poorly analyzed videos."""
        videos = self.repo.get_videos_with_low_entry_stats()
        queued = 0
        for v in videos:
            self.repo.insert_queue_item({
                "action_type": "re_ingest",
                "severity": "destructive",
                "target_type": "video",
                "target_id": v["id"],
                "description": (
                    f"Re-ingest '{v['title'][:60]}' — only {v['entry_count']} entries, "
                    f"avg confidence {v['avg_confidence']:.0%}"
                ),
                "details": {
                    "video_id": v["video_id"],
                    "entry_count": v["entry_count"],
                    "avg_confidence": v["avg_confidence"],
                },
            })
            queued += 1

        yield {"event": "result", "action": "suggest_reingest", "queued": queued}

    def _suggest_delete_garbage(self):
        """Queue suggestions to delete very low quality entries."""
        entries = self.repo.get_low_quality_entries()
        queued = 0
        for entry in entries:
            self.repo.insert_queue_item({
                "action_type": "delete_entry",
                "severity": "destructive",
                "target_type": "knowledge_entry",
                "target_id": entry["id"],
                "description": (
                    f"Delete low-quality entry: '{entry['title'][:50]}' — "
                    f"confidence {entry['confidence']:.0%}, "
                    f"{len(entry['content'])} chars"
                ),
                "details": {
                    "title": entry["title"],
                    "content": entry["content"],
                    "confidence": entry["confidence"],
                },
            })
            queued += 1

        yield {"event": "result", "action": "suggest_delete", "queued": queued}

    # ==================================================================
    # EXECUTE: Run approved queue items
    # ==================================================================

    def execute_approved(self):
        """Execute all approved items from the optimization queue."""
        approved = self.repo.get_approved_queue_items()
        executed = 0
        failed = 0

        for item in approved:
            try:
                self._execute_queue_item(item)
                self.repo.update_queue_status(item["id"], "executed")
                executed += 1
            except Exception as e:
                self.repo.update_queue_status(item["id"], "failed")
                logger.error(f"Failed to execute queue item {item['id']}: {e}")
                failed += 1

        return {"executed": executed, "failed": failed}

    def _execute_queue_item(self, item: dict):
        """Execute a single approved queue item."""
        action = item["action_type"]
        details = json.loads(item["details"]) if item["details"] else {}

        if action == "delete_entry":
            self.repo.delete_knowledge_entry(item["target_id"])
            self.repo.log_optimization(
                item["id"], "delete_entry",
                f"Deleted entry {item['target_id']}: {item['description']}",
                details,
            )
        elif action == "re_ingest":
            # Reset video status so the ingestion pipeline picks it up again
            self.repo.update_video_status(item["target_id"], "pending")
            self.repo.log_optimization(
                item["id"], "re_ingest",
                f"Reset video {item['target_id']} for re-ingestion",
                details,
            )
        else:
            logger.warning(f"Unknown queue action: {action}")

    # ==================================================================
    # Helpers
    # ==================================================================

    def _call_ollama(self, prompt: str) -> str:
        """Send a prompt to Ollama and return the response content."""
        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": OPTIMIZER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "{}")
