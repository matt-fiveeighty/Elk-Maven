from __future__ import annotations

import json
import re
import logging
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse"
CLIENT_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00",
        "hl": "en",
        "gl": "US",
    }
}


class ChannelFetcher:
    """Fetches channel info and video lists from YouTube without an API key."""

    def resolve_channel(self, channel_input: str) -> dict:
        """Accept a channel URL, @handle, or channel ID. Return channel metadata."""
        page_url = self._build_channel_url(channel_input)

        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        # Extract ytInitialData JSON from the page
        match = re.search(r"var ytInitialData = ({.*?});</script>", resp.text)
        if not match:
            raise ValueError(f"Could not parse channel page: {channel_input}")

        data = json.loads(match.group(1))

        # Extract channel metadata from the page data
        metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
        if not metadata:
            raise ValueError(f"Channel not found: {channel_input}")

        channel_id = metadata.get("externalId", "")
        header = data.get("header", {}).get("c4TabbedHeaderRenderer", {})

        return {
            "channel_id": channel_id,
            "channel_name": metadata.get("title", "Unknown"),
            "channel_url": metadata.get("channelUrl", page_url),
            "description": metadata.get("description"),
            "subscriber_count": None,  # Not reliably available without API
            "video_count": None,
            "thumbnail_url": (
                metadata.get("avatar", {}).get("thumbnails", [{}])[0].get("url")
            ),
        }

    def _build_channel_url(self, channel_input: str) -> str:
        """Convert various input formats to a channel /videos page URL."""
        channel_input = channel_input.strip()

        # Already a full URL
        if channel_input.startswith("http"):
            parsed = urlparse(channel_input)
            path = parsed.path.rstrip("/")
            # Make sure we hit the /videos tab
            if not path.endswith("/videos"):
                return f"https://www.youtube.com{path}/videos"
            return channel_input

        # @handle
        if channel_input.startswith("@"):
            return f"https://www.youtube.com/{channel_input}/videos"

        # Direct channel ID
        if re.match(r"^UC[\w-]{22}$", channel_input):
            return f"https://www.youtube.com/channel/{channel_input}/videos"

        # Assume it's a handle without @
        return f"https://www.youtube.com/@{channel_input}/videos"

    def list_all_videos(self, channel_id: str) -> list[dict]:
        """List all videos from a channel by scraping the /videos tab."""
        page_url = f"https://www.youtube.com/channel/{channel_id}/videos"

        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        match = re.search(r"var ytInitialData = ({.*?});</script>", resp.text)
        if not match:
            raise ValueError(f"Could not parse videos page for channel {channel_id}")

        data = json.loads(match.group(1))

        # Find the videos tab content
        videos = []
        continuation_token = None

        tabs = (
            data.get("contents", {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs", [])
        )

        for tab in tabs:
            tab_content = tab.get("tabRenderer", {}).get("content", {})
            grid = tab_content.get("richGridRenderer", {})
            if not grid:
                continue

            for item in grid.get("contents", []):
                video = self._extract_video(item)
                if video:
                    videos.append(video)

                # Check for continuation
                cont = item.get("continuationItemRenderer", {})
                if cont:
                    continuation_token = (
                        cont.get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token")
                    )

        logger.debug(f"Initial page: {len(videos)} videos")

        # Paginate through continuation tokens
        while continuation_token:
            time.sleep(0.5)  # Be polite
            payload = {"context": CLIENT_CONTEXT, "continuation": continuation_token}

            try:
                resp = requests.post(
                    BROWSE_URL, json=payload, headers=HEADERS, timeout=15
                )
                resp.raise_for_status()
                cont_data = resp.json()
            except Exception as e:
                logger.warning(f"Continuation request failed: {e}")
                break

            continuation_token = None

            actions = cont_data.get("onResponseReceivedActions", [])
            for action in actions:
                items = action.get("appendContinuationItemsAction", {}).get(
                    "continuationItems", []
                )
                for item in items:
                    video = self._extract_video(item)
                    if video:
                        videos.append(video)

                    cont = item.get("continuationItemRenderer", {})
                    if cont:
                        continuation_token = (
                            cont.get("continuationEndpoint", {})
                            .get("continuationCommand", {})
                            .get("token")
                        )

            logger.debug(f"Paginated: {len(videos)} videos total")

        logger.info(f"Found {len(videos)} videos for channel {channel_id}")
        return videos

    def _extract_video(self, item: dict) -> dict | None:
        """Extract video info from a richItemRenderer."""
        renderer = (
            item.get("richItemRenderer", {}).get("content", {}).get("videoRenderer", {})
        )
        vid = renderer.get("videoId")
        if not vid:
            return None

        title = renderer.get("title", {}).get("runs", [{}])[0].get("text", "")
        description_snippet = renderer.get("descriptionSnippet", {})
        description = ""
        if description_snippet:
            description = "".join(
                r.get("text", "") for r in description_snippet.get("runs", [])
            )

        published = renderer.get("publishedTimeText", {}).get("simpleText")

        thumbnail = None
        thumbs = renderer.get("thumbnail", {}).get("thumbnails", [])
        if thumbs:
            thumbnail = thumbs[-1].get("url")

        return {
            "video_id": vid,
            "title": title,
            "description": description,
            "published_at": published,  # Relative like "3 months ago" (not ISO)
            "thumbnail_url": thumbnail,
        }
