"""Tests for the BiasDetectorAgent — heuristic checks and scanning."""
from __future__ import annotations

import pytest

from youtube_university.agents.bias_detector import (
    BiasDetectorAgent,
    BRAND_PATTERNS,
    AFFILIATE_PATTERNS,
    PROMOTIONAL_PATTERNS,
)


@pytest.fixture
def detector(seeded_repo):
    """Create a BiasDetectorAgent backed by the seeded repo."""
    return BiasDetectorAgent(
        repo=seeded_repo,
        ollama_url="http://localhost:11434",
        model="llama3.2",
    )


class TestHeuristicCheck:
    def test_detects_brand_mention(self, detector):
        entry = {
            "id": 1,
            "title": "Best bow for elk",
            "content": "I always use my Hoyt RX-7 for backcountry hunts.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        assert len(result["brands"]) > 0
        assert any("hoyt" in b.lower() for b in result["brands"])

    def test_detects_affiliate_language(self, detector):
        entry = {
            "id": 2,
            "title": "Gear recommendation",
            "content": "Use my code HUNT20 for 10% off at the store.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        assert result["has_affiliate"] is True

    def test_detects_promotional_language(self, detector):
        entry = {
            "id": 3,
            "title": "Camo review",
            "content": "This is hands down the best camo on the market for elk.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        assert result["has_promo"] is True

    def test_clean_entry_passes(self, detector):
        entry = {
            "id": 4,
            "title": "Wind strategy",
            "content": "Always approach from downwind. Thermals shift at dawn.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is None

    def test_multiple_brands_detected(self, detector):
        entry = {
            "id": 5,
            "title": "My favorite setup",
            "content": "I run Sitka camo with Kenetrek boots and Vortex optics.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        brands_lower = [b.lower() for b in result["brands"]]
        assert "sitka" in brands_lower
        assert "kenetrek" in brands_lower
        assert "vortex" in brands_lower

    def test_detects_discount_code(self, detector):
        entry = {
            "id": 6,
            "title": "New product",
            "content": "Get a discount code from the link in description.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        assert result["has_affiliate"] is True

    def test_case_insensitive_brand_detection(self, detector):
        entry = {
            "id": 7,
            "title": "Optics",
            "content": "I switched to LEUPOLD scopes last year.",
            "source_quote": "",
        }
        result = detector._heuristic_check(entry)
        assert result is not None
        assert any("leupold" in b.lower() for b in result["brands"])


class TestHeuristicToFlag:
    def test_affiliate_flag_priority(self, detector):
        entry = {"id": 1, "title": "Test", "content": "Test"}
        heuristic = {"brands": ["Sitka"], "has_affiliate": True, "has_promo": False}
        flag = detector._heuristic_to_flag(entry, heuristic)
        assert flag["bias_type"] == "affiliate"
        assert flag["bias_severity"] == "medium"

    def test_promo_flag_priority(self, detector):
        entry = {"id": 2, "title": "Test", "content": "Test"}
        heuristic = {"brands": [], "has_affiliate": False, "has_promo": True}
        flag = detector._heuristic_to_flag(entry, heuristic)
        assert flag["bias_type"] == "unsubstantiated_claim"

    def test_brand_only_flag(self, detector):
        entry = {"id": 3, "title": "Test", "content": "Test"}
        heuristic = {"brands": ["Hoyt"], "has_affiliate": False, "has_promo": False}
        flag = detector._heuristic_to_flag(entry, heuristic)
        assert flag["bias_type"] == "brand_promotion"
        assert flag["bias_severity"] == "low"

    def test_flag_includes_entry_id(self, detector):
        entry = {"id": 42, "title": "Test", "content": "Test"}
        heuristic = {"brands": ["Sitka"], "has_affiliate": False, "has_promo": False}
        flag = detector._heuristic_to_flag(entry, heuristic)
        assert flag["knowledge_id"] == 42
        assert flag["detected_by"] == "heuristic_fallback"


class TestScanAll:
    def test_scan_yields_progress_events(self, detector):
        events = list(detector.scan_all(batch_size=3))
        assert len(events) > 0

        # First event should be "start"
        assert events[0]["event"] == "start"
        assert events[0]["total"] == 6  # 6 entries in seeded_repo

        # Last event should be "complete"
        assert events[-1]["event"] == "complete"
        assert events[-1]["total"] == 6

    def test_scan_on_empty_db(self, repo):
        """Scanning with no entries should yield a single complete event."""
        det = BiasDetectorAgent(repo, "http://localhost:11434", "llama3.2")
        events = list(det.scan_all())
        assert len(events) == 1
        assert events[0]["event"] == "complete"
        assert events[0]["total"] == 0

    def test_scan_flags_biased_entry(self, detector, seeded_repo):
        """The seeded 'Sitka Gear Review' entry should be caught by heuristics.
        Since Ollama may not be running in CI, the fallback heuristic flags it."""
        events = list(detector.scan_all(batch_size=10))
        complete = events[-1]
        assert complete["flagged"] >= 1

        # Verify the flag was stored in the DB
        summary = seeded_repo.get_bias_summary()
        assert summary["total_flags"] >= 1


class TestPatternCompleteness:
    """Verify the regex patterns cover expected brands."""

    def test_brand_patterns_cover_major_brands(self):
        import re
        text = "hoyt mathews sitka kuiu vortex leupold kenetrek stone glacier"
        compiled = [re.compile(p, re.IGNORECASE) for p in BRAND_PATTERNS]
        found = []
        for pattern in compiled:
            found.extend(pattern.findall(text))
        assert len(found) >= 8

    def test_affiliate_patterns_detect_codes(self):
        import re
        texts = [
            "use my code SAVE20",
            "link in the description below",
            "sponsored by XYZ",
            "promo code HUNT",
            "save 15% with this coupon",
        ]
        compiled = [re.compile(p, re.IGNORECASE) for p in AFFILIATE_PATTERNS]
        for text in texts:
            assert any(p.search(text) for p in compiled), f"Failed to match: {text}"

    def test_promotional_patterns(self):
        import re
        texts = [
            "best camo on the market",
            "nothing compares to this bow",
            "hands down the best optics",
            "this is a game changer for hunting",
        ]
        compiled = [re.compile(p, re.IGNORECASE) for p in PROMOTIONAL_PATTERNS]
        for text in texts:
            assert any(p.search(text) for p in compiled), f"Failed to match: {text}"
