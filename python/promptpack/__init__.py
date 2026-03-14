"""
promptpack - Pack JSON data into token-efficient formats for LLM prompts.

Automatically converts JSON arrays to CSV (40-62% fewer tokens) while
handling nested objects, null values, and edge cases. Falls back to JSON
when CSV can't represent the data safely.

Usage:
    from promptpack import pack, unpack

    csv_text = pack(my_json_data)       # JSON → CSV (fewer tokens)
    json_data = unpack(csv_text)        # CSV → JSON (back to original)
"""

from promptpack.core import pack, unpack, pack_for_prompt, estimate_savings

__version__ = "0.1.0"
__all__ = ["pack", "unpack", "pack_for_prompt", "estimate_savings"]
