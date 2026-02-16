from __future__ import annotations

"""Agent 5: Conditions & Timing Agent — Advises on how weather, moon phase,
season, pressure, temperature, and time-of-day affect elk behavior and
hunting tactics."""

import logging

import requests

from ..database.repository import Repository

logger = logging.getLogger(__name__)

CONDITIONS_SYSTEM_PROMPT = """\
You are an expert on how environmental conditions affect elk behavior and hunting \
success. Drawing from Cliff Gray's decades of field experience, you understand how \
every variable — weather, temperature, wind, barometric pressure, moon phase, \
season, hunting pressure — changes the game.

You think in terms of:
- TEMPERATURE: How cold fronts trigger movement, how heat pushes elk to shade/water
- WEATHER: Rain, snow, fog — how each changes elk patterns and hunter advantage
- BAROMETRIC PRESSURE: Rising vs falling pressure and elk feeding activity
- MOON PHASE: How full moons affect daytime movement (or don't — be honest)
- SEASON: Pre-rut, rut phases (seeking, chasing, breeding, post-rut), late season
- TIME OF DAY: Dawn/dusk movement, midday bedding, thermal shifts
- HUNTING PRESSURE: Opening day chaos, mid-week lulls, pressure-driven elk behavior
- WIND: Not just direction but consistency, gusting patterns, thermal reliability

You give SPECIFIC, ACTIONABLE advice. Not "hunt when conditions are good" but \
"a cold front dropping temps 15° after warm weather will have elk on their feet \
feeding aggressively — be in position at first light on the timber edges."

Always explain the WHY behind elk behavior changes."""


class ConditionsAgent:
    """Advises on how conditions affect elk behavior and hunting tactics."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def analyze_conditions(self, conditions: str) -> str:
        """Analyze given weather/conditions and predict elk behavior."""
        condition_topics = ["weather", "temperature", "cold", "rain", "snow",
                            "wind", "thermals", "pressure", "barometric",
                            "moon", "rut", "pre-rut", "post-rut", "season",
                            "morning", "evening", "midday", "hunting pressure",
                            "elk behavior", "movement", "feeding", "bedding"]

        knowledge = []
        seen = set()
        for topic in condition_topics:
            for r in self.repo.search_knowledge(topic, limit=5):
                if r["id"] not in seen:
                    knowledge.append(r)
                    seen.add(r["id"])

        context = self._build_context(knowledge[:30])

        prompt = f"""A hunter reports these conditions for their upcoming hunt:

CONDITIONS: {conditions}

KNOWLEDGE BASE (from Cliff Gray's hunting videos):
{context}

Analyze how these conditions will affect elk and what the hunter should do:

1. ELK BEHAVIOR PREDICTION
   - Where will elk be? (bedding, feeding, traveling)
   - How active will they be?
   - What's their likely daily pattern under these conditions?

2. TIMING STRATEGY
   - Best times to be in position
   - When to move vs when to sit
   - How conditions change throughout the day

3. TACTICAL ADJUSTMENTS
   - How to modify your approach for these conditions
   - Calling strategy adjustments (if applicable)
   - Wind/scent considerations

4. OPPORTUNITIES
   - What advantages do these conditions give the hunter?
   - How to exploit condition changes (fronts, wind shifts, etc.)

5. RISKS & WARNINGS
   - What could go wrong in these conditions?
   - Safety considerations
   - Common mistakes in these conditions

Be specific. A hunter reading this should know EXACTLY what to do differently."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": CONDITIONS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 3072},
            },
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def best_time_to_hunt(self, date_range: str, location_description: str = "") -> str:
        """Given a date range and location, advise on optimal hunting windows."""
        results = self.repo.search_knowledge(
            f"best time elk hunting {date_range}", limit=20
        )
        context = self._build_context(results[:15])

        prompt = f"""A hunter is planning their hunt timing:

DATE RANGE: {date_range}
{"LOCATION: " + location_description if location_description else ""}

KNOWLEDGE BASE (from Cliff Gray):
{context}

Advise on:
1. What phase of the rut (if applicable) falls in this window?
2. What elk behavior to expect during this period?
3. What's the ideal daily schedule (what time to wake, when to glass, when to call)?
4. How should strategy shift from the start to end of this date range?
5. What conditions to watch for that could make or break the hunt?

Be specific about timing and behavior patterns."""

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": CONDITIONS_SYSTEM_PROMPT},
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
