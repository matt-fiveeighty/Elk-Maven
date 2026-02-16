from __future__ import annotations

import logging
import time

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

logger = logging.getLogger(__name__)


# IpBlocked may not exist in all versions, import safely
try:
    from youtube_transcript_api._errors import IpBlocked
except ImportError:
    IpBlocked = None


class TranscriptFetcher:
    """Fetches video transcripts using youtube-transcript-api."""

    def __init__(self, preferred_languages: list[str] = None):
        self.api = YouTubeTranscriptApi()
        self.preferred_languages = preferred_languages or ["en", "en-US", "en-GB"]
        self._ip_blocked = False

    @property
    def is_blocked(self) -> bool:
        """True if YouTube is currently blocking transcript requests."""
        return self._ip_blocked

    def fetch_transcript(self, video_id: str) -> dict | None:
        """Fetch transcript for a video. Returns dict or None if unavailable.

        Raises RuntimeError if YouTube is IP-blocking us (caller should stop).
        """
        try:
            transcript = self.api.fetch(video_id, languages=self.preferred_languages)
            snippets = transcript.to_raw_data()
            full_text = " ".join(s["text"] for s in snippets)

            self._ip_blocked = False  # Reset on success
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
            # Check for IpBlocked (class or string match for forward compat)
            if (IpBlocked and isinstance(e, IpBlocked)) or "IpBlocked" in type(e).__name__:
                self._ip_blocked = True
                raise RuntimeError(
                    "YouTube is rate-limiting/IP-blocking transcript requests. "
                    "Wait a few hours and retry with: ytuni retry-skipped"
                ) from e
            logger.warning(f"Unexpected error fetching transcript for {video_id}: {e}")
            return None
