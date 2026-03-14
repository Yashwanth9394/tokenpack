use serde_json::{Map, Value};
use std::collections::{BTreeSet, HashMap};
use std::io::Cursor;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// If `data` is a packable array (>=2 uniform objects), return CSV.
/// Otherwise return compact JSON.
pub fn pack(data: &Value) -> String {
    if is_packable_array(data) {
        to_csv(data)
    } else {
        serde_json::to_string(data).unwrap_or_default()
    }
}

/// Parse `text` back to a `Value`. Tries CSV first, falls back to JSON.
pub fn unpack(text: &str) -> Value {
    let trimmed = text.trim();
    // If it looks like JSON, parse as JSON directly.
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        if let Ok(v) = serde_json::from_str(trimmed) {
            return v;
        }
    }
    // Otherwise try CSV.
    from_csv(trimmed)
}

/// Convenience: combine a human message with packed data.
pub fn pack_for_prompt(message: &str, data: &Value) -> String {
    let packed = pack(data);
    format!("{}\n\n{}", message, packed)
}

// ---------------------------------------------------------------------------
// Internal: packability check
// ---------------------------------------------------------------------------

fn is_packable_array(data: &Value) -> bool {
    let arr = match data.as_array() {
        Some(a) => a,
        None => return false,
    };
    if arr.len() < 2 {
        return false;
    }
    // Every item must be an object.
    if !arr.iter().all(|v| v.is_object()) {
        return false;
    }

    // Collect all keys (superset).
    let superset: BTreeSet<String> = arr
        .iter()
        .flat_map(|v| v.as_object().unwrap().keys().cloned())
        .collect();

    if superset.is_empty() {
        return false;
    }

    // Shared-key intersection must be > 0.
    let mut intersection: BTreeSet<String> = superset.clone();
    for item in arr {
        let keys: BTreeSet<String> = item.as_object().unwrap().keys().cloned().collect();
        intersection = intersection.intersection(&keys).cloned().collect();
    }
    if intersection.is_empty() {
        return false;
    }

    let superset_len = superset.len() as f64;
    // Each row must have >= 30% of the superset keys.
    for item in arr {
        let row_keys = item.as_object().unwrap().len() as f64;
        if row_keys / superset_len < 0.3 {
            return false;
        }
    }

    true
}

// ---------------------------------------------------------------------------
// Internal: flatten / unflatten
// ---------------------------------------------------------------------------

/// Flatten a `Value::Object` using dot notation. Primitive arrays are
/// pipe-joined; non-primitive arrays and nested objects in arrays are
/// serialised as JSON strings.
fn flatten_row(value: &Value) -> Vec<(String, Value)> {
    let mut out: Vec<(String, Value)> = Vec::new();
    if let Value::Object(map) = value {
        flatten_into(&mut out, String::new(), map);
    }
    out
}

fn flatten_into(out: &mut Vec<(String, Value)>, prefix: String, map: &Map<String, Value>) {
    for (k, v) in map {
        let key = if prefix.is_empty() {
            k.clone()
        } else {
            format!("{}.{}", prefix, k)
        };
        match v {
            Value::Object(inner) => {
                flatten_into(out, key, inner);
            }
            Value::Array(arr) => {
                if arr.iter().all(|el| is_primitive(el)) {
                    // Pipe-join primitive arrays.
                    let joined: Vec<String> = arr
                        .iter()
                        .map(|el| match el {
                            Value::String(s) => s.clone(),
                            Value::Null => String::new(),
                            other => other.to_string(),
                        })
                        .collect();
                    out.push((key, Value::String(joined.join("|"))));
                } else {
                    // Non-primitive array → JSON string in cell.
                    out.push((key, Value::String(serde_json::to_string(arr).unwrap())));
                }
            }
            _ => {
                out.push((key, v.clone()));
            }
        }
    }
}

fn is_primitive(v: &Value) -> bool {
    matches!(v, Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_))
}

/// Unflatten a map of dotted keys back into nested objects.
fn unflatten(flat: &HashMap<String, Value>) -> Value {
    let mut root = Value::Object(Map::new());
    for (dotted_key, val) in flat {
        let parts: Vec<&str> = dotted_key.split('.').collect();
        set_nested(&mut root, &parts, val.clone());
    }
    root
}

fn set_nested(current: &mut Value, parts: &[&str], val: Value) {
    if parts.len() == 1 {
        if let Value::Object(map) = current {
            map.insert(parts[0].to_string(), val);
        }
        return;
    }
    if let Value::Object(map) = current {
        let entry = map
            .entry(parts[0].to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        set_nested(entry, &parts[1..], val);
    }
}

// ---------------------------------------------------------------------------
// Internal: CSV serialisation
// ---------------------------------------------------------------------------

fn to_csv(data: &Value) -> String {
    let arr = data.as_array().unwrap();

    // Collect all flattened rows and the superset of headers.
    let mut all_rows: Vec<HashMap<String, Value>> = Vec::new();
    let mut header_set: BTreeSet<String> = BTreeSet::new();

    for item in arr {
        let flat = flatten_row(item);
        let mut map = HashMap::new();
        for (k, v) in flat {
            header_set.insert(k.clone());
            map.insert(k, v);
        }
        all_rows.push(map);
    }

    let headers: Vec<String> = header_set.into_iter().collect();

    let mut wtr = csv::Writer::from_writer(Vec::new());
    // Write header row.
    wtr.write_record(&headers).unwrap();

    // Write data rows.
    for row in &all_rows {
        let record: Vec<String> = headers
            .iter()
            .map(|h| match row.get(h) {
                Some(Value::Null) | None => String::new(),
                Some(Value::Bool(b)) => b.to_string(),
                Some(Value::Number(n)) => n.to_string(),
                Some(Value::String(s)) => s.clone(),
                Some(other) => serde_json::to_string(other).unwrap(),
            })
            .collect();
        wtr.write_record(&record).unwrap();
    }

    wtr.flush().unwrap();
    String::from_utf8(wtr.into_inner().unwrap()).unwrap()
}

fn from_csv(text: &str) -> Value {
    let cursor = Cursor::new(text.as_bytes());
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_reader(cursor);

    let headers: Vec<String> = match rdr.headers() {
        Ok(h) => h.iter().map(|s| s.to_string()).collect(),
        Err(_) => return Value::Null,
    };

    let mut result: Vec<Value> = Vec::new();

    for record in rdr.records() {
        let record = match record {
            Ok(r) => r,
            Err(_) => continue,
        };
        let mut flat: HashMap<String, Value> = HashMap::new();
        for (i, header) in headers.iter().enumerate() {
            let cell = record.get(i).unwrap_or("");
            flat.insert(header.clone(), parse_cell(cell));
        }
        result.push(unflatten(&flat));
    }

    Value::Array(result)
}

/// Parse a single CSV cell back to an appropriate `Value`.
fn parse_cell(cell: &str) -> Value {
    // Empty → null
    if cell.is_empty() {
        return Value::Null;
    }
    // Booleans
    if cell == "true" {
        return Value::Bool(true);
    }
    if cell == "false" {
        return Value::Bool(false);
    }
    // Integer
    if let Ok(n) = cell.parse::<i64>() {
        return Value::Number(n.into());
    }
    // Float
    if let Ok(f) = cell.parse::<f64>() {
        if let Some(n) = serde_json::Number::from_f64(f) {
            return Value::Number(n);
        }
    }
    // JSON object or array
    if (cell.starts_with('{') && cell.ends_with('}'))
        || (cell.starts_with('[') && cell.ends_with(']'))
    {
        if let Ok(v) = serde_json::from_str::<Value>(cell) {
            return v;
        }
    }
    // Pipe-separated → array (must contain at least one pipe)
    if cell.contains('|') {
        let parts: Vec<Value> = cell
            .split('|')
            .map(|p| {
                let p = p.trim();
                if p.is_empty() {
                    Value::Null
                } else if p == "true" {
                    Value::Bool(true)
                } else if p == "false" {
                    Value::Bool(false)
                } else if let Ok(n) = p.parse::<i64>() {
                    Value::Number(n.into())
                } else if let Ok(f) = p.parse::<f64>() {
                    serde_json::Number::from_f64(f)
                        .map(Value::Number)
                        .unwrap_or_else(|| Value::String(p.to_string()))
                } else {
                    Value::String(p.to_string())
                }
            })
            .collect();
        return Value::Array(parts);
    }
    // Plain string
    Value::String(cell.to_string())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_basic_round_trip() {
        let data = json!([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25}
        ]);
        let packed = pack(&data);
        assert!(packed.contains("name"));
        assert!(packed.contains("Alice"));

        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr.len(), 2);
        assert_eq!(arr[0]["name"], "Alice");
        assert_eq!(arr[0]["age"], 30);
        assert_eq!(arr[1]["name"], "Bob");
        assert_eq!(arr[1]["age"], 25);
    }

    #[test]
    fn test_commas_in_values() {
        let data = json!([
            {"city": "Raleigh, NC", "pop": 500000},
            {"city": "Austin, TX", "pop": 1000000}
        ]);
        let packed = pack(&data);
        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr[0]["city"], "Raleigh, NC");
        assert_eq!(arr[1]["city"], "Austin, TX");
    }

    #[test]
    fn test_nested_objects_dot_flatten() {
        let data = json!([
            {"name": "Alice", "address": {"city": "NYC", "zip": "10001"}},
            {"name": "Bob",   "address": {"city": "LA",  "zip": "90001"}}
        ]);
        let packed = pack(&data);
        assert!(packed.contains("address.city"));
        assert!(packed.contains("address.zip"));

        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr[0]["address"]["city"], "NYC");
        assert_eq!(arr[0]["address"]["zip"], "10001");
        assert_eq!(arr[1]["address"]["city"], "LA");
    }

    #[test]
    fn test_primitive_arrays_pipe_join() {
        let data = json!([
            {"name": "Alice", "langs": ["Python", "Java"]},
            {"name": "Bob",   "langs": ["Rust", "Go"]}
        ]);
        let packed = pack(&data);
        assert!(packed.contains("Python|Java") || packed.contains("Python|Java"));

        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        let langs = arr[0]["langs"].as_array().unwrap();
        assert_eq!(langs[0], "Python");
        assert_eq!(langs[1], "Java");
    }

    #[test]
    fn test_nulls() {
        let data = json!([
            {"name": "Alice", "email": null},
            {"name": "Bob",   "email": "bob@x.com"}
        ]);
        let packed = pack(&data);
        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert!(arr[0]["email"].is_null());
        assert_eq!(arr[1]["email"], "bob@x.com");
    }

    #[test]
    fn test_booleans() {
        let data = json!([
            {"name": "Alice", "active": true},
            {"name": "Bob",   "active": false}
        ]);
        let packed = pack(&data);
        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr[0]["active"], true);
        assert_eq!(arr[1]["active"], false);
    }

    #[test]
    fn test_numbers() {
        let data = json!([
            {"item": "A", "price": 9.99, "qty": 3},
            {"item": "B", "price": 19.5, "qty": 1}
        ]);
        let packed = pack(&data);
        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr[0]["price"], 9.99);
        assert_eq!(arr[0]["qty"], 3);
        assert_eq!(arr[1]["price"], 19.5);
    }

    #[test]
    fn test_non_uniform_objects() {
        // Objects with different keys but enough overlap (>=30%).
        let data = json!([
            {"name": "Alice", "age": 30, "city": "NYC"},
            {"name": "Bob",   "age": 25}
        ]);
        let packed = pack(&data);
        // Should still produce CSV because Bob has 2/3 keys = 66% >= 30%.
        assert!(packed.contains("name"));

        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        assert_eq!(arr[0]["name"], "Alice");
        assert_eq!(arr[0]["city"], "NYC");
        // Bob has no city → null.
        assert!(arr[1]["city"].is_null());
    }

    #[test]
    fn test_json_fallback_single_object() {
        let data = json!({"name": "Alice"});
        let packed = pack(&data);
        // Should be JSON, not CSV.
        assert_eq!(packed, r#"{"name":"Alice"}"#);
        let unpacked = unpack(&packed);
        assert_eq!(unpacked["name"], "Alice");
    }

    #[test]
    fn test_json_fallback_single_element_array() {
        let data = json!([{"name": "Alice"}]);
        let packed = pack(&data);
        // < 2 items → JSON fallback.
        assert!(packed.starts_with('['));
        let unpacked = unpack(&packed);
        assert_eq!(unpacked[0]["name"], "Alice");
    }

    #[test]
    fn test_json_fallback_primitive_array() {
        let data = json!([1, 2, 3]);
        let packed = pack(&data);
        assert_eq!(packed, "[1,2,3]");
    }

    #[test]
    fn test_pack_for_prompt() {
        let data = json!([
            {"name": "Alice", "age": 30},
            {"name": "Bob",   "age": 25}
        ]);
        let result = pack_for_prompt("Here is the data:", &data);
        assert!(result.starts_with("Here is the data:"));
        assert!(result.contains("Alice"));
    }

    #[test]
    fn test_non_primitive_array_in_cell() {
        let data = json!([
            {"name": "Alice", "scores": [{"math": 90}, {"eng": 80}]},
            {"name": "Bob",   "scores": [{"math": 70}, {"eng": 60}]}
        ]);
        let packed = pack(&data);
        let unpacked = unpack(&packed);
        let arr = unpacked.as_array().unwrap();
        let scores = arr[0]["scores"].as_array().unwrap();
        assert_eq!(scores[0]["math"], 90);
    }
}
