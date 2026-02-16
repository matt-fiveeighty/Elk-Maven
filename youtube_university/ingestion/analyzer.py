from __future__ import annotations

import json
import logging

import requests

from ..prompts.transcript_analysis import SYSTEM_PROMPT, build_user_prompt
from ..utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

VALID_ENTRY_TYPES = {"insight", "tip", "concept", "technique", "warning", "resource", "quote"}

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class TranscriptAnalyzer:
    """Chunks transcripts and sends them to Ollama for knowledge extraction."""

    def __init__(
        self,
        model: str = "llama3.2",
        chunk_target_words: int = 2000,
        chunk_overlap_words: int = 100,
        max_retries: int = 3,
        retry_base_delay: float = 2.0,
        ollama_url: str = DEFAULT_OLLAMA_URL,
    ):
        self.model = model
        self.chunk_target_words = chunk_target_words
        self.chunk_overlap_words = chunk_overlap_words
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.ollama_url = ollama_url.rstrip("/")

    def chunk_transcript(self, snippets: list[dict]) -> list[dict]:
        """Split transcript snippets into chunks of ~chunk_target_words."""
        if not snippets:
            return []

        chunks = []
        current_words = []
        current_start = snippets[0].get("start", 0.0)
        current_end = current_start
        word_count = 0

        for snippet in snippets:
            text = snippet.get("text", "")
            start = snippet.get("start", 0.0)
            duration = snippet.get("duration", 0.0)

            words = text.split()
            current_words.extend(words)
            word_count += len(words)
            current_end = start + duration

            if word_count >= self.chunk_target_words:
                chunk_text = " ".join(current_words)
                chunks.append(
                    {
                        "index": len(chunks),
                        "text": chunk_text,
                        "start_time": current_start,
                        "end_time": current_end,
                        "word_count": word_count,
                    }
                )

                # Overlap: keep last N words for context
                overlap_words = current_words[-self.chunk_overlap_words :]
                current_words = overlap_words
                word_count = len(overlap_words)
                current_start = max(current_end - 10.0, 0.0)

        # Final chunk with remaining words
        if current_words:
            chunk_text = " ".join(current_words)
            chunks.append(
                {
                    "index": len(chunks),
                    "text": chunk_text,
                    "start_time": current_start,
                    "end_time": current_end,
                    "word_count": len(current_words),
                }
            )

        return chunks

    def analyze_video(
        self,
        video_title: str,
        channel_name: str,
        snippets: list[dict],
        video_description: str = "",
    ) -> list[dict]:
        """Analyze a full video transcript: chunk, send to Ollama, collect entries."""
        chunks = self.chunk_transcript(snippets)
        if not chunks:
            return []

        all_entries = []
        total_chunks = len(chunks)

        for chunk in chunks:
            try:
                entries = self._analyze_chunk(
                    chunk=chunk,
                    video_title=video_title,
                    channel_name=channel_name,
                    video_description=video_description,
                    total_chunks=total_chunks,
                )
                all_entries.extend(entries)
            except Exception as e:
                logger.error(
                    f"Failed to analyze chunk {chunk['index']} of '{video_title}': {e}"
                )

        logger.info(
            f"Extracted {len(all_entries)} entries from '{video_title}' "
            f"({total_chunks} chunks)"
        )
        return all_entries

    @retry_with_backoff(max_retries=3, base_delay=2.0)
    def _analyze_chunk(
        self,
        chunk: dict,
        video_title: str,
        channel_name: str,
        video_description: str,
        total_chunks: int,
    ) -> list[dict]:
        """Send a single chunk to Ollama and parse the JSON response."""
        user_prompt = build_user_prompt(
            chunk_text=chunk["text"],
            chunk_start_time=chunk["start_time"],
            chunk_end_time=chunk["end_time"],
            video_title=video_title,
            channel_name=channel_name,
            video_description=video_description,
            chunk_index=chunk["index"],
            total_chunks=total_chunks,
        )

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 4096,
                },
            },
            timeout=300,  # Local models can be slow
        )
        resp.raise_for_status()

        result = resp.json()
        response_text = result.get("message", {}).get("content", "").strip()

        # Strip markdown code fences if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error(
                f"Failed to parse JSON from Ollama for chunk {chunk['index']}: "
                f"{response_text[:200]}"
            )
            return []

        entries = data.get("entries", [])

        # Validate and annotate each entry
        validated = []
        for entry in entries:
            entry_type = entry.get("entry_type", "insight")
            if entry_type not in VALID_ENTRY_TYPES:
                entry_type = "insight"

            if not entry.get("title") or not entry.get("content"):
                continue  # Skip entries missing required fields

            validated.append(
                {
                    "entry_type": entry_type,
                    "title": entry["title"][:200],
                    "content": entry["content"],
                    "source_quote": (entry.get("source_quote") or "")[:500],
                    "source_start_time": entry.get("source_start_time", chunk["start_time"]),
                    "source_end_time": entry.get("source_end_time", chunk["end_time"]),
                    "confidence": max(0.0, min(1.0, float(entry.get("confidence", 0.8)))),
                    "categories": entry.get("categories", []),
                    "tags": entry.get("tags", []),
                    "chunk_index": chunk["index"],
                    "_tokens_used": 0,  # Local model, no token cost
                }
            )

        return validated
