package promptpack

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestBasicRoundTrip(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "age": 30, "city": "NYC"},
		{"name": "Bob", "age": 25, "city": "LA"},
	}

	packed := Pack(input)
	if !strings.Contains(packed, "name") {
		t.Fatal("packed output should contain header 'name'")
	}
	// Should be CSV, not JSON
	if strings.HasPrefix(packed, "[") {
		t.Fatal("expected CSV output, got JSON")
	}

	unpacked := Unpack(packed)
	if len(unpacked) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(unpacked))
	}

	// Check values (age will come back as int64 from CSV)
	if unpacked[0]["name"] != "Alice" {
		t.Errorf("expected Alice, got %v", unpacked[0]["name"])
	}
	if unpacked[1]["name"] != "Bob" {
		t.Errorf("expected Bob, got %v", unpacked[1]["name"])
	}
	if unpacked[0]["age"] != int64(30) {
		t.Errorf("expected 30 (int64), got %v (%T)", unpacked[0]["age"], unpacked[0]["age"])
	}
	if unpacked[0]["city"] != "NYC" {
		t.Errorf("expected NYC, got %v", unpacked[0]["city"])
	}
}

func TestValuesWithCommasQuotesSpacesNewlines(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "O'Brien, James", "bio": "Line1\nLine2", "quote": `He said "hello"`},
		{"name": "Smith, Jane", "bio": "Simple bio", "quote": "No quotes"},
	}

	packed := Pack(input)
	unpacked := Unpack(packed)

	if len(unpacked) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(unpacked))
	}
	if unpacked[0]["name"] != "O'Brien, James" {
		t.Errorf("comma in value not preserved: got %v", unpacked[0]["name"])
	}
	if unpacked[0]["bio"] != "Line1\nLine2" {
		t.Errorf("newline in value not preserved: got %v", unpacked[0]["bio"])
	}
	if unpacked[0]["quote"] != `He said "hello"` {
		t.Errorf("quotes in value not preserved: got %v", unpacked[0]["quote"])
	}
}

func TestNestedObjectsDotFlatten(t *testing.T) {
	input := []map[string]interface{}{
		{
			"name": "Alice",
			"address": map[string]interface{}{
				"city":  "NYC",
				"state": "NY",
			},
		},
		{
			"name": "Bob",
			"address": map[string]interface{}{
				"city":  "LA",
				"state": "CA",
			},
		},
	}

	packed := Pack(input)
	if !strings.Contains(packed, "address.city") {
		t.Errorf("expected dot-flattened header 'address.city', got: %s", packed)
	}
	if !strings.Contains(packed, "address.state") {
		t.Errorf("expected dot-flattened header 'address.state', got: %s", packed)
	}

	unpacked := Unpack(packed)
	if len(unpacked) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(unpacked))
	}

	addr, ok := unpacked[0]["address"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected address to be a nested map, got %T", unpacked[0]["address"])
	}
	if addr["city"] != "NYC" {
		t.Errorf("expected NYC, got %v", addr["city"])
	}
	if addr["state"] != "NY" {
		t.Errorf("expected NY, got %v", addr["state"])
	}
}

func TestNestedPrimitiveArraysPipeJoin(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "skills": []interface{}{"Python", "TypeScript"}},
		{"name": "Bob", "skills": []interface{}{"Go", "Rust"}},
	}

	packed := Pack(input)
	if !strings.Contains(packed, "Python|TypeScript") {
		t.Errorf("expected pipe-joined skills, got: %s", packed)
	}

	unpacked := Unpack(packed)
	skills, ok := unpacked[0]["skills"].([]interface{})
	if !ok {
		t.Fatalf("expected skills to be []interface{}, got %T", unpacked[0]["skills"])
	}
	if len(skills) != 2 || skills[0] != "Python" || skills[1] != "TypeScript" {
		t.Errorf("expected [Python TypeScript], got %v", skills)
	}
}

func TestNullHandling(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "email": "alice@example.com"},
		{"name": "Bob", "email": nil},
	}

	packed := Pack(input)
	unpacked := Unpack(packed)

	if len(unpacked) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(unpacked))
	}
	if unpacked[0]["name"] != "Alice" {
		t.Errorf("expected Alice, got %v", unpacked[0]["name"])
	}
	if unpacked[1]["email"] != nil {
		t.Errorf("expected nil for Bob's email, got %v (%T)", unpacked[1]["email"], unpacked[1]["email"])
	}
}

func TestBooleanAndNumberPreservation(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "active": true, "score": 95.5},
		{"name": "Bob", "active": false, "score": 88.0},
	}

	packed := Pack(input)
	unpacked := Unpack(packed)

	if unpacked[0]["active"] != true {
		t.Errorf("expected true, got %v (%T)", unpacked[0]["active"], unpacked[0]["active"])
	}
	if unpacked[1]["active"] != false {
		t.Errorf("expected false, got %v (%T)", unpacked[1]["active"], unpacked[1]["active"])
	}
	if unpacked[0]["score"] != 95.5 {
		t.Errorf("expected 95.5, got %v (%T)", unpacked[0]["score"], unpacked[0]["score"])
	}
	// 88.0 will be formatted as "88" (integer) and parsed back as int64
	if unpacked[1]["score"] != int64(88) {
		t.Errorf("expected 88 (int64), got %v (%T)", unpacked[1]["score"], unpacked[1]["score"])
	}
}

func TestNonUniformObjects(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "age": 30, "email": "alice@example.com"},
		{"name": "Bob", "age": 25},
		{"name": "Charlie", "age": 35, "phone": "555-1234"},
	}

	packed := Pack(input)
	// Should still be CSV since they share enough keys
	if strings.HasPrefix(packed, "[") {
		t.Error("expected CSV output for non-uniform objects with sufficient overlap")
	}

	unpacked := Unpack(packed)
	if len(unpacked) != 3 {
		t.Fatalf("expected 3 rows, got %d", len(unpacked))
	}
	// Bob should have nil email
	if unpacked[1]["email"] != nil {
		t.Errorf("expected nil for Bob's email, got %v", unpacked[1]["email"])
	}
}

func TestFallbackToJSONSingleRow(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "age": 30},
	}

	packed := Pack(input)
	if !strings.HasPrefix(packed, "[") {
		t.Error("expected JSON fallback for single-row array")
	}
}

func TestFallbackToJSONNonPackable(t *testing.T) {
	// Completely different keys
	input := []map[string]interface{}{
		{"a": 1, "b": 2},
		{"x": 3, "y": 4},
	}

	packed := Pack(input)
	// These share no keys, so intersection is 0 → JSON fallback
	if !strings.HasPrefix(packed, "[") {
		t.Error("expected JSON fallback for non-packable data with no shared keys")
	}
}

func TestPackStringInput(t *testing.T) {
	jsonStr := `[{"name":"Alice","age":30},{"name":"Bob","age":25}]`
	packed := Pack(jsonStr)
	if strings.HasPrefix(packed, "[") {
		t.Error("expected CSV output when packing a JSON string of packable array")
	}
	unpacked := Unpack(packed)
	if len(unpacked) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(unpacked))
	}
}

func TestPackForPrompt(t *testing.T) {
	input := []map[string]interface{}{
		{"name": "Alice", "role": "Engineer"},
		{"name": "Bob", "role": "Designer"},
	}

	result := PackForPrompt("Here is the team data:", input)
	if !strings.HasPrefix(result, "Here is the team data:") {
		t.Error("expected result to start with the message")
	}
	if !strings.Contains(result, "name") {
		t.Error("expected result to contain packed data")
	}
}

func TestUnpackJSON(t *testing.T) {
	jsonStr := `[{"name":"Alice","age":30},{"name":"Bob","age":25}]`
	result := Unpack(jsonStr)
	if len(result) != 2 {
		t.Fatalf("expected 2 rows, got %d", len(result))
	}
	if result[0]["name"] != "Alice" {
		t.Errorf("expected Alice, got %v", result[0]["name"])
	}
}

func TestDeeplyNestedObjects(t *testing.T) {
	input := []map[string]interface{}{
		{
			"id": 1,
			"meta": map[string]interface{}{
				"created": map[string]interface{}{
					"year":  2024,
					"month": 1,
				},
			},
		},
		{
			"id": 2,
			"meta": map[string]interface{}{
				"created": map[string]interface{}{
					"year":  2024,
					"month": 6,
				},
			},
		},
	}

	packed := Pack(input)
	if !strings.Contains(packed, "meta.created.year") {
		t.Errorf("expected deeply nested dot-flattened key, got: %s", packed)
	}

	unpacked := Unpack(packed)
	meta, ok := unpacked[0]["meta"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected meta to be map, got %T", unpacked[0]["meta"])
	}
	created, ok := meta["created"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected meta.created to be map, got %T", meta["created"])
	}
	if created["year"] != int64(2024) {
		t.Errorf("expected 2024, got %v", created["year"])
	}
}

func TestEmptyInput(t *testing.T) {
	result := Unpack("")
	if result != nil {
		t.Errorf("expected nil for empty input, got %v", result)
	}
}

func TestTokenSavings(t *testing.T) {
	// Demonstrate that CSV is shorter than JSON for typical data
	input := []map[string]interface{}{
		{"name": "Alice Johnson", "age": 30, "city": "New York", "role": "Engineer"},
		{"name": "Bob Smith", "age": 25, "city": "Los Angeles", "role": "Designer"},
		{"name": "Charlie Brown", "age": 35, "city": "Chicago", "role": "Manager"},
		{"name": "Diana Prince", "age": 28, "city": "San Francisco", "role": "Developer"},
		{"name": "Eve Wilson", "age": 32, "city": "Seattle", "role": "Analyst"},
	}

	jsonBytes, _ := json.Marshal(input)
	jsonLen := len(string(jsonBytes))
	csvStr := Pack(input)
	csvLen := len(csvStr)

	savings := float64(jsonLen-csvLen) / float64(jsonLen) * 100
	t.Logf("JSON length: %d, CSV length: %d, Savings: %.1f%%", jsonLen, csvLen, savings)

	if csvLen >= jsonLen {
		t.Error("CSV should be shorter than JSON for this data")
	}
}

func TestParseCellEdgeCases(t *testing.T) {
	tests := []struct {
		input    string
		expected interface{}
	}{
		{"", nil},
		{"true", true},
		{"false", false},
		{"42", int64(42)},
		{"3.14", 3.14},
		{"hello", "hello"},
		{"a|b|c", []interface{}{"a", "b", "c"}},
	}

	for _, tt := range tests {
		result := parseCell(tt.input)
		if !reflect.DeepEqual(result, tt.expected) {
			t.Errorf("parseCell(%q) = %v (%T), expected %v (%T)",
				tt.input, result, result, tt.expected, tt.expected)
		}
	}
}

func TestLowOverlapFallbackToJSON(t *testing.T) {
	// Each row has only 1 out of many keys → below 30% threshold
	input := []map[string]interface{}{
		{"a": 1, "b": 2, "c": 3, "d": 4},
		{"a": 5, "e": 6, "f": 7, "g": 8},
	}
	// Superset has 7 keys, row 1 has 4/7 ≈ 57%, row 2 has 4/7 ≈ 57%
	// Both above 30% and intersection (a) > 0, so should pack
	packed := Pack(input)
	if strings.HasPrefix(packed, "[") {
		t.Log("Packed as JSON (keys overlap is sufficient but let's verify)")
	}

	// Now test truly low overlap
	input2 := []map[string]interface{}{
		{"a": 1},
		{"b": 2, "c": 3, "d": 4, "e": 5, "f": 6},
	}
	// Superset has 6 keys, row 1 has 1/6 ≈ 16.7% → below 30%
	packed2 := Pack(input2)
	if !strings.HasPrefix(packed2, "[") {
		t.Error("expected JSON fallback for low-overlap data")
	}
}
