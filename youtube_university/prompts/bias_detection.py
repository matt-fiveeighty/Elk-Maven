from __future__ import annotations

"""Prompt templates for the Bias Detection Agent."""

BIAS_SYSTEM_PROMPT = """\
You are a bias detection specialist. You analyze knowledge entries extracted from \
YouTube hunting videos and detect commercial bias, sponsored content, and product \
promotion that could skew the objectivity of the advice.

Types of bias to detect:
- brand_promotion: Recommending specific brands without objective comparison
- affiliate: Language suggesting affiliate relationships or discount codes
- sponsored: Content that appears to be a sponsored segment
- product_placement: Subtle integration of product mentions into otherwise good advice
- unsubstantiated_claim: Product/gear claims without evidence

Rules for severity:
- low: Mentions a brand in passing while giving functional advice ("I use a 70lb bow" + happens to name it)
- medium: Recommends a specific brand as the go-to choice without alternatives
- high: Direct endorsement, affiliate push, or sponsored segment

Respond ONLY with valid JSON. No text outside the JSON."""


def build_bias_check_prompt(entries: list[dict]) -> str:
    """Build a prompt to check a batch of entries for bias."""
    entries_text = ""
    for e in entries:
        entries_text += (
            f"\n[Entry {e['id']}]\n"
            f"Type: {e['entry_type']}\n"
            f"Title: {e['title']}\n"
            f"Content: {e['content']}\n"
            f"Source Quote: {e.get('source_quote', 'N/A')}\n"
        )

    return f"""Analyze these knowledge entries for commercial bias:

{entries_text}

For EACH entry, determine if it contains bias. Respond with JSON:
{{
    "results": [
        {{
            "id": <entry_id>,
            "is_biased": true/false,
            "bias_type": "brand_promotion|affiliate|sponsored|product_placement|unsubstantiated_claim",
            "bias_severity": "low|medium|high",
            "brand_names": ["Brand1"],
            "bias_notes": "Brief explanation"
        }}
    ]
}}

Only include entries where is_biased is true. If none are biased, return {{"results": []}}"""
