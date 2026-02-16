from __future__ import annotations

"""Prompt templates for the Optimization Agent."""

OPTIMIZER_SYSTEM_PROMPT = """\
You are a knowledge base optimization specialist. You analyze knowledge entries \
and help improve data quality by identifying duplicates, suggesting better \
categorization, and detecting low-quality entries.

Respond ONLY with valid JSON as specified in each prompt. No text outside the JSON."""


def build_categorize_prompt(entries: list[dict], categories: list[str]) -> str:
    """Build a prompt to suggest categories for uncategorized entries."""
    entries_text = ""
    for e in entries:
        entries_text += (
            f"\n[Entry {e['id']}] ({e['entry_type']}) {e['title']}\n"
            f"  Content: {e['content'][:200]}\n"
        )

    cats_text = ", ".join(categories)

    return f"""Assign categories to these knowledge entries.

Available categories: {cats_text}

Entries:
{entries_text}

For each entry, suggest 1-3 categories. Respond with JSON:
{{
    "assignments": [
        {{"id": <entry_id>, "categories": ["category1", "category2"]}}
    ]
}}"""


def build_tag_prompt(entries: list[dict]) -> str:
    """Build a prompt to suggest tags for untagged entries."""
    entries_text = ""
    for e in entries:
        entries_text += (
            f"\n[Entry {e['id']}] ({e['entry_type']}) {e['title']}\n"
            f"  Content: {e['content'][:200]}\n"
        )

    return f"""Suggest 2-5 descriptive tags for each knowledge entry.
Tags should be lowercase, specific, and useful for search.

Entries:
{entries_text}

Respond with JSON:
{{
    "assignments": [
        {{"id": <entry_id>, "tags": ["tag1", "tag2", "tag3"]}}
    ]
}}"""


def build_duplicate_check_prompt(pairs: list[tuple]) -> str:
    """Build a prompt to check if entry pairs are duplicates."""
    pairs_text = ""
    for i, (a, b) in enumerate(pairs):
        pairs_text += (
            f"\n--- Pair {i + 1} ---\n"
            f"Entry A [{a['id']}]: {a['title']}\n"
            f"  {a['content'][:200]}\n"
            f"Entry B [{b['id']}]: {b['title']}\n"
            f"  {b['content'][:200]}\n"
        )

    return f"""Are these entry pairs expressing the same insight/knowledge?

{pairs_text}

For each pair, determine if they are duplicates (same core insight, possibly different wording).
Respond with JSON:
{{
    "pairs": [
        {{
            "pair_index": 1,
            "is_duplicate": true/false,
            "keep_id": <id_of_better_entry>,
            "remove_id": <id_of_weaker_entry>,
            "reason": "Brief explanation"
        }}
    ]
}}"""
