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
# pack() outputs pure standard CSV (no #types row)
# =========================================================================

class TestPureCSV:

    def test_no_types_row_by_default(self):
        """Default pack() should NOT include a #types row."""
        data = [{"name": "Yash", "age": 28}, {"name": "Ali", "age": 25}]
        packed = pack(data)
        lines = packed.split("\n")
        assert lines[0] == "name,age"
        assert lines[1] == "Yash,28"  # Data immediately after header, no # row
        assert len(lines) == 3

    def test_typed_mode_includes_types_row(self):
        """pack(typed=True) should include #types row."""
        data = [{"name": "Yash", "age": 28}, {"name": "Ali", "age": 25}]
        packed = pack(data, typed=True)
        lines = packed.split("\n")
        assert lines[0] == "name,age"
        assert lines[1].startswith("#")  # Types row
        assert lines[2] == "Yash,28"


# =========================================================================
# Values with special characters
# =========================================================================

class TestSpecialCharacters:

    def test_values_with_commas(self):
        data = [
            {"name": "Yash", "city": "New York, NY"},
            {"name": "Ali", "city": "Los Angeles, CA"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["city"] == "New York, NY"
        assert result[1]["city"] == "Los Angeles, CA"

    def test_values_with_quotes(self):
        data = [
            {"name": "Yash", "bio": 'He said "hello"'},
            {"name": "Ali", "bio": "Normal bio"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["bio"] == 'He said "hello"'

    def test_values_with_newlines(self):
        data = [
            {"name": "Yash", "notes": "line1\nline2"},
            {"name": "Ali", "notes": "single line"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["notes"] == "line1\nline2"

    def test_values_with_spaces(self):
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
        # Without types, zip "10001" round-trips as int (known auto-detect behavior)
        assert result[0]["address"]["zip"] in ("10001", 10001)

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
# Edge cases
# =========================================================================

class TestEdgeCases:

    def test_non_uniform_objects_with_optional_fields(self):
        data = [
            {"name": "Yash", "role": "Eng", "salary": 150000},
            {"name": "Ali", "role": "Des"},
        ]
        packed = pack(data)
        result = unpack(packed)
        assert result[0]["salary"] == 150000
        assert result[1]["salary"] is None

    def test_single_row(self):
        data = [{"name": "Yash", "role": "Eng"}]
        packed = pack(data)
        assert packed.startswith("[")

    def test_empty_array(self):
        assert pack([]) == "[]"

    def test_single_dict(self):
        data = {"name": "Yash", "role": "Eng"}
        packed = pack(data)
        assert packed == '{"name":"Yash","role":"Eng"}'

    def test_string_input(self):
        json_str = '[{"name":"Yash"},{"name":"Ali"}]'
        packed = pack(json_str)
        assert "name" in packed
        result = unpack(packed)
        assert result[0]["name"] == "Yash"

    def test_plain_string_passthrough(self):
        assert pack("Hello world") == "Hello world"

    def test_non_dict_array_fallback(self):
        data = [1, 2, 3, 4, 5]
        assert pack(data) == "[1,2,3,4,5]"

    def test_mixed_array_fallback(self):
        data = [{"name": "Yash"}, 42, "hello"]
        assert pack(data).startswith("[")

    def test_deeply_dissimilar_objects_fallback(self):
        data = [
            {"a": 1, "b": 2, "c": 3, "d": 4},
            {"x": 1, "y": 2, "z": 3, "w": 4},
        ]
        assert pack(data).startswith("[")

    def test_large_dataset(self):
        data = [{"id": i, "name": f"User{i}", "score": i * 1.5} for i in range(100)]
        packed = pack(data)
        result = unpack(packed)
        assert len(result) == 100
        assert result[0]["id"] == 0
        assert result[99]["name"] == "User99"
        assert result[50]["score"] == 75.0


# =========================================================================
# Typed mode: safe round-tripping with #types and \N nulls
# =========================================================================

class TestTypedMode:
    """pack(typed=True) enables safe round-tripping."""

    def test_string_true_preserved(self):
        """String 'true' must NOT become boolean in typed mode."""
        data = [{"name": "Yash", "status": "true"}, {"name": "Ali", "status": "active"}]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["status"] == "true"
        assert isinstance(result[0]["status"], str)

    def test_numeric_string_preserved(self):
        """Phone numbers stay as strings in typed mode."""
        data = [{"name": "Yash", "phone": "5551234567"}, {"name": "Ali", "phone": "5559876543"}]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["phone"] == "5551234567"
        assert isinstance(result[0]["phone"], str)

    def test_zip_code_preserved(self):
        data = [
            {"name": "Yash", "address": {"city": "NYC", "zip": "10001"}},
            {"name": "Ali", "address": {"city": "LA", "zip": "90001"}},
        ]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["address"]["zip"] == "10001"
        assert isinstance(result[0]["address"]["zip"], str)

    def test_pipe_in_string_preserved(self):
        """String containing | must NOT become array in typed mode."""
        data = [{"name": "Yash", "note": "yes|no"}, {"name": "Ali", "note": "maybe"}]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["note"] == "yes|no"
        assert isinstance(result[0]["note"], str)

    def test_pipe_in_array_element_preserved(self):
        """Array elements containing | must round-trip in typed mode."""
        data = [
            {"name": "Yash", "tags": ["yes|no", "maybe"]},
            {"name": "Ali", "tags": ["ok"]},
        ]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["tags"] == ["yes|no", "maybe"]

    def test_dot_in_key_name_preserved(self):
        """Key 'config.name' must NOT become nested in typed mode."""
        data = [
            {"version": "1.0", "config.name": "prod"},
            {"version": "2.0", "config.name": "staging"},
        ]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert "config.name" in result[0]
        assert result[0]["config.name"] == "prod"

    def test_null_vs_empty_string_distinguished(self):
        """Typed mode can distinguish null from empty string."""
        data = [
            {"name": "Yash", "bio": ""},
            {"name": "Ali", "bio": None},
        ]
        packed = pack(data, typed=True)
        assert "\\N" in packed  # Null sentinel
        result = unpack(packed)
        assert result[0]["bio"] == ""   # Empty string preserved
        assert result[1]["bio"] is None  # Null preserved

    def test_backslash_in_values(self):
        data = [
            {"name": "Yash", "path": "C:\\Users\\yash"},
            {"name": "Ali", "path": "C:\\Users\\ali"},
        ]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["path"] == "C:\\Users\\yash"

    def test_mixed_nesting_and_dot_keys(self):
        data = [
            {"name": "Yash", "address": {"city": "NYC"}, "meta.version": "1.0"},
            {"name": "Ali", "address": {"city": "LA"}, "meta.version": "2.0"},
        ]
        packed = pack(data, typed=True)
        result = unpack(packed)
        assert result[0]["address"]["city"] == "NYC"
        assert result[0]["meta.version"] == "1.0"


# =========================================================================
# Untyped mode: auto-detect has known limitations (documented)
# =========================================================================

class TestUntypedLimitations:
    """These are KNOWN limitations of default (untyped) mode, documented in README."""

    def test_numeric_string_becomes_number(self):
        """Without types, '10001' unpacks as int. Use typed=True for strings."""
        data = [{"name": "Yash", "zip": "10001"}, {"name": "Ali", "zip": "90210"}]
        packed = pack(data)  # default, no types
        result = unpack(packed)
        # Known: "10001" → 10001 (auto-detect guesses number)
        assert result[0]["zip"] in ("10001", 10001)

    def test_empty_string_becomes_null(self):
        """Without types, empty string and null are indistinguishable."""
        data = [{"name": "Yash", "bio": ""}, {"name": "Ali", "bio": None}]
        packed = pack(data)
        result = unpack(packed)
        # Both become None in untyped mode
        assert result[0]["bio"] is None
        assert result[1]["bio"] is None


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
        result = unpack('[{"name":"Yash"}]')
        assert result == [{"name": "Yash"}]

    def test_unpack_empty(self):
        assert unpack("") == []

    def test_unpack_json_object(self):
        result = unpack('{"name":"Yash"}')
        assert result == {"name": "Yash"}

    def test_unpack_csv_without_type_hints(self):
        """Plain CSV (no #types) uses auto-detect."""
        csv_text = "name,role\nYash,Eng\nAli,Des"
        result = unpack(csv_text)
        assert result[0]["name"] == "Yash"
        assert result[1]["role"] == "Des"

    def test_unpack_csv_with_type_hints(self):
        """CSV with #types row uses safe parsing."""
        csv_text = "name,zip\n#s,s\nYash,10001\nAli,90210"
        result = unpack(csv_text)
        assert result[0]["zip"] == "10001"  # String, not int
        assert isinstance(result[0]["zip"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
