"""Core pack/unpack logic for promptpack."""

import csv
import io
import json
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pack(data: Any) -> str:
    """Convert JSON-compatible data to the most token-efficient text format.

    - Array of similar objects → CSV with dot-flattened headers
    - Everything else → compact JSON (not worth converting)

    Returns a string ready to paste into an LLM prompt.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data

    if isinstance(data, list) and len(data) >= 2 and _is_packable_array(data):
        return _to_csv(data)

    # Not worth packing — return compact JSON
    return json.dumps(data, separators=(",", ":"))


def unpack(text: str) -> Any:
    """Convert packed text back to JSON-compatible Python objects.

    Detects whether *text* is CSV (produced by ``pack``) or plain JSON
    and returns the appropriate Python structure.
    """
    text = text.strip()
    if not text:
        return []

    # If it starts with [ or { it's JSON
    if text[0] in ("{", "["):
        return json.loads(text)

    # Otherwise treat as CSV
    return _from_csv(text)


def pack_for_prompt(message: str, data: Any) -> str:
    """Convenience helper: combine a user message with packed data.

    Example::

        prompt = pack_for_prompt("Analyze these employees:", employees)
    """
    packed = pack(data)
    return f"{message}\n{packed}"


def estimate_savings(data: Any) -> dict:
    """Return a dict with token-count estimates (requires tiktoken).

    Keys: json_chars, packed_chars, char_savings_pct, format_used
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return {"json_chars": len(data), "packed_chars": len(data),
                    "char_savings_pct": 0.0, "format_used": "passthrough"}

    json_text = json.dumps(data, separators=(",", ":"))
    packed_text = pack(data)
    json_len = len(json_text)
    packed_len = len(packed_text)
    savings = (1 - packed_len / json_len) * 100 if json_len else 0

    return {
        "json_chars": json_len,
        "packed_chars": packed_len,
        "char_savings_pct": round(savings, 1),
        "format_used": "csv" if packed_text != json_text else "json",
    }


# ---------------------------------------------------------------------------
# Internal: shape detection
# ---------------------------------------------------------------------------


def _is_packable_array(data: list) -> bool:
    """Return True if *data* is a list of dicts that share enough keys."""
    if not data:
        return False
    if not all(isinstance(item, dict) for item in data):
        return False

    # Collect all keys across all rows
    all_keys = set()
    for item in data:
        all_keys.update(item.keys())

    if not all_keys:
        return False

    # Check key overlap: rows must share at least 30 % of keys with each other
    # and at least 30% of the superset must be covered per row
    threshold = max(len(all_keys) * 0.3, 1)
    shared_keys = set.intersection(*(set(item.keys()) for item in data))
    if len(shared_keys) == 0:
        return False
    for item in data:
        if len(item) < threshold:
            return False

    return True


# ---------------------------------------------------------------------------
# Internal: JSON → CSV conversion
# ---------------------------------------------------------------------------

# Sentinel used inside pipe-joined arrays so a literal "|" in a value
# survives the round-trip.
_PIPE_ESCAPE = "\\|"


def _flatten_value(value: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict using dot notation.

    Nested dicts  → ``address.city``
    Primitive lists → pipe-joined string ``Python|TypeScript``
    Nested object lists → JSON string (safe fallback)
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            out.update(_flatten_value(v, full_key))
        return out

    if isinstance(value, list):
        # Array of primitives → pipe-join
        if all(_is_primitive(v) for v in value):
            joined = "|".join(_prim_to_str(v) for v in value)
            return {prefix: joined}
        # Array of objects → JSON fallback for this cell
        return {prefix: json.dumps(value, separators=(",", ":"))}

    return {prefix: value}


def _flatten_row(row: dict) -> dict[str, Any]:
    """Flatten one row, handling nested dicts and arrays."""
    flat: dict[str, Any] = {}
    for key, value in row.items():
        flat.update(_flatten_value(value, key))
    return flat


def _to_csv(data: list[dict]) -> str:
    """Convert a list of dicts to CSV with smart flattening."""
    # Flatten all rows
    flat_rows = [_flatten_row(row) for row in data]

    # Collect ordered superset of keys (preserving first-seen order)
    seen: dict[str, None] = {}
    for row in flat_rows:
        for k in row:
            if k not in seen:
                seen[k] = None
    headers = list(seen)

    # Write CSV
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in flat_rows:
        writer.writerow([_format_cell(row.get(k)) for k in headers])

    return buf.getvalue().rstrip("\n")


def _format_cell(value: Any) -> str:
    """Convert a single cell value to its CSV string representation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    # Anything else (shouldn't happen after flattening) → JSON
    return json.dumps(value, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Internal: CSV → JSON conversion (unpack)
# ---------------------------------------------------------------------------


def _from_csv(text: str) -> list[dict]:
    """Parse CSV text back into a list of dicts, reversing the pack."""
    buf = io.StringIO(text)
    reader = csv.reader(buf)

    try:
        headers = next(reader)
    except StopIteration:
        return []

    rows: list[dict] = []
    for csv_row in reader:
        if not csv_row or all(c == "" for c in csv_row):
            continue
        flat: dict[str, Any] = {}
        for i, header in enumerate(headers):
            raw = csv_row[i] if i < len(csv_row) else ""
            flat[header] = _parse_cell(raw, header)

        # Unflatten dot-notation keys back into nested dicts
        nested = _unflatten(flat)
        rows.append(nested)

    return rows


def _parse_cell(raw: str, header: str = "") -> Any:
    """Parse a raw CSV cell back to a Python value."""
    # Empty → None
    if raw == "":
        return None

    # Booleans
    if raw == "true":
        return True
    if raw == "false":
        return False

    # Numbers
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass

    # Pipe-separated array (heuristic: contains | but is not JSON)
    if "|" in raw and not raw.startswith("["):
        parts = raw.split("|")
        return [_parse_cell(p) for p in parts]

    # JSON array/object embedded in cell
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    # Plain string
    return raw


def _unflatten(flat: dict[str, Any]) -> dict:
    """Convert ``{"a.b.c": 1}`` back to ``{"a": {"b": {"c": 1}}}``."""
    result: dict = {}
    for key, value in flat.items():
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# Internal: helpers
# ---------------------------------------------------------------------------


def _is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _prim_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
