from __future__ import annotations

import logging
from typing import Optional

from ..database.repository import Repository
from .channel_fetcher import ChannelFetcher
from .transcript_fetcher import TranscriptFetcher
from .analyzer import TranscriptAnalyzer

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates the full ingestion flow: channel -> videos -> transcripts -> knowledge.

    Designed for resumability: checks video status before each step.
    """

    def __init__(
        self,
        channel_fetcher: ChannelFetcher,
        transcript_fetcher: TranscriptFetcher,
        analyzer: TranscriptAnalyzer,
        repo: Repository,
    ):
        self.channel_fetcher = channel_fetcher
        self.transcript_fetcher = transcript_fetcher
        self.analyzer = analyzer
        self.repo = repo

    def add_channel(self, channel_input: str) -> dict:
        """Resolve a channel, store it, and discover all its videos.

        Returns summary dict with channel_name, total_videos, new_videos.
        """
        # 1. Resolve channel metadata from YouTube
        channel_data = self.channel_fetcher.resolve_channel(channel_input)
        logger.info(f"Resolved channel: {channel_data['channel_name']}")

        # 2. Upsert channel in DB
        channel_db_id = self.repo.upsert_channel(channel_data)

        # 3. List all videos
        videos = self.channel_fetcher.list_all_videos(channel_data["channel_id"])

        # 4. Batch insert (skip duplicates)
        new_count = self.repo.insert_videos_batch(channel_db_id, videos)

        return {
            "channel_name": channel_data["channel_name"],
            "channel_id": channel_data["channel_id"],
            "channel_db_id": channel_db_id,
            "total_videos": len(videos),
            "new_videos": new_count,
        }

    def ingest(
        self,
        channel_db_id: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        """Process pending videos. Yields progress event dicts for the CLI.

        Events:
            {"event": "start", "total": int}
            {"event": "transcript_start", "video": str, "video_id": str}
            {"event": "transcript_fetched", "video": str, "word_count": int}
            {"event": "skipped", "video": str, "reason": str}
            {"event": "analysis_start", "video": str, "chunks": int}
            {"event": "completed", "video": str, "entries_count": int}
            {"event": "failed", "video": str, "error": str}
        """
        pending = self.repo.get_pending_videos(channel_db_id, limit)
        yield {"event": "start", "total": len(pending)}

        for video in pending:
            yield from self._process_video(video)

    def _process_video(self, video: dict):
        """Process a single video through the full pipeline."""
        title = video["title"]
        yt_video_id = video["video_id"]
        db_id = video["id"]

        # --- Step 1: Fetch transcript ---
        yield {"event": "transcript_start", "video": title, "video_id": yt_video_id}

        log_id = self.repo.log_processing_step(db_id, "fetch_transcript")

        try:
            transcript_data = self.transcript_fetcher.fetch_transcript(yt_video_id)
        except Exception as e:
            self.repo.update_video_status(db_id, "failed", str(e))
            self.repo.log_processing_step(
                db_id, "fetch_transcript", status="failed", error_message=str(e)
            )
            yield {"event": "failed", "video": title, "error": str(e)}
            return

        if transcript_data is None:
            self.repo.update_video_status(db_id, "skipped", "No transcript available")
            self.repo.complete_processing_step(log_id)
            yield {"event": "skipped", "video": title, "reason": "No transcript available"}
            return

        self.repo.insert_transcript(db_id, transcript_data)
        self.repo.update_video_status(db_id, "transcript_fetched")
        self.repo.complete_processing_step(log_id)

        yield {
            "event": "transcript_fetched",
            "video": title,
            "word_count": transcript_data["word_count"],
        }

        # --- Step 2: Analyze with Claude ---
        try:
            entries = self.analyzer.analyze_video(
                video_title=title,
                channel_name=video.get("channel_name", ""),
                snippets=transcript_data["snippets"],
                video_description=video.get("description", "") or "",
            )
        except Exception as e:
            self.repo.update_video_status(db_id, "failed", f"Analysis failed: {e}")
            yield {"event": "failed", "video": title, "error": str(e)}
            return

        chunks_count = len(self.analyzer.chunk_transcript(transcript_data["snippets"]))
        yield {"event": "analysis_start", "video": title, "chunks": chunks_count}

        # --- Step 3: Store knowledge entries ---
        total_tokens = 0
        for entry in entries:
            ke_id = self.repo.insert_knowledge_entry(
                {
                    "video_id": db_id,
                    "entry_type": entry["entry_type"],
                    "title": entry["title"],
                    "content": entry["content"],
                    "source_start_time": entry.get("source_start_time"),
                    "source_end_time": entry.get("source_end_time"),
                    "source_quote": entry.get("source_quote"),
                    "confidence": entry.get("confidence", 0.8),
                    "chunk_index": entry.get("chunk_index"),
                }
            )

            # Link categories
            for cat_name in entry.get("categories", []):
                cat_id = self.repo.get_or_create_category(cat_name)
                self.repo.link_knowledge_category(ke_id, cat_id)

            # Link tags
            for tag_name in entry.get("tags", []):
                tag_id = self.repo.get_or_create_tag(tag_name)
                self.repo.link_knowledge_tag(ke_id, tag_id)

            total_tokens += entry.get("_tokens_used", 0)

        # Log the analysis step
        self.repo.log_processing_step(
            db_id, "store_knowledge", status="completed", tokens_used=total_tokens
        )

        self.repo.update_video_status(db_id, "analyzed")
        yield {"event": "completed", "video": title, "entries_count": len(entries)}
