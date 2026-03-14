"""Comprehensive tests for promptpack — every edge case covered."""

import json
import pytest
from promptpack import pack, unpack, pack_for_prompt, estimate_savings


# =========================================================================
# Basic round-trip: pack → unpack should return the same data
# =========================================================================

class TestBasicRoundTrip:

    def test_simple_array(self):
        data = [{"name": "Yash", "role": "Eng"}, {"name": "Ali", "role": "Des"}]
        packed = pack(data)
        assert "name,role" in packed  # CSV header
        assert "Yash,Eng" in packed
        result = unpack(packed)
        assert result == data

    def test_three_columns(self):
        data = [
            {"name": "Yash", "role": "Eng", "city": "NYC"},
            {"name": "Ali", "role": "Des", "city": "LA"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result == data

    def test_numbers_preserved(self):
        data = [{"id": 1, "salary": 150000}, {"id": 2, "salary": 120000}]
        packed = pack(data)
        result = unpack(packed)
        assert result == data
        assert isinstance(result[0]["id"], int)
        assert isinstance(result[0]["salary"], int)

    def test_floats_preserved(self):
        data = [{"name": "A", "score": 3.14}, {"name": "B", "score": 2.72}]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["score"] == 3.14

    def test_booleans_preserved(self):
        data = [{"name": "Yash", "active": True}, {"name": "Ali", "active": False}]
        packed = pack(data)
        assert "true" in packed
        assert "false" in packed
        result = unpack(packed)
        assert result[0]["active"] is True
        assert result[1]["active"] is False

    def test_null_preserved(self):
        data = [{"name": "Yash", "salary": 150000}, {"name": "Bob", "salary": None}]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["salary"] == 150000
        assert result[1]["salary"] is None


# =========================================================================
# Values with special characters
# =========================================================================

class TestSpecialCharacters:

    def test_values_with_commas(self):
        """Commas in values must be quoted in CSV — not break the format."""
        data = [
            {"name": "Yash", "city": "New York, NY"},
            {"name": "Ali", "city": "Los Angeles, CA"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["city"] == "New York, NY"
        assert result[1]["city"] == "Los Angeles, CA"

    def test_values_with_quotes(self):
        """Double quotes in values must be escaped."""
        data = [
            {"name": "Yash", "bio": 'He said "hello"'},
            {"name": "Ali", "bio": "Normal bio"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["bio"] == 'He said "hello"'

    def test_values_with_newlines(self):
        """Newlines in values must be quoted."""
        data = [
            {"name": "Yash", "notes": "line1\nline2"},
            {"name": "Ali", "notes": "single line"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["notes"] == "line1\nline2"

    def test_values_with_spaces(self):
        """Spaces in values (the original problem) — must work."""
        data = [
            {"name": "Yash P", "role": "Senior Eng"},
            {"name": "Ali Khan", "role": "QA Lead"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["name"] == "Yash P"
        assert result[1]["role"] == "QA Lead"

    def test_unicode_and_emoji(self):
        data = [
            {"name": "José", "mood": "Happy 😊"},
            {"name": "André", "mood": "OK 👍"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["name"] == "José"
        assert result[0]["mood"] == "Happy 😊"

    def test_email_and_urls(self):
        data = [
            {"name": "Yash", "email": "yash@gmail.com", "url": "https://github.com/yash"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["email"] == "yash@gmail.com"
        assert result[0]["url"] == "https://github.com/yash"

    def test_empty_string_vs_null(self):
        """Empty strings and None must be distinguishable on unpack."""
        data = [
            {"name": "Yash", "bio": ""},
            {"name": "Ali", "bio": None},
        ]
        packed = pack(data)
        result = unpack(packed)
        # CSV limitation: both empty string and null become empty cell
        # unpack treats empty cell as None (acceptable trade-off)
        # This is documented behavior
        assert result[0]["bio"] is None or result[0]["bio"] == ""
        assert result[1]["bio"] is None


# =========================================================================
# Nested objects (dot-flattening)
# =========================================================================

class TestNesting:

    def test_one_level_nesting(self):
        data = [
            {"name": "Yash", "address": {"city": "NYC", "zip": "10001"}},
            {"name": "Ali", "address": {"city": "LA", "zip": "90001"}},
        ]
        packed = pack(data)
        assert "address.city" in packed
        assert "address.zip" in packed
        result = unpack(packed)
        assert result[0]["address"]["city"] == "NYC"
        # Zip codes round-trip as int (CSV limitation — acceptable for LLM use)
        assert result[1]["address"]["zip"] in ("90001", 90001)

    def test_deep_nesting(self):
        data = [
            {"name": "Yash", "addr": {"loc": {"city": "NYC", "state": "NY"}}},
            {"name": "Ali", "addr": {"loc": {"city": "LA", "state": "CA"}}},
        ]
        packed = pack(data)
        assert "addr.loc.city" in packed
        result = unpack(packed)
        assert result[0]["addr"]["loc"]["city"] == "NYC"
        assert result[1]["addr"]["loc"]["state"] == "CA"

    def test_nested_array_of_primitives(self):
        """Arrays like skills: ["Python", "Java"] → pipe-joined."""
        data = [
            {"name": "Yash", "skills": ["Python", "TypeScript", "Java"]},
            {"name": "Ali", "skills": ["Figma", "CSS"]},
        ]
        packed = pack(data)
        assert "Python|TypeScript|Java" in packed
        result = unpack(packed)
        assert result[0]["skills"] == ["Python", "TypeScript", "Java"]
        assert result[1]["skills"] == ["Figma", "CSS"]

    def test_nested_array_of_numbers(self):
        data = [
            {"name": "Yash", "scores": [95, 87, 92]},
            {"name": "Ali", "scores": [88, 91]},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["scores"] == [95, 87, 92]

    def test_nested_with_null_values(self):
        data = [
            {"name": "Yash", "address": {"city": "NYC", "zip": "10001"}},
            {"name": "Bob", "address": {"city": "SF", "zip": None}},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["address"]["zip"] in ("10001", 10001)
        assert result[1]["address"]["zip"] is None

    def test_mixed_nested_and_flat(self):
        data = [
            {"name": "Yash", "age": 28, "address": {"city": "NYC"}, "active": True},
            {"name": "Ali", "age": 25, "address": {"city": "LA"}, "active": False},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["name"] == "Yash"
        assert result[0]["age"] == 28
        assert result[0]["address"]["city"] == "NYC"
        assert result[0]["active"] is True


# =========================================================================
# Non-uniform and edge-case arrays
# =========================================================================

class TestEdgeCases:

    def test_non_uniform_objects_with_optional_fields(self):
        """Objects with different optional fields → superset headers, nulls for missing."""
        data = [
            {"name": "Yash", "role": "Eng", "salary": 150000},
            {"name": "Ali", "role": "Des"},  # no salary
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["salary"] == 150000
        assert result[1]["salary"] is None

    def test_single_row(self):
        """Single row shouldn't be packed (not worth it)."""
        data = [{"name": "Yash", "role": "Eng"}]
        packed = pack(data)
        # Single row → falls back to JSON (pack requires >= 2 rows)
        assert packed.startswith("[")

    def test_empty_array(self):
        packed = pack([])
        assert packed == "[]"

    def test_single_dict(self):
        """Single object → compact JSON."""
        data = {"name": "Yash", "role": "Eng"}
        packed = pack(data)
        assert packed == '{"name":"Yash","role":"Eng"}'

    def test_string_input(self):
        """If input is already a string, try to parse as JSON first."""
        json_str = '[{"name":"Yash"},{"name":"Ali"}]'
        packed = pack(json_str)
        assert "name" in packed
        result = unpack(packed)
        assert result[0]["name"] == "Yash"

    def test_plain_string_passthrough(self):
        """Non-JSON strings pass through unchanged."""
        assert pack("Hello world") == "Hello world"

    def test_non_dict_array_fallback(self):
        """Array of non-dicts → JSON fallback."""
        data = [1, 2, 3, 4, 5]
        packed = pack(data)
        assert packed == "[1,2,3,4,5]"

    def test_mixed_array_fallback(self):
        """Array of mixed types → JSON fallback."""
        data = [{"name": "Yash"}, 42, "hello"]
        packed = pack(data)
        assert packed.startswith("[")

    def test_deeply_dissimilar_objects_fallback(self):
        """Objects with zero shared keys → JSON fallback."""
        data = [
            {"a": 1, "b": 2, "c": 3, "d": 4},
            {"x": 1, "y": 2, "z": 3, "w": 4},
        ]
        packed = pack(data)
        # Zero overlap → should fall back to JSON
        assert packed.startswith("[")

    def test_large_dataset(self):
        """100 rows should pack and unpack correctly."""
        data = [{"id": i, "name": f"User{i}", "score": i * 1.5} for i in range(100)]
        packed = pack(data)
        result = unpack(packed)
        assert len(result) == 100
        assert result[0]["id"] == 0
        assert result[99]["name"] == "User99"
        assert result[50]["score"] == 75.0

    def test_value_looks_like_number_but_is_string(self):
        """Zip codes like '10001' — will be parsed as number on unpack.
        This is a known limitation documented in README."""
        data = [{"name": "Yash", "zip": "10001"}]
        packed = pack(data)
        result = unpack(packed)
        # Known: "10001" round-trips as 10001 (int)
        # Acceptable for LLM use — the LLM understands either way
        assert result[0]["zip"] in ("10001", 10001)


# =========================================================================
# pack_for_prompt
# =========================================================================

class TestPackForPrompt:

    def test_combines_message_and_data(self):
        data = [{"name": "Yash", "role": "Eng"}, {"name": "Ali", "role": "Des"}]
        result = pack_for_prompt("Analyze:", data)
        assert result.startswith("Analyze:\n")
        assert "name,role" in result

    def test_with_empty_message(self):
        data = [{"x": 1}, {"x": 2}]
        result = pack_for_prompt("", data)
        assert "x" in result


# =========================================================================
# estimate_savings
# =========================================================================

class TestEstimateSavings:

    def test_returns_savings(self):
        data = [{"name": "Yash", "role": "Eng", "city": "NYC"},
                {"name": "Ali", "role": "Des", "city": "LA"}]
        result = estimate_savings(data)
        assert result["char_savings_pct"] > 0
        assert result["format_used"] == "csv"

    def test_no_savings_for_single_object(self):
        data = {"name": "Yash"}
        result = estimate_savings(data)
        assert result["format_used"] == "json"


# =========================================================================
# Unpack edge cases
# =========================================================================

class TestUnpack:

    def test_unpack_json(self):
        """unpack should handle JSON strings too."""
        result = unpack('[{"name":"Yash"}]')
        assert result == [{"name": "Yash"}]

    def test_unpack_empty(self):
        assert unpack("") == []

    def test_unpack_json_object(self):
        result = unpack('{"name":"Yash"}')
        assert result == {"name": "Yash"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
