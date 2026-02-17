from __future__ import annotations

import logging
import random
import time

from requests import Session

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
    """Fetches video transcripts using youtube-transcript-api.

    Uses a fresh requests Session per fetch and adds random delays
    between requests to avoid YouTube IP-blocking.
    """

    def __init__(self, preferred_languages: list[str] = None,
                 delay_range: tuple[float, float] = (2.0, 5.0)):
        self.preferred_languages = preferred_languages or ["en", "en-US", "en-GB"]
        self._ip_blocked = False
        self._delay_range = delay_range
        self._request_count = 0

    def _make_api(self) -> YouTubeTranscriptApi:
        """Create a fresh API instance with a new session to rotate cookies."""
        session = Session()
        session.headers.update({
            "Accept-Language": "en-US,en;q=0.9",
        })
        return YouTubeTranscriptApi(http_client=session)

    @property
    def is_blocked(self) -> bool:
        """True if YouTube is currently blocking transcript requests."""
        return self._ip_blocked

    def fetch_transcript(self, video_id: str) -> dict | None:
        """Fetch transcript for a video. Returns dict or None if unavailable.

        Raises RuntimeError if YouTube is IP-blocking us (caller should stop).
        """
        # Throttle: add delay between requests to avoid triggering blocks
        if self._request_count > 0:
            delay = random.uniform(*self._delay_range)
            time.sleep(delay)
        self._request_count += 1

        try:
            api = self._make_api()
            transcript = api.fetch(video_id, languages=self.preferred_languages)
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
