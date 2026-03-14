"""Core pack/unpack logic for tokenpack."""

import csv
import io
import json
from typing import Any


# ---------------------------------------------------------------------------
# Marker type for pipe-joined arrays
# ---------------------------------------------------------------------------


class _PipeJoined(str):
    """String subclass marking a value that came from pipe-joining an array."""
    pass


# Null sentinel for typed mode (distinguishes null from empty string)
_NULL = "\\N"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pack(data: Any, *, typed: bool = False) -> str:
    """Convert JSON-compatible data to the most token-efficient text format.

    Args:
        data: JSON-compatible Python data (list/dict/str).
        typed: If True, include a ``#types`` row and ``\\N`` null markers
               for safe round-tripping. Default False outputs pure CSV.

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
        return _to_csv(data, typed=typed)

    # Not worth packing — return compact JSON
    return json.dumps(data, separators=(",", ":"))


def unpack(text: str) -> Any:
    """Convert packed text back to JSON-compatible Python objects.

    Detects whether *text* is CSV (produced by ``pack``) or plain JSON
    and returns the appropriate Python structure.  Automatically detects
    the ``#types`` row if present and uses it for safe parsing.
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
    """Return a dict with token-count estimates.

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
    threshold = max(len(all_keys) * 0.3, 1)
    shared_keys = set.intersection(*(set(item.keys()) for item in data))
    if len(shared_keys) == 0:
        return False
    for item in data:
        if len(item) < threshold:
            return False

    return True


# ---------------------------------------------------------------------------
# Internal: key escaping for dot-notation
# ---------------------------------------------------------------------------


def _escape_key(key: str) -> str:
    """Escape backslashes and dots in a key name so dots aren't confused with nesting."""
    return key.replace("\\", "\\\\").replace(".", "\\.")


def _split_dotted_key(key: str) -> list[str]:
    """Split a key on unescaped dots, handling escaped dots and backslashes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(key):
        if key[i] == '\\' and i + 1 < len(key):
            current.append(key[i + 1])
            i += 2
        elif key[i] == '.':
            parts.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(key[i])
            i += 1
    parts.append(''.join(current))
    return parts


# ---------------------------------------------------------------------------
# Internal: pipe escaping for array values
# ---------------------------------------------------------------------------


def _escape_pipe(s: str) -> str:
    """Escape backslashes and pipes in an array element."""
    return s.replace("\\", "\\\\").replace("|", "\\|")


def _split_pipe_joined(raw: str) -> list[str]:
    """Split on unescaped pipe characters, handling escaped pipes and backslashes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == '\\' and i + 1 < len(raw):
            current.append(raw[i + 1])
            i += 2
        elif raw[i] == '|':
            parts.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(raw[i])
            i += 1
    parts.append(''.join(current))
    return parts


# ---------------------------------------------------------------------------
# Internal: JSON → CSV conversion
# ---------------------------------------------------------------------------


def _flatten_value(value: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict using dot notation.

    Nested dicts  → ``address.city``
    Primitive lists → pipe-joined string ``Python|TypeScript``
    Nested object lists → JSON string (safe fallback)
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            escaped_k = _escape_key(k)
            full_key = f"{prefix}.{escaped_k}" if prefix else escaped_k
            out.update(_flatten_value(v, full_key))
        return out

    if isinstance(value, list):
        # Array of primitives → pipe-join with escaping
        if all(_is_primitive(v) for v in value):
            joined = "|".join(_escape_pipe(_prim_to_str(v)) for v in value)
            return {prefix: _PipeJoined(joined)}
        # Array of objects → JSON fallback for this cell
        return {prefix: json.dumps(value, separators=(",", ":"))}

    return {prefix: value}


def _flatten_row(row: dict) -> dict[str, Any]:
    """Flatten one row, handling nested dicts and arrays."""
    flat: dict[str, Any] = {}
    for key, value in row.items():
        escaped_key = _escape_key(key)
        flat.update(_flatten_value(value, escaped_key))
    return flat


def _detect_column_type(flat_rows: list[dict], header: str) -> str:
    """Detect the type code for a column based on Python types of values.

    Type codes: s=string, n=number, b=bool, a=pipe-array, j=json-blob, x=mixed
    """
    vals = [row[header] for row in flat_rows if header in row and row[header] is not None]
    if not vals:
        return "x"

    # Check for pipe-joined arrays first
    if any(isinstance(v, _PipeJoined) for v in vals):
        return "a"

    types_seen: set[str] = set()
    for v in vals:
        if isinstance(v, bool):
            types_seen.add("b")
        elif isinstance(v, (int, float)):
            types_seen.add("n")
        elif isinstance(v, str):
            # Check if this is a JSON blob
            if v and v[0] in ("{", "["):
                try:
                    json.loads(v)
                    types_seen.add("j")
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            types_seen.add("s")
        else:
            types_seen.add("x")

    if len(types_seen) == 1:
        return types_seen.pop()

    # Mixed types — if strings are present, use string (safest)
    if "s" in types_seen:
        return "s"

    return "x"


def _to_csv(data: list[dict], *, typed: bool = False) -> str:
    """Convert a list of dicts to CSV with smart flattening.

    Args:
        typed: If True, include a #types row and use \\N for null values.
    """
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

    if typed:
        # Detect column types and write type hints row
        col_types = [_detect_column_type(flat_rows, h) for h in headers]
        buf.write("#" + ",".join(col_types) + "\n")

    for row in flat_rows:
        writer.writerow([_format_cell(row.get(k), typed=typed) for k in headers])

    return buf.getvalue().rstrip("\n")


def _format_cell(value: Any, *, typed: bool = False) -> str:
    """Convert a single cell value to its CSV string representation."""
    if value is None:
        return _NULL if typed else ""
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

    # Check for type hints row
    col_types: list[str] | None = None
    typed_mode = False
    first_data_row = None
    try:
        maybe_types = next(reader)
        if maybe_types and maybe_types[0].startswith("#"):
            # Type hints: csv.reader splits "#s,n,a,b" into ["#s", "n", "a", "b"]
            col_types = [maybe_types[0][1:]] + list(maybe_types[1:])
            typed_mode = True
        else:
            first_data_row = maybe_types
    except StopIteration:
        return []

    rows: list[dict] = []

    def _process_row(csv_row: list[str]) -> None:
        if not csv_row or all(c == "" for c in csv_row):
            return
        flat: dict[str, Any] = {}
        for i, header in enumerate(headers):
            raw = csv_row[i] if i < len(csv_row) else ""
            t = col_types[i] if col_types and i < len(col_types) else None
            flat[header] = _parse_cell(raw, t, typed_mode=typed_mode)
        nested = _unflatten(flat)
        rows.append(nested)

    if first_data_row is not None:
        _process_row(first_data_row)

    for csv_row in reader:
        _process_row(csv_row)

    return rows


def _parse_cell(raw: str, type_hint: str | None = None, *,
                typed_mode: bool = False) -> Any:
    """Parse a raw CSV cell back to a Python value."""
    # Null sentinel (typed mode)
    if raw == _NULL and typed_mode:
        return None

    # Empty cell
    if raw == "":
        if typed_mode:
            return ""  # In typed mode, empty = empty string, \N = null
        return None     # In untyped mode, empty = null (best guess)

    # If we have a type hint, use it for safe parsing
    if type_hint == "s":
        return raw  # Always return as string — never auto-parse
    if type_hint == "b":
        return raw == "true"
    if type_hint == "n":
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            return raw
    if type_hint == "a":
        parts = _split_pipe_joined(raw)
        return [_parse_array_element(p) for p in parts]
    if type_hint == "j":
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    # No type hint — auto-detect (backward compat with plain CSV)
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
    """Convert ``{"a.b.c": 1}`` back to ``{"a": {"b": {"c": 1}}}``.

    Handles escaped dots in key names (``a\\.b`` stays as key ``a.b``).
    """
    result: dict = {}
    for key, value in flat.items():
        parts = _split_dotted_key(key)
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


def _parse_array_element(raw: str) -> Any:
    """Parse a single element from a pipe-joined array (no pipe detection)."""
    if raw == "":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw


def _is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _prim_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
