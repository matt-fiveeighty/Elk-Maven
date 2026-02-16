from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Channel:
    channel_id: str
    channel_name: str
    channel_url: str
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    video_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Video:
    video_id: str
    channel_id: int
    title: str
    description: Optional[str] = None
    published_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    ingestion_status: str = "pending"
    failure_reason: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Transcript:
    video_id: int
    full_text: str
    snippet_data: str  # JSON string
    word_count: int
    language_code: str = "en"
    is_generated: bool = False
    id: Optional[int] = None


@dataclass
class KnowledgeEntry:
    video_id: int
    entry_type: str
    title: str
    content: str
    source_start_time: Optional[float] = None
    source_end_time: Optional[float] = None
    source_quote: Optional[str] = None
    confidence: float = 0.8
    chunk_index: Optional[int] = None
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    id: Optional[int] = None


@dataclass
class Category:
    name: str
    slug: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    id: Optional[int] = None
