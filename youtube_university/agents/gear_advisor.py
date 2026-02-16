from __future__ import annotations

"""Agent 4: Gear & Equipment Advisor — Recommends gear setups, packing lists,
and equipment strategies based on knowledge base entries about gear, bows,
rifles, optics, clothing, and camp setup."""

import logging

import requests

from ..database.repository import Repository

logger = logging.getLogger(__name__)

GEAR_SYSTEM_PROMPT = """\
You are an expert hunting gear advisor. You draw from Cliff Gray's extensive \
experience outfitting for backcountry elk hunts — from archery setups to optics, \
packs, clothing systems, camp gear, and field processing equipment.

You prioritize:
- FUNCTION over brand loyalty — what actually works in the field
- WEIGHT vs UTILITY trade-offs for backcountry hunts
- LAYERING SYSTEMS that handle mountain weather swings
- OPTICS that match the terrain and hunting style
- ARCHERY/RIFLE setups appropriate for elk at realistic distances
- CAMP EFFICIENCY — lightweight but functional setups

When asked about gear, you:
1. Recommend specific categories and types (not just brands)
2. Explain WHY each piece matters in a hunting context
3. Prioritize what to spend money on vs where to save
4. Consider the specific hunt scenario (day hunt vs multi-day, archery vs rifle, etc.)
5. Warn about common gear mistakes

Be practical and direct. Hunters want real-world advice, not catalog descriptions."""


class GearAdvisorAgent:
    """Recommends gear based on knowledge base and hunt scenario."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def recommend_gear(self, scenario: str) -> str:
        """Build a gear list recommendation for a specific hunting scenario."""
        gear_topics = ["gear", "pack", "optics", "bow", "rifle", "arrow",
                       "broadhead", "clothing", "boots", "tent", "sleep",
                       "binoculars", "rangefinder", "camp", "knife", "water",
                       "food", "layering", "rain", "weight"]

        knowledge = []
        seen = set()
        for topic in gear_topics:
            for r in self.repo.search_knowledge(topic, limit=5):
                if r["id"] not in seen:
                    knowledge.append(r)
                    seen.add(r["id"])

        context = self._build_context(knowledge[:30])

        prompt = f"""A hunter needs gear recommendations for this scenario:

SCENARIO: {scenario}

KNOWLEDGE BASE (from Cliff Gray's videos):
{context}

Produce a comprehensive gear guide:

1. ESSENTIAL GEAR (must-have items)
   - Weapon system (bow/rifle specifics)
   - Optics (binos, rangefinder, spotting scope)
   - Pack system
   - Footwear

2. CLOTHING SYSTEM
   - Base layers
   - Insulation layers
   - Outer layers
   - Accessories (gloves, hat, gaiter, etc.)

3. CAMP GEAR (if applicable)
   - Shelter
   - Sleep system
   - Cooking/water
   - Game processing

4. NICE-TO-HAVE vs LEAVE-AT-HOME
   - What's worth the weight
   - Common over-packing mistakes

5. BUDGET PRIORITIES
   - Where to spend money
   - Where to save

Reference knowledge base entries where applicable. Be specific and practical."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": GEAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 3072},
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def evaluate_setup(self, gear_description: str) -> str:
        """Evaluate a hunter's current gear setup and suggest improvements."""
        results = self.repo.search_knowledge(gear_description, limit=20)
        context = self._build_context(results[:15])

        prompt = f"""A hunter describes their current gear setup:

GEAR SETUP: {gear_description}

KNOWLEDGE BASE (from Cliff Gray):
{context}

Evaluate this setup:
1. What's GOOD about this setup?
2. What's MISSING or needs upgrading?
3. What's UNNECESSARY weight?
4. What would Cliff Gray change?

Be honest and direct. Don't just validate — challenge where needed."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": GEAR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def _build_context(self, results: list[dict]) -> str:
        lines = []
        for i, r in enumerate(results, 1):
            video = r.get("video_title", "Unknown")
            lines.append(
                f"[{i}] ({r['entry_type']}) {r['title']}\n"
                f"    {r['content']}\n"
                f"    Video: {video}"
            )
        return "\n\n".join(lines)
