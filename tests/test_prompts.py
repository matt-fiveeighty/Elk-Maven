"""Tests for prompt template builders."""
from __future__ import annotations

import pytest

from youtube_university.prompts.bias_detection import (
    BIAS_SYSTEM_PROMPT,
    build_bias_check_prompt,
)
from youtube_university.prompts.optimization import (
    OPTIMIZER_SYSTEM_PROMPT,
    build_categorize_prompt,
    build_tag_prompt,
    build_duplicate_check_prompt,
)


class TestBiasPrompts:
    def test_system_prompt_not_empty(self):
        assert len(BIAS_SYSTEM_PROMPT) > 100

    def test_system_prompt_mentions_json(self):
        assert "JSON" in BIAS_SYSTEM_PROMPT

    def test_build_bias_check_prompt(self):
        entries = [
            {"id": 1, "entry_type": "tip", "title": "Wind tips",
             "content": "Use wind checkers", "source_quote": "Always check wind"},
            {"id": 2, "entry_type": "insight", "title": "Gear advice",
             "content": "Sitka is great", "source_quote": None},
        ]
        prompt = build_bias_check_prompt(entries)
        assert "[Entry 1]" in prompt
        assert "[Entry 2]" in prompt
        assert "Wind tips" in prompt
        assert "Sitka is great" in prompt
        assert "is_biased" in prompt

    def test_build_bias_check_prompt_empty(self):
        prompt = build_bias_check_prompt([])
        assert "results" in prompt


class TestOptimizationPrompts:
    def test_optimizer_system_prompt(self):
        assert len(OPTIMIZER_SYSTEM_PROMPT) > 50
        assert "JSON" in OPTIMIZER_SYSTEM_PROMPT

    def test_build_categorize_prompt(self):
        entries = [
            {"id": 1, "entry_type": "tip", "title": "Elk movement",
             "content": "Elk move at dawn and dusk."},
        ]
        categories = ["Elk Hunting", "Gear", "Tactics"]
        prompt = build_categorize_prompt(entries, categories)
        assert "Elk Hunting" in prompt
        assert "[Entry 1]" in prompt
        assert "categories" in prompt

    def test_build_tag_prompt(self):
        entries = [
            {"id": 1, "entry_type": "tip", "title": "Thermals",
             "content": "Thermals rise in the morning."},
        ]
        prompt = build_tag_prompt(entries)
        assert "[Entry 1]" in prompt
        assert "tags" in prompt
        assert "lowercase" in prompt

    def test_build_duplicate_check_prompt(self):
        pairs = [
            (
                {"id": 1, "title": "Wind tips", "content": "Always check the wind direction."},
                {"id": 2, "title": "Wind advice", "content": "Check wind direction before approach."},
            ),
        ]
        prompt = build_duplicate_check_prompt(pairs)
        assert "Pair 1" in prompt
        assert "Entry A [1]" in prompt
        assert "Entry B [2]" in prompt
        assert "is_duplicate" in prompt
