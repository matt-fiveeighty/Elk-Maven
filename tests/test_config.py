"""Tests for configuration loading."""
from __future__ import annotations

import os

import pytest

from youtube_university.config import load_config, get_ollama_config, get_transcript_config


class TestLoadConfig:
    def test_returns_dict(self):
        config = load_config()
        assert isinstance(config, dict)

    def test_has_db_path(self):
        config = load_config()
        assert "db_path" in config
        assert config["db_path"].endswith(".db")

    def test_has_log_level(self):
        config = load_config()
        assert "log_level" in config


class TestOllamaConfig:
    def test_defaults(self):
        cfg = get_ollama_config({})
        assert cfg["model"] == "llama3.2"
        assert cfg["ollama_url"] == "http://localhost:11434"
        assert cfg["chunk_target_words"] == 2000
        assert cfg["chunk_overlap_words"] == 100
        assert cfg["max_retries"] == 3

    def test_overrides(self):
        cfg = get_ollama_config({
            "ollama": {
                "model": "custom-model",
                "url": "http://custom:1234",
                "chunk_target_words": 5000,
            }
        })
        assert cfg["model"] == "custom-model"
        assert cfg["ollama_url"] == "http://custom:1234"
        assert cfg["chunk_target_words"] == 5000
        # Non-overridden defaults remain
        assert cfg["chunk_overlap_words"] == 100


class TestTranscriptConfig:
    def test_defaults(self):
        cfg = get_transcript_config({})
        assert "en" in cfg["preferred_languages"]
        assert cfg["fallback_to_generated"] is True

    def test_overrides(self):
        cfg = get_transcript_config({
            "transcripts": {
                "preferred_languages": ["es"],
                "fallback_to_generated": False,
            }
        })
        assert cfg["preferred_languages"] == ["es"]
        assert cfg["fallback_to_generated"] is False
