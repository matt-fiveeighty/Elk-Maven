from __future__ import annotations

"""Agent 3: Strategy Agent — Analyzes terrain, maps, and scenarios to produce
tactical hunting recommendations grounded in the knowledge base."""

import json
import logging

import requests

from ..database.repository import Repository

logger = logging.getLogger(__name__)

STRATEGIST_SYSTEM_PROMPT = """\
You are an elite backcountry elk hunting tactician. You combine decades of guiding \
knowledge (from Cliff Gray's extensive video library) with terrain analysis skills.

When given terrain descriptions, maps, or screenshots:
1. Identify likely elk holding areas (north-facing timber, saddles, benches, water sources)
2. Deduce wind patterns based on terrain (thermals flow uphill in morning, downhill in evening)
3. Recommend approach routes that keep the wind in your favor
4. Identify glassing positions with maximum visibility
5. Suggest ambush points based on likely travel corridors
6. Consider time of year, pressure levels, and elk behavior patterns

You think in terms of:
- TERRAIN: ridges, saddles, benches, bowls, creek bottoms, timber edges
- WIND: prevailing winds, thermals, swirling zones, wind funnels
- ELK BEHAVIOR: feeding areas (parks/meadows), bedding (dark timber, north slopes), \
travel corridors (saddles, ridgelines), water sources
- PRESSURE: how hunting pressure pushes elk, escape routes, sanctuary areas
- TIME: how elk movement changes morning vs evening, pre-rut vs rut vs post-rut

Always explain your reasoning. A hunter should understand WHY you're recommending something, \
not just WHAT to do."""


class StrategistAgent:
    """Analyzes terrain and scenarios to produce tactical hunting plans."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def analyze_terrain(self, description: str) -> str:
        """Analyze a terrain description and produce tactical recommendations."""
        # Pull relevant tactical knowledge
        tactical_topics = ["wind", "thermals", "glassing", "stalk", "terrain",
                           "bedding", "feeding", "approach", "ambush", "sign",
                           "pressure", "escape", "saddle", "timber"]

        knowledge = []
        seen = set()
        for topic in tactical_topics:
            for r in self.repo.search_knowledge(topic, limit=5):
                if r["id"] not in seen:
                    knowledge.append(r)
                    seen.add(r["id"])

        context = self._build_context(knowledge[:30])

        prompt = f"""Analyze this terrain and produce a tactical hunting plan:

TERRAIN DESCRIPTION:
{description}

KNOWLEDGE BASE (from Cliff Gray's hunting videos):
{context}

Produce a detailed tactical analysis:

1. TERRAIN READING
   - Where elk are likely bedding, feeding, and traveling
   - Key terrain features (saddles, benches, timber edges, water)

2. WIND & THERMALS
   - Expected wind patterns for this terrain
   - Morning vs evening thermal flows
   - Danger zones where wind swirls

3. GLASSING POSITIONS
   - Best spots to glass from and why
   - What to look for at different times of day

4. APPROACH ROUTES
   - How to get in without being detected
   - Wind-safe approach corridors
   - Timing (when to move)

5. AMBUSH / SETUP POINTS
   - Where to set up for archery vs rifle
   - Calling positions if applicable

6. ESCAPE ROUTES & CONTINGENCIES
   - Where elk will go if bumped
   - How to recover from mistakes

Be specific and tactical. Reference knowledge base entries where applicable."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": STRATEGIST_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def analyze_map_description(self, map_description: str, hunt_details: str = "") -> str:
        """Analyze a described map/screenshot and produce approach strategies.

        Since we can't process images directly through Ollama, the user describes
        what they see on the map (or we get a text description from the CLI).
        """
        knowledge = []
        seen = set()
        for topic in ["approach", "wind", "glassing", "stalk", "elk behavior",
                       "terrain", "pressure", "calling"]:
            for r in self.repo.search_knowledge(topic, limit=5):
                if r["id"] not in seen:
                    knowledge.append(r)
                    seen.add(r["id"])

        context = self._build_context(knowledge[:25])

        prompt = f"""A hunter is showing you their hunting area map. Here's what they describe:

MAP DESCRIPTION:
{map_description}

{"HUNT DETAILS: " + hunt_details if hunt_details else ""}

KNOWLEDGE BASE (from Cliff Gray):
{context}

Based on this map, provide:

1. APPROACH ANGLES — rank the best 2-3 approach routes and explain why
2. GLASSING POINTS — where to set up optics and what you'll be able to see
3. LIKELY ELK ZONES — where elk are probably bedding, feeding, watering
4. WIND CONSIDERATIONS — which approaches work in morning vs evening thermals
5. DANGER ZONES — areas to avoid (wind swirls, skylining, noisy terrain)
6. GAME PLAN — a step-by-step plan for hunting this area

Be specific about directions, terrain features, and timing."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": STRATEGIST_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def evaluate_scenario(self, scenario: str) -> str:
        """Evaluate a hunting scenario and give tactical advice."""
        # Search for relevant knowledge based on the scenario
        results = self.repo.search_knowledge(scenario, limit=20)
        context = self._build_context(results[:15])

        prompt = f"""A hunter describes this situation:

SCENARIO: {scenario}

RELEVANT KNOWLEDGE (from Cliff Gray):
{context}

Give direct, tactical advice:
1. What should the hunter do RIGHT NOW?
2. What are the biggest risks in this situation?
3. What would Cliff Gray likely recommend based on his teachings?
4. What's the most common mistake hunters make in this scenario?

Be direct and specific. No hedging."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": STRATEGIST_SYSTEM_PROMPT},
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
