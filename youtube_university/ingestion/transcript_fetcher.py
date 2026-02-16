from __future__ import annotations

import logging

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)


class TranscriptFetcher:
    """Fetches video transcripts using youtube-transcript-api."""

    def __init__(self, preferred_languages: list[str] = None):
        self.api = YouTubeTranscriptApi()
        self.preferred_languages = preferred_languages or ["en", "en-US", "en-GB"]

    def fetch_transcript(self, video_id: str) -> dict | None:
        """Fetch transcript for a video. Returns dict or None if unavailable."""
        try:
            transcript = self.api.fetch(video_id, languages=self.preferred_languages)
            snippets = transcript.to_raw_data()
            full_text = " ".join(s["text"] for s in snippets)

            return {
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "snippets": snippets,
                "full_text": full_text,
                "word_count": len(full_text.split()),
            }
        except (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        ) as e:
            logger.info(f"No transcript for {video_id}: {type(e).__name__}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error fetching transcript for {video_id}: {e}")
            return None
