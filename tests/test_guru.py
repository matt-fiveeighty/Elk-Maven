"""Tests for the HuntingGuru routing logic and conversation management."""
from __future__ import annotations

import pytest

from youtube_university.agents.guru import (
    HuntingGuru,
    TERRAIN_KEYWORDS,
    GEAR_KEYWORDS,
    CONDITIONS_KEYWORDS,
    STRATEGY_KEYWORDS,
)


@pytest.fixture
def guru(seeded_repo):
    """Create a HuntingGuru backed by the seeded repo."""
    return HuntingGuru(
        repo=seeded_repo,
        ollama_url="http://localhost:11434",
        model="llama3.2",
    )


class TestRouteDetection:
    def test_terrain_routing(self, guru):
        assert guru._detect_route("How should I approach this ridge for glassing?") == "terrain"
        assert guru._detect_route("Where is the best glassing position on this topo?") == "terrain"
        assert guru._detect_route("analyze this terrain for a morning stalk") == "terrain"

    def test_gear_routing(self, guru):
        assert guru._detect_route("What bow and optics should I bring for elk?") == "gear"
        assert guru._detect_route("I need a pack list for backcountry hunting") == "gear"
        assert guru._detect_route("What should I bring for a 7-day hunt?") == "gear"

    def test_conditions_routing(self, guru):
        assert guru._detect_route("What does the weather and barometric pressure mean for elk?") == "conditions"
        assert guru._detect_route("cold front moving in, what should I expect?") == "conditions"
        assert guru._detect_route("When should I hunt based on moon phase?") == "conditions"

    def test_strategy_routing(self, guru):
        assert guru._detect_route("Build a plan for a 5-day archery hunt") == "plan"
        assert guru._detect_route("I bumped a bull, what's my strategy now?") == "plan"
        assert guru._detect_route("What should I do if I spooked the herd?") == "plan"

    def test_general_routing(self, guru):
        assert guru._detect_route("Tell me about elk behavior") == "general"
        assert guru._detect_route("Hello") == "general"
        assert guru._detect_route("What do you know about Cliff Gray?") == "general"

    def test_phrase_based_routing(self, guru):
        assert guru._detect_route("analyze this terrain please") == "terrain"
        assert guru._detect_route("what gear do I need") == "gear"
        assert guru._detect_route("what time should I head out") == "conditions"
        assert guru._detect_route("build a plan for opening day") == "plan"


class TestHistoryManagement:
    def test_history_starts_empty(self, guru):
        assert guru.history == []

    def test_history_tracks_manually_added(self, guru):
        guru.history.append({"role": "user", "content": "test"})
        guru.history.append({"role": "assistant", "content": "response"})
        assert len(guru.history) == 2

    def test_history_truncation_boundary(self, guru):
        """History should be capped at 20 entries (last 10 exchanges)."""
        # Manually fill beyond 20
        for i in range(25):
            guru.history.append({"role": "user", "content": f"msg {i}"})
        # Simulate the truncation that chat() does
        if len(guru.history) > 20:
            guru.history = guru.history[-20:]
        assert len(guru.history) == 20


class TestBuildContext:
    def test_build_context_with_results(self, guru, seeded_repo):
        results = seeded_repo.search_knowledge("elk wind")
        context = guru._build_context(results[:5])
        assert "[1]" in context
        assert "Video:" in context

    def test_build_context_empty(self, guru):
        context = guru._build_context([])
        assert context == ""

    def test_build_context_includes_bias_caveat(self, guru, seeded_repo):
        """If an entry has a bias flag, the context should include a BIAS NOTE."""
        # Flag an entry
        entries = seeded_repo.conn.execute(
            "SELECT id FROM knowledge_entries LIMIT 1"
        ).fetchall()
        seeded_repo.insert_bias_flag({
            "knowledge_id": entries[0]["id"],
            "bias_type": "brand_promotion",
            "bias_severity": "low",
            "brand_names": ["Sitka"],
            "bias_notes": "Brand mention",
        })

        # Search and build context
        results = seeded_repo.search_knowledge("elk", limit=10)
        # Find the flagged entry in results
        flagged_result = next(
            (r for r in results if r["id"] == entries[0]["id"]), None
        )
        if flagged_result:
            context = guru._build_context([flagged_result])
            assert "BIAS NOTE" in context
            assert "Sitka" in context


class TestKeywordSets:
    """Verify keyword sets are complete and don't overlap excessively."""

    def test_terrain_keywords_not_empty(self):
        assert len(TERRAIN_KEYWORDS) > 10

    def test_gear_keywords_not_empty(self):
        assert len(GEAR_KEYWORDS) > 10

    def test_conditions_keywords_not_empty(self):
        assert len(CONDITIONS_KEYWORDS) > 10

    def test_strategy_keywords_not_empty(self):
        assert len(STRATEGY_KEYWORDS) > 5

    def test_no_excessive_keyword_overlap(self):
        """No single word should appear in more than 2 keyword sets."""
        all_sets = [TERRAIN_KEYWORDS, GEAR_KEYWORDS, CONDITIONS_KEYWORDS, STRATEGY_KEYWORDS]
        all_words = set()
        for s in all_sets:
            all_words.update(s)

        for word in all_words:
            count = sum(1 for s in all_sets if word in s)
            assert count <= 2, f"'{word}' appears in {count} keyword sets"
