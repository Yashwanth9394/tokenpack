package promptpack

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Pack converts JSON-compatible data to a compact CSV representation when possible.
// Accepts []map[string]interface{} or a JSON string. If the data is a packable array
// of similar objects (>=2 rows), it returns CSV with dot-flattened headers.
// Otherwise it returns compact JSON.
func Pack(data interface{}) string {
	var rows []map[string]interface{}

	switch v := data.(type) {
	case string:
		// Try parsing as JSON
		if err := json.Unmarshal([]byte(v), &rows); err != nil {
			// Not an array of objects, return compact JSON of whatever it is
			var arbitrary interface{}
			if err2 := json.Unmarshal([]byte(v), &arbitrary); err2 != nil {
				return v
			}
			b, _ := json.Marshal(arbitrary)
			return string(b)
		}
	case []map[string]interface{}:
		rows = v
	case []interface{}:
		for _, item := range v {
			if m, ok := item.(map[string]interface{}); ok {
				rows = append(rows, m)
			} else {
				// Not all items are maps, fallback to JSON
				b, _ := json.Marshal(data)
				return string(b)
			}
		}
	default:
		b, _ := json.Marshal(data)
		return string(b)
	}

	if !isPackableArray(rows) {
		b, _ := json.Marshal(rows)
		return string(b)
	}

	// Flatten all rows
	flatRows := make([]map[string]string, len(rows))
	for i, row := range rows {
		flatRows[i] = flattenMap(row, "")
	}

	// Collect all headers (superset)
	headerSet := map[string]bool{}
	for _, fr := range flatRows {
		for k := range fr {
			headerSet[k] = true
		}
	}
	headers := make([]string, 0, len(headerSet))
	for k := range headerSet {
		headers = append(headers, k)
	}
	sort.Strings(headers)

	// Write CSV
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)

	w.Write(headers)
	for _, fr := range flatRows {
		record := make([]string, len(headers))
		for j, h := range headers {
			record[j] = fr[h] // empty string if missing
		}
		w.Write(record)
	}
	w.Flush()

	return strings.TrimRight(buf.String(), "\n")
}

// Unpack converts a CSV or JSON string back to []map[string]interface{}.
func Unpack(text string) []map[string]interface{} {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}

	// Try JSON first
	if strings.HasPrefix(text, "[") {
		var result []map[string]interface{}
		if err := json.Unmarshal([]byte(text), &result); err == nil {
			return result
		}
	}

	// Parse as CSV
	r := csv.NewReader(strings.NewReader(text))
	records, err := r.ReadAll()
	if err != nil || len(records) < 2 {
		return nil
	}

	headers := records[0]
	var result []map[string]interface{}

	for i := 1; i < len(records); i++ {
		flat := map[string]interface{}{}
		for j, h := range headers {
			var val string
			if j < len(records[i]) {
				val = records[i][j]
			}
			flat[h] = parseCell(val)
		}
		result = append(result, unflatten(flat))
	}

	return result
}

// PackForPrompt combines a user message with packed data.
func PackForPrompt(message string, data interface{}) string {
	packed := Pack(data)
	return message + "\n\n" + packed
}

// isPackableArray checks if the data is suitable for CSV packing.
// Requires: >=2 rows, all maps, shared keys (intersection > 0),
// each row has >= 30% of the superset keys.
func isPackableArray(rows []map[string]interface{}) bool {
	if len(rows) < 2 {
		return false
	}

	// Compute superset and intersection of keys
	supersetKeys := map[string]bool{}
	var intersectionKeys map[string]bool

	for i, row := range rows {
		if len(row) == 0 {
			return false
		}
		currentKeys := map[string]bool{}
		flat := flattenMap(row, "")
		for k := range flat {
			currentKeys[k] = true
			supersetKeys[k] = true
		}
		if i == 0 {
			intersectionKeys = make(map[string]bool)
			for k := range currentKeys {
				intersectionKeys[k] = true
			}
		} else {
			for k := range intersectionKeys {
				if !currentKeys[k] {
					delete(intersectionKeys, k)
				}
			}
		}
	}

	if len(intersectionKeys) == 0 {
		return false
	}

	supersetCount := len(supersetKeys)
	for _, row := range rows {
		flat := flattenMap(row, "")
		rowKeyCount := len(flat)
		if float64(rowKeyCount)/float64(supersetCount) < 0.3 {
			return false
		}
	}

	return true
}

// flattenMap recursively flattens nested maps using dot notation.
// Primitive arrays are pipe-joined. Nested arrays of objects are JSON-encoded.
func flattenMap(m map[string]interface{}, prefix string) map[string]string {
	result := map[string]string{}
	for k, v := range m {
		key := k
		if prefix != "" {
			key = prefix + "." + k
		}
		switch val := v.(type) {
		case map[string]interface{}:
			for fk, fv := range flattenMap(val, key) {
				result[fk] = fv
			}
		case []interface{}:
			if isPrimitiveArray(val) {
				parts := make([]string, len(val))
				for i, item := range val {
					parts[i] = formatValue(item)
				}
				result[key] = strings.Join(parts, "|")
			} else {
				b, _ := json.Marshal(val)
				result[key] = string(b)
			}
		case nil:
			result[key] = ""
		default:
			result[key] = formatValue(v)
		}
	}
	return result
}

// isPrimitiveArray checks if all elements are non-map, non-array (primitives).
func isPrimitiveArray(arr []interface{}) bool {
	for _, item := range arr {
		switch item.(type) {
		case map[string]interface{}, []interface{}:
			return false
		}
	}
	return true
}

// formatValue converts a value to its string representation.
func formatValue(v interface{}) string {
	switch val := v.(type) {
	case nil:
		return ""
	case bool:
		if val {
			return "true"
		}
		return "false"
	case float64:
		if val == math.Trunc(val) && !math.IsInf(val, 0) && !math.IsNaN(val) {
			return strconv.FormatInt(int64(val), 10)
		}
		return strconv.FormatFloat(val, 'f', -1, 64)
	case int:
		return strconv.Itoa(val)
	case int64:
		return strconv.FormatInt(val, 10)
	case string:
		return val
	default:
		return fmt.Sprintf("%v", v)
	}
}

// parseCell converts a CSV cell string back to a typed Go value.
// empty → nil, "true"/"false" → bool, integers, floats, pipe-separated → []interface{},
// JSON strings → parsed.
func parseCell(s string) interface{} {
	if s == "" {
		return nil
	}
	if s == "true" {
		return true
	}
	if s == "false" {
		return false
	}

	// Try integer
	if i, err := strconv.ParseInt(s, 10, 64); err == nil {
		// Make sure the string exactly matches the integer representation
		// to avoid interpreting floats as ints
		if strconv.FormatInt(i, 10) == s {
			return i
		}
	}

	// Try float
	if f, err := strconv.ParseFloat(s, 64); err == nil {
		if strconv.FormatFloat(f, 'f', -1, 64) == s {
			return f
		}
	}

	// Try JSON (arrays/objects)
	if (strings.HasPrefix(s, "[") && strings.HasSuffix(s, "]")) ||
		(strings.HasPrefix(s, "{") && strings.HasSuffix(s, "}")) {
		var parsed interface{}
		if err := json.Unmarshal([]byte(s), &parsed); err == nil {
			return parsed
		}
	}

	// Try pipe-separated (must have at least one pipe and no commas in the value
	// that would suggest it's just regular text)
	if strings.Contains(s, "|") {
		parts := strings.Split(s, "|")
		result := make([]interface{}, len(parts))
		for i, p := range parts {
			result[i] = parsePrimitive(p)
		}
		return result
	}

	return s
}

// parsePrimitive parses a simple string into a bool, int, float, or string.
func parsePrimitive(s string) interface{} {
	if s == "true" {
		return true
	}
	if s == "false" {
		return false
	}
	if i, err := strconv.ParseInt(s, 10, 64); err == nil {
		if strconv.FormatInt(i, 10) == s {
			return i
		}
	}
	if f, err := strconv.ParseFloat(s, 64); err == nil {
		if strconv.FormatFloat(f, 'f', -1, 64) == s {
			return f
		}
	}
	return s
}

// unflatten converts a flat map with dot-notation keys into a nested map.
func unflatten(flat map[string]interface{}) map[string]interface{} {
	result := map[string]interface{}{}
	for k, v := range flat {
		parts := strings.Split(k, ".")
		setNested(result, parts, v)
	}
	return result
}

// setNested sets a value in a nested map structure given a path of keys.
func setNested(m map[string]interface{}, keys []string, value interface{}) {
	if len(keys) == 1 {
		m[keys[0]] = value
		return
	}
	sub, ok := m[keys[0]]
	if !ok {
		sub = map[string]interface{}{}
		m[keys[0]] = sub
	}
	subMap, ok := sub.(map[string]interface{})
	if !ok {
		subMap = map[string]interface{}{}
		m[keys[0]] = subMap
	}
	setNested(subMap, keys[1:], value)
}
