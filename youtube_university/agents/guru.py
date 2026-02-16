from __future__ import annotations

"""Hunting Guru — Unified conversational interface that routes questions to
the right specialist agent and maintains conversation context.

This is the "bounce ideas off of" hunting assistant the user wanted.
It acts as a smart router + conversationalist that draws on all agents."""

import logging
import re

import requests

from ..database.repository import Repository
from .synthesis import SynthesisAgent
from .strategist import StrategistAgent
from .gear_advisor import GearAdvisorAgent
from .conditions import ConditionsAgent

logger = logging.getLogger(__name__)

GURU_SYSTEM_PROMPT = """\
You are the Hunting Guru — an elite backcountry elk hunting advisor powered by \
Cliff Gray's extensive video library of hunting knowledge. You are the hunter's \
trusted companion for planning, strategy, gear, conditions, and in-the-field decisions.

Your personality:
- Direct and no-nonsense, like a seasoned guide
- You back up advice with reasoning and experience (from the knowledge base)
- You're honest about uncertainty — if the data doesn't cover something, say so
- You think tactically and practically
- You can go deep on any hunting topic: terrain, wind, thermals, calling, stalking, \
gear, fitness, field judging, game processing, and more

When a hunter asks you something:
1. Draw from the knowledge base to give SPECIFIC, GROUNDED answers
2. If relevant, cite which video/insight supports your point
3. Think about what the hunter REALLY needs to know (not just what they asked)
4. Offer follow-up suggestions — what should they think about next?

You're not a search engine. You're a thinking partner. Analyze, synthesize, and \
push back when a hunter's plan has holes.

IMPORTANT: You have access to a growing knowledge base extracted from Cliff Gray's \
YouTube channel. Reference specific entries when making claims. If the knowledge base \
doesn't cover a topic well yet, say so honestly."""

# Keywords that help route to specialist agents
TERRAIN_KEYWORDS = {"terrain", "map", "ridge", "saddle", "bench", "bowl", "creek",
                    "timber", "approach", "route", "glassing", "glass", "stalk",
                    "ambush", "topo", "topographic", "elevation", "north face",
                    "south face", "drainage", "canyon"}

GEAR_KEYWORDS = {"gear", "pack", "bow", "rifle", "optics", "binoculars", "scope",
                 "rangefinder", "boots", "clothing", "layers", "tent", "sleeping",
                 "knife", "broadhead", "arrow", "caliber", "ammunition", "rain gear",
                 "backpack", "camp", "stove", "water filter", "tarp"}

CONDITIONS_KEYWORDS = {"weather", "temperature", "cold", "hot", "rain", "snow",
                       "wind", "barometric", "pressure", "moon", "phase", "front",
                       "storm", "fog", "humidity", "forecast", "when to hunt",
                       "best time", "season", "rut", "pre-rut", "post-rut"}

STRATEGY_KEYWORDS = {"plan", "strategy", "hunt plan", "scenario", "situation",
                     "what should i do", "mistake", "bumped", "spooked", "bugle",
                     "call", "cow call", "setup", "morning", "evening"}


class HuntingGuru:
    """Unified conversational hunting advisor that routes to specialist agents."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

        # Initialize specialist agents
        self.synthesis = SynthesisAgent(repo, ollama_url, model)
        self.strategist = StrategistAgent(repo, ollama_url, model)
        self.gear = GearAdvisorAgent(repo, ollama_url, model)
        self.conditions = ConditionsAgent(repo, ollama_url, model)

        # Conversation history for context
        self.history: list[dict] = []

    def chat(self, message: str) -> str:
        """Process a message and return a response.

        Routes to specialist agents when appropriate, or handles
        directly for general conversation.
        """
        # Add to history
        self.history.append({"role": "user", "content": message})

        # Detect if this should route to a specialist
        route = self._detect_route(message)

        if route == "terrain":
            response = self._handle_terrain(message)
        elif route == "gear":
            response = self._handle_gear(message)
        elif route == "conditions":
            response = self._handle_conditions(message)
        elif route == "plan":
            response = self._handle_plan(message)
        else:
            response = self._handle_general(message)

        # Add response to history
        self.history.append({"role": "assistant", "content": response})

        # Keep history manageable (last 10 exchanges)
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return response

    def _detect_route(self, message: str) -> str:
        """Detect which specialist agent should handle this message."""
        msg_lower = message.lower()
        words = set(re.findall(r'\w+', msg_lower))

        # Score each category
        terrain_score = len(words & TERRAIN_KEYWORDS)
        gear_score = len(words & GEAR_KEYWORDS)
        conditions_score = len(words & CONDITIONS_KEYWORDS)
        strategy_score = len(words & STRATEGY_KEYWORDS)

        scores = {
            "terrain": terrain_score,
            "gear": gear_score,
            "conditions": conditions_score,
            "plan": strategy_score,
        }

        best = max(scores, key=scores.get)
        # Only route to specialist if there's a meaningful signal
        if scores[best] >= 2:
            return best

        # Check for specific phrases that indicate routing
        if any(phrase in msg_lower for phrase in [
            "analyze this terrain", "look at this map", "approach route",
            "glassing position", "where should i glass"
        ]):
            return "terrain"
        if any(phrase in msg_lower for phrase in [
            "what gear", "pack list", "what should i bring", "equipment",
            "what bow", "what rifle"
        ]):
            return "gear"
        if any(phrase in msg_lower for phrase in [
            "weather", "what time", "when should i", "cold front",
            "temperature", "moon phase"
        ]):
            return "conditions"
        if any(phrase in msg_lower for phrase in [
            "build a plan", "hunt plan", "what's my strategy",
            "what should i do", "game plan"
        ]):
            return "plan"

        return "general"

    def _handle_terrain(self, message: str) -> str:
        """Route terrain questions to the strategist agent."""
        try:
            return self.strategist.analyze_terrain(message)
        except Exception as e:
            logger.error(f"Strategist agent error: {e}")
            return self._handle_general(message)

    def _handle_gear(self, message: str) -> str:
        """Route gear questions to the gear advisor agent."""
        try:
            return self.gear.recommend_gear(message)
        except Exception as e:
            logger.error(f"Gear advisor error: {e}")
            return self._handle_general(message)

    def _handle_conditions(self, message: str) -> str:
        """Route conditions questions to the conditions agent."""
        try:
            return self.conditions.analyze_conditions(message)
        except Exception as e:
            logger.error(f"Conditions agent error: {e}")
            return self._handle_general(message)

    def _handle_plan(self, message: str) -> str:
        """Route plan requests to the synthesis agent."""
        try:
            return self.synthesis.build_hunt_plan(message)
        except Exception as e:
            logger.error(f"Synthesis agent error: {e}")
            return self._handle_general(message)

    def _handle_general(self, message: str) -> str:
        """Handle general questions using the knowledge base + conversation history."""
        # Search for relevant knowledge
        results = self.repo.search_knowledge(message, limit=20)
        context = self._build_context(results[:15])

        # Build conversation context from history
        messages = [{"role": "system", "content": GURU_SYSTEM_PROMPT}]

        # Include recent history for conversational context
        for h in self.history[-6:]:  # Last 3 exchanges
            if h["role"] == "user":
                messages.append({"role": "user", "content": h["content"]})
            else:
                messages.append({"role": "assistant", "content": h["content"]})

        # Build the current message with knowledge context
        if context:
            current_msg = f"""KNOWLEDGE BASE ENTRIES (from Cliff Gray's videos):
{context}

HUNTER'S QUESTION: {message}

Draw from the knowledge base above to give a thorough, grounded answer. \
Cite specific entries. Think about what else the hunter should consider."""
        else:
            current_msg = f"""HUNTER'S QUESTION: {message}

Note: No directly relevant entries found in the knowledge base for this specific query. \
Answer based on general hunting knowledge from the knowledge base context, and note \
that more data may become available as ingestion continues."""

        # Replace the last user message with the enriched version
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = current_msg
        else:
            messages.append({"role": "user", "content": current_msg})

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "No response generated.")

    def get_briefing(self) -> str:
        """Get a knowledge base status briefing."""
        return self.synthesis.daily_briefing()

    def _build_context(self, results: list[dict]) -> str:
        """Format knowledge entries as context for the LLM, with bias caveats."""
        lines = []
        for i, r in enumerate(results, 1):
            video = r.get("video_title", "Unknown")
            entry = (
                f"[{i}] ({r['entry_type']}) {r['title']}\n"
                f"    {r['content']}\n"
                f"    Video: {video}"
            )

            # Check for bias flags and add caveats
            try:
                flags = self.repo.get_bias_flags_for_entry(r["id"])
                if flags:
                    brands = []
                    for f in flags:
                        if f.get("brand_names"):
                            import json
                            try:
                                brands.extend(json.loads(f["brand_names"]))
                            except (json.JSONDecodeError, TypeError):
                                pass
                    if brands:
                        entry += (
                            f"\n    [BIAS NOTE: References brands ({', '.join(brands)}) "
                            f"— consider generic alternatives]"
                        )
                    else:
                        entry += (
                            f"\n    [BIAS NOTE: May contain commercial bias — "
                            f"{flags[0]['bias_type']}]"
                        )
            except Exception:
                pass  # Don't let bias checking break the response

            lines.append(entry)
        return "\n\n".join(lines)
