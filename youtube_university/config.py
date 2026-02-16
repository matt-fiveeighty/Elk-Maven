import os
import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def load_config() -> dict:
    """Load configuration from .env and config.yaml. Env vars take precedence."""
    load_dotenv(PROJECT_ROOT / ".env")

    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Resolve database path relative to project root
    db_rel = config.get("database", {}).get("path", "data/youtube_university.db")
    config["db_path"] = str(PROJECT_ROOT / db_rel)

    # Resolve log file path
    log_rel = config.get("logging", {}).get("file")
    if log_rel:
        config["log_file"] = str(PROJECT_ROOT / log_rel)
    else:
        config["log_file"] = None

    config["log_level"] = config.get("logging", {}).get("level", "INFO")

    return config


def get_ollama_config(config: dict) -> dict:
    """Extract Ollama-specific settings with defaults."""
    ollama = config.get("ollama", {})
    return {
        "model": ollama.get("model", "llama3.2"),
        "ollama_url": ollama.get("url", "http://localhost:11434"),
        "chunk_target_words": ollama.get("chunk_target_words", 2000),
        "chunk_overlap_words": ollama.get("chunk_overlap_words", 100),
        "max_retries": ollama.get("max_retries", 3),
        "retry_base_delay": ollama.get("retry_base_delay", 2.0),
    }


def get_transcript_config(config: dict) -> dict:
    """Extract transcript-specific settings with defaults."""
    tc = config.get("transcripts", {})
    return {
        "preferred_languages": tc.get("preferred_languages", ["en", "en-US", "en-GB"]),
        "fallback_to_generated": tc.get("fallback_to_generated", True),
    }
