from __future__ import annotations

"""Agent 6: Bias Detector — Scans knowledge entries for commercial bias,
brand promotion, affiliate language, and sponsored content. Flags entries
in the database without modifying originals."""

import json
import re
import logging

import requests

from ..database.repository import Repository
from ..prompts.bias_detection import BIAS_SYSTEM_PROMPT, build_bias_check_prompt

logger = logging.getLogger(__name__)

# Known brand names in the elk hunting space
BRAND_PATTERNS = [
    # Bow manufacturers
    r'\b(hoyt|mathews|bowtech|bear archery|pse|elite archery|prime bows)\b',
    # Clothing/camo
    r'\b(sitka|kuiu|first lite|kryptek|kings camo|under armour|realtree|mossy oak)\b',
    # Optics
    r'\b(vortex|leupold|swarovski|zeiss|maven|sig sauer|athlon|nikon)\b',
    # Packs
    r'\b(stone glacier|mystery ranch|kifaru|exo mountain|badlands)\b',
    # Boots
    r'\b(crispi|kenetrek|schnee|danner|salomon|lowa|meindl)\b',
    # Calls / elk specific
    r'\b(phelps|rocky mountain hunting|primos|carlton|bugling bull)\b',
    # Broadheads / arrows
    r'\b(rage|muzzy|iron will|sevr|gold tip|easton|black eagle)\b',
    # Rifles / calibers (brand focus)
    r'\b(weatherby|remington|winchester|browning|tikka|christensen)\b',
    # General outdoor
    r'\b(yeti|garmin|onx|gohunt|gaia|cabelas|bass pro|sportsmans warehouse)\b',
]

AFFILIATE_PATTERNS = [
    r'use (?:my |the )?code\b',
    r'link in (?:the )?description',
    r'affiliate',
    r'discount code',
    r'promo code',
    r'sponsored by',
    r'check (?:them )?out at',
    r'special (?:offer|deal)',
    r'percent off',
    r'\bsave \d+%',
    r'coupon',
]

PROMOTIONAL_PATTERNS = [
    r'best .{1,30} on the market',
    r'nothing compares to',
    r'only .{1,20} I(?:\'ll| will) ever use',
    r'hands down the best',
    r'game ?changer',
    r'can\'?t hunt without',
    r'(?:my|the) go[- ]?to',
    r'I(?:\'ve| have) tried (?:them )?all.{0,30}(?:best|winner)',
]


class BiasDetectorAgent:
    """Scans knowledge entries for commercial bias and flags them."""

    def __init__(self, repo: Repository, ollama_url: str = "http://localhost:11434",
                 model: str = "llama3.2"):
        self.repo = repo
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._compiled_brands = [re.compile(p, re.IGNORECASE) for p in BRAND_PATTERNS]
        self._compiled_affiliate = [re.compile(p, re.IGNORECASE) for p in AFFILIATE_PATTERNS]
        self._compiled_promo = [re.compile(p, re.IGNORECASE) for p in PROMOTIONAL_PATTERNS]

    def scan_all(self, batch_size: int = 15):
        """Scan all unflagged knowledge entries for bias. Yields progress events."""
        entries = self.repo.get_unflagged_entries()
        total = len(entries)

        if total == 0:
            yield {"event": "complete", "total": 0, "flagged": 0}
            return

        yield {"event": "start", "total": total}
        flagged_count = 0

        for i in range(0, total, batch_size):
            batch = entries[i:i + batch_size]

            # Pass 1: fast heuristic pre-filter
            suspicious = []
            clean = []
            for entry in batch:
                heuristic = self._heuristic_check(entry)
                if heuristic:
                    suspicious.append((entry, heuristic))
                else:
                    clean.append(entry)

            # Pass 2: LLM analysis for suspicious entries
            if suspicious:
                try:
                    flags = self._llm_analyze([s[0] for s in suspicious])
                    for flag in flags:
                        self.repo.insert_bias_flag(flag)
                        flagged_count += 1
                except Exception as e:
                    logger.error(f"LLM bias analysis failed for batch: {e}")
                    # Fall back to heuristic-only flags for this batch
                    for entry, heuristic in suspicious:
                        flag = self._heuristic_to_flag(entry, heuristic)
                        self.repo.insert_bias_flag(flag)
                        flagged_count += 1

            processed = min(i + batch_size, total)
            yield {
                "event": "progress",
                "processed": processed,
                "total": total,
                "flagged": flagged_count,
                "batch_suspicious": len(suspicious),
            }

        yield {"event": "complete", "total": total, "flagged": flagged_count}

    def _heuristic_check(self, entry: dict) -> dict | None:
        """Fast regex-based pre-filter. Returns findings dict or None."""
        text = f"{entry['title']} {entry['content']} {entry.get('source_quote', '')}"

        brands_found = []
        for pattern in self._compiled_brands:
            matches = pattern.findall(text)
            brands_found.extend(matches)

        has_affiliate = any(p.search(text) for p in self._compiled_affiliate)
        has_promo = any(p.search(text) for p in self._compiled_promo)

        if brands_found or has_affiliate or has_promo:
            return {
                "brands": list(set(b.strip().title() for b in brands_found)),
                "has_affiliate": has_affiliate,
                "has_promo": has_promo,
            }
        return None

    def _heuristic_to_flag(self, entry: dict, heuristic: dict) -> dict:
        """Convert heuristic findings to a bias flag dict (fallback when LLM fails)."""
        if heuristic["has_affiliate"]:
            bias_type = "affiliate"
            severity = "medium"
            notes = "Detected affiliate/promotional language"
        elif heuristic["has_promo"]:
            bias_type = "unsubstantiated_claim"
            severity = "medium"
            notes = "Detected promotional claims"
        elif heuristic["brands"]:
            bias_type = "brand_promotion"
            severity = "low"
            notes = f"Mentions brands: {', '.join(heuristic['brands'])}"
        else:
            bias_type = "brand_promotion"
            severity = "low"
            notes = "Possible commercial content"

        return {
            "knowledge_id": entry["id"],
            "bias_type": bias_type,
            "bias_severity": severity,
            "brand_names": heuristic.get("brands", []),
            "bias_notes": notes,
            "detected_by": "heuristic_fallback",
        }

    def _llm_analyze(self, entries: list[dict]) -> list[dict]:
        """Send suspicious entries to Ollama for nuanced bias analysis."""
        prompt = build_bias_check_prompt(entries)

        resp = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": BIAS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": 2048},
            },
            timeout=300,
        )
        resp.raise_for_status()

        content = resp.json().get("message", {}).get("content", "{}")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse bias LLM response as JSON")
            return []

        flags = []
        for result in data.get("results", []):
            if not result.get("is_biased"):
                continue

            # Validate bias_type
            valid_types = {"brand_promotion", "affiliate", "sponsored",
                           "product_placement", "unsubstantiated_claim"}
            bias_type = result.get("bias_type", "brand_promotion")
            if bias_type not in valid_types:
                bias_type = "brand_promotion"

            valid_severities = {"low", "medium", "high"}
            severity = result.get("bias_severity", "medium")
            if severity not in valid_severities:
                severity = "medium"

            flags.append({
                "knowledge_id": result["id"],
                "bias_type": bias_type,
                "bias_severity": severity,
                "brand_names": result.get("brand_names", []),
                "bias_notes": result.get("bias_notes", "Flagged by LLM analysis"),
                "detected_by": "bias_agent",
            })

        return flags
