from __future__ import annotations

"""Agent 2: Synthesis Agent — Analyzes the knowledge base and produces
actionable hunting plans, deductions, and cross-video insights."""

import json
import logging

import requests

from ..database.repository import Repository

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """\
You are an expert hunting strategist and advisor. You have access to a knowledge base \
extracted from Cliff Gray's YouTube channel — one of the most respected elk hunting \
educators in the country.

Your job is to synthesize this knowledge into actionable hunting advice. You should:
1. Cross-reference insights from multiple videos to find patterns
2. Identify non-obvious connections between concepts
3. Produce specific, actionable plans — not generic advice
4. Always cite which video/insight your advice comes from
5. Think like a guide who has spent decades in the field

When producing plans, format them as clear step-by-step strategies with reasoning.
When asked questions, draw from the knowledge base and explain your reasoning.

Respond in clear, direct language. No fluff. Hunters want actionable intel."""


class SynthesisAgent:
    """Queries the knowledge base and uses Ollama to synthesize insights."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def ask(self, question: str) -> str:
        """Ask a question and get a synthesized answer from the knowledge base."""
        # Search for relevant knowledge
        results = self.repo.search_knowledge(question, limit=15)

        if not results:
            return "No relevant knowledge found in the database yet. Ingest more videos first."

        # Build context from search results
        context = self._build_context(results)

        # Send to Ollama for synthesis
        prompt = f"""Based on the following knowledge extracted from Cliff Gray's hunting videos, \
answer this question:

QUESTION: {question}

KNOWLEDGE BASE ENTRIES:
{context}

Synthesize these into a clear, actionable answer. Reference specific entries when making claims. \
If the knowledge base doesn't fully answer the question, say what you can deduce and what's missing."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def build_hunt_plan(self, scenario: str) -> str:
        """Build a comprehensive hunting plan based on a scenario description."""
        # Pull broad knowledge across categories
        categories = ["elk", "wind", "glassing", "calling", "sign", "stalk",
                       "camp", "gear", "fitness", "mistakes", "public land",
                       "terrain", "thermals", "scent", "rut", "archery", "rifle"]

        all_knowledge = []
        seen_ids = set()
        for cat in categories:
            results = self.repo.search_knowledge(cat, limit=8)
            for r in results:
                if r["id"] not in seen_ids:
                    all_knowledge.append(r)
                    seen_ids.add(r["id"])

        context = self._build_context(all_knowledge[:40])

        prompt = f"""Create a detailed, day-by-day hunting plan for this scenario:

SCENARIO: {scenario}

KNOWLEDGE BASE ({len(all_knowledge)} entries from Cliff Gray's videos):
{context}

Create a specific plan that includes:
1. PRE-HUNT PREPARATION (fitness, gear, scouting)
2. DAY-BY-DAY STRATEGY (what to do each day, where to focus)
3. WIND & THERMALS (how to read and use them)
4. SIGN READING (what to look for and what it means)
5. APPROACH TACTICS (stalking, calling, ambush setups)
6. COMMON MISTAKES TO AVOID (based on the knowledge base)
7. CONTINGENCY PLANS (what to do when things go wrong)

Be specific and tactical. Reference knowledge base entries to support your recommendations."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 4096},
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def daily_briefing(self) -> str:
        """Generate a briefing of the latest knowledge added to the database."""
        # Get the most recent entries
        rows = self.repo.conn.execute("""
            SELECT ke.entry_type, ke.title, ke.content, ke.confidence,
                   v.title as video_title, c.channel_name
            FROM knowledge_entries ke
            JOIN videos v ON ke.video_id = v.id
            JOIN channels c ON v.channel_id = c.id
            ORDER BY ke.created_at DESC
            LIMIT 30
        """).fetchall()

        if not rows:
            return "No knowledge in the database yet."

        stats = self.repo.get_ingestion_stats()
        entries_text = "\n".join(
            f"- [{r['entry_type']}] {r['title']}: {r['content'][:150]}..."
            for r in rows
        )

        prompt = f"""Here are the latest knowledge entries extracted from hunting videos:

DATABASE STATUS:
- {stats['total_videos']} total videos tracked
- {stats.get('videos_by_status', {}).get('analyzed', 0)} analyzed so far
- {stats['knowledge_entries']} total knowledge entries

LATEST ENTRIES:
{entries_text}

Produce a concise briefing that:
1. Summarizes the KEY themes and patterns emerging from the data
2. Highlights the most actionable insights
3. Notes any contradictions or areas needing more data
4. Suggests what topics a hunter should focus on studying next"""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def _build_context(self, results: list[dict]) -> str:
        """Format knowledge entries as context for the LLM."""
        lines = []
        for i, r in enumerate(results, 1):
            video = r.get("video_title", "Unknown")
            entry = (
                f"[{i}] ({r['entry_type']}, {r['confidence']:.0%} confidence) "
                f"{r['title']}\n"
                f"    {r['content']}\n"
                f"    Source: \"{r.get('source_quote', 'N/A')}\"\n"
                f"    Video: {video}"
            )
            lines.append(entry)
        return "\n\n".join(lines)
