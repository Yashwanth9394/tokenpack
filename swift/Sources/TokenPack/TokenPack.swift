/// TokenPack - Pack JSON data into token-efficient CSV for LLM prompts.
///
/// Usage:
///   let csv = TokenPack.pack(myData)        // JSON → CSV (fewer tokens)
///   let json = TokenPack.unpack(csv)         // CSV → back to dicts
///   let prompt = TokenPack.packForPrompt("Analyze:", data: myData)

import Foundation

// MARK: - Public API

public enum TokenPack {

    /// Convert JSON-compatible data to the most token-efficient text format.
    ///
    /// - Parameter data: `[[String: Any]]`, a JSON string, or any JSON-serializable value.
    /// - Returns: CSV string for packable arrays, compact JSON otherwise.
    public static func pack(_ data: Any) -> String {
        var resolved = data

        // If data is a String, try parsing as JSON first
        if let str = data as? String {
            guard let jsonData = str.data(using: .utf8),
                  let parsed = try? JSONSerialization.jsonObject(with: jsonData, options: []) else {
                return str
            }
            resolved = parsed
        }

        // If array of dicts with >= 2 items and packable -> CSV
        if let array = resolved as? [[String: Any]], array.count >= 2, isPackableArray(array) {
            return toCsv(array)
        }

        // Fallback: compact JSON
        if let jsonData = try? JSONSerialization.data(withJSONObject: resolved, options: [.sortedKeys, .fragmentsAllowed]),
           let jsonStr = String(data: jsonData, encoding: .utf8) {
            return jsonStr
        }

        return "\(resolved)"
    }

    /// Convert packed text back to JSON-compatible objects.
    ///
    /// - Parameter text: CSV (produced by `pack`) or JSON string.
    /// - Returns: Array of dictionaries.
    public static func unpack(_ text: String) -> [[String: Any]] {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return [] }

        let first = trimmed.first!
        if first == "[" || first == "{" {
            if let data = trimmed.data(using: .utf8),
               let parsed = try? JSONSerialization.jsonObject(with: data, options: []) {
                if let array = parsed as? [[String: Any]] {
                    return array
                }
                // Single dict -> wrap in array
                if let dict = parsed as? [String: Any] {
                    return [dict]
                }
            }
            return []
        }

        // Otherwise treat as CSV
        return fromCsv(trimmed)
    }

    /// Convenience: combine a user message with packed data.
    public static func packForPrompt(_ message: String, data: Any) -> String {
        let packed = pack(data)
        return "\(message)\n\(packed)"
    }
}

// MARK: - Shape Detection

private func isPackableArray(_ data: [[String: Any]]) -> Bool {
    if data.isEmpty { return false }

    // Collect all keys across all rows
    var allKeys = Set<String>()
    for item in data {
        for key in item.keys {
            allKeys.insert(key)
        }
    }
    if allKeys.isEmpty { return false }

    // Shared keys: intersection of all rows' key sets
    var sharedKeys = Set(data[0].keys)
    for item in data {
        sharedKeys.formIntersection(item.keys)
    }
    if sharedKeys.isEmpty { return false }

    // Each row must have at least 30% of the superset key count
    let threshold = max(Double(allKeys.count) * 0.3, 1.0)
    for item in data {
        if Double(item.count) < threshold {
            return false
        }
    }

    return true
}

// MARK: - CSV Writing

private func flattenValue(_ value: Any, prefix: String) -> [(String, Any?)] {
    // Nested dict -> dot notation
    if let dict = value as? [String: Any] {
        var out: [(String, Any?)] = []
        for (k, v) in dict.sorted(by: { $0.key < $1.key }) {
            let fullKey = prefix.isEmpty ? k : "\(prefix).\(k)"
            out.append(contentsOf: flattenValue(v, prefix: fullKey))
        }
        return out
    }

    // Array
    if let array = value as? [Any] {
        // All primitives -> pipe-join
        if array.allSatisfy({ isPrimitive($0) }) {
            let joined = array.map { primToStr($0) }.joined(separator: "|")
            return [(prefix, joined)]
        }
        // Complex array -> JSON fallback
        if let jsonData = try? JSONSerialization.data(withJSONObject: array, options: [.sortedKeys]),
           let jsonStr = String(data: jsonData, encoding: .utf8) {
            return [(prefix, jsonStr)]
        }
        return [(prefix, nil)]
    }

    return [(prefix, value)]
}

private func flattenRow(_ row: [String: Any]) -> [(String, Any?)] {
    var flat: [(String, Any?)] = []
    for (key, value) in row.sorted(by: { $0.key < $1.key }) {
        flat.append(contentsOf: flattenValue(value, prefix: key))
    }
    return flat
}

private func toCsv(_ data: [[String: Any]]) -> String {
    // Flatten all rows
    let flatRows: [[(String, Any?)]] = data.map { flattenRow($0) }

    // Collect ordered superset of keys (preserving first-seen order)
    var seen = [String]()
    var seenSet = Set<String>()
    for row in flatRows {
        for (key, _) in row {
            if !seenSet.contains(key) {
                seenSet.insert(key)
                seen.append(key)
            }
        }
    }
    let headers = seen

    // Build lookup dicts for each row
    let rowDicts: [[String: Any?]] = flatRows.map { pairs in
        var dict = [String: Any?]()
        for (k, v) in pairs {
            dict[k] = v
        }
        return dict
    }

    var lines: [String] = []
    lines.append(csvLine(headers))
    for row in rowDicts {
        let cells = headers.map { h -> String in
            if let val = row[h] {
                return formatCell(val)
            }
            return ""
        }
        lines.append(csvLine(cells))
    }

    return lines.joined(separator: "\n")
}

private func formatCell(_ value: Any?) -> String {
    guard let value = value else { return "" }

    if value is NSNull { return "" }

    if isBool(value), let b = value as? Bool { return b ? "true" : "false" }
    if let n = value as? Int { return "\(n)" }
    if let n = value as? Double {
        // If it's a whole number, format without decimal
        if n == n.rounded() && !n.isInfinite && !n.isNaN && abs(n) < 1e15 {
            return "\(Int(n))"
        }
        return "\(n)"
    }
    if let s = value as? String { return s }

    // Fallback: JSON
    if let jsonData = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
       let jsonStr = String(data: jsonData, encoding: .utf8) {
        return jsonStr
    }
    return "\(value)"
}

private func csvLine(_ fields: [String]) -> String {
    return fields.map { csvEscape($0) }.joined(separator: ",")
}

private func csvEscape(_ value: String) -> String {
    if value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r") {
        let escaped = value.replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(escaped)\""
    }
    return value
}

// MARK: - CSV Parsing (unpack)

private func fromCsv(_ text: String) -> [[String: Any]] {
    let lines = parseCsvLines(text)
    if lines.count < 2 { return [] }

    let headers = lines[0]
    var rows: [[String: Any]] = []

    for i in 1..<lines.count {
        let csvRow = lines[i]
        if csvRow.allSatisfy({ $0.isEmpty }) { continue }

        var flat: [String: Any] = [:]
        for (j, header) in headers.enumerated() {
            let raw = j < csvRow.count ? csvRow[j] : ""
            if let parsed = parseCell(raw) {
                flat[header] = parsed
            }
        }
        rows.append(unflatten(flat))
    }

    return rows
}

private func parseCell(_ raw: String) -> Any? {
    // Empty -> nil
    if raw.isEmpty { return nil }

    // Booleans
    if raw == "true" { return true }
    if raw == "false" { return false }

    // Integer
    if let intVal = Int(raw) {
        // Make sure the string representation matches (no leading zeros etc.)
        if "\(intVal)" == raw {
            return intVal
        }
    }

    // Double
    if raw.contains("."), let dblVal = Double(raw) {
        return dblVal
    }

    // Pipe-separated array
    if raw.contains("|") && !raw.hasPrefix("[") {
        let parts = raw.components(separatedBy: "|")
        return parts.map { parseCell($0) as Any }
    }

    // Embedded JSON array/object
    if raw.hasPrefix("[") || raw.hasPrefix("{") {
        if let data = raw.data(using: .utf8),
           let parsed = try? JSONSerialization.jsonObject(with: data, options: []) {
            return parsed
        }
    }

    // Plain string
    return raw
}

private func unflatten(_ flat: [String: Any]) -> [String: Any] {
    var result: [String: Any] = [:]
    for (key, value) in flat {
        let parts = key.components(separatedBy: ".")
        setNestedValue(&result, parts: parts, index: 0, value: value)
    }
    return result
}

/// Recursively set a value in a nested dictionary using key path parts.
private func setNestedValue(_ dict: inout [String: Any], parts: [String], index: Int, value: Any) {
    let key = parts[index]
    if index == parts.count - 1 {
        // Leaf: set the value directly
        dict[key] = value
    } else {
        // Intermediate: ensure a nested dict exists and recurse
        var nested = dict[key] as? [String: Any] ?? [:]
        setNestedValue(&nested, parts: parts, index: index + 1, value: value)
        dict[key] = nested
    }
}

private func parseCsvLines(_ text: String) -> [[String]] {
    var lines: [[String]] = []
    var current: [String] = []
    var field = ""
    var inQuotes = false

    let chars = Array(text)
    var i = 0

    while i < chars.count {
        let ch = chars[i]

        if inQuotes {
            if ch == "\"" {
                if i + 1 < chars.count && chars[i + 1] == "\"" {
                    field.append("\"")
                    i += 2
                    continue
                } else {
                    inQuotes = false
                    i += 1
                    continue
                }
            } else {
                field.append(ch)
            }
        } else {
            if ch == "\"" {
                inQuotes = true
            } else if ch == "," {
                current.append(field)
                field = ""
            } else if ch == "\n" {
                current.append(field)
                field = ""
                lines.append(current)
                current = []
            } else if ch == "\r" {
                // skip carriage return
            } else {
                field.append(ch)
            }
        }

        i += 1
    }

    // Flush last field and line
    current.append(field)
    if current.contains(where: { !$0.isEmpty }) {
        lines.append(current)
    }

    return lines
}

// MARK: - Helpers

/// Distinguish true Bool from NSNumber-bridged integers.
/// In Foundation, Bool bridges to NSNumber and `as? Bool` can match integers.
/// CFBooleanGetTypeID lets us detect actual booleans.
private func isBool(_ value: Any) -> Bool {
    guard let number = value as? NSNumber else { return false }
    return CFGetTypeID(number) == CFBooleanGetTypeID()
}

private func isPrimitive(_ value: Any) -> Bool {
    if value is NSNull { return true }
    if value is String { return true }
    if isBool(value) { return true }
    if value is Int { return true }
    if value is Double { return true }
    // NSNumber that isn't Bool
    if value is NSNumber { return true }
    return false
}

private func primToStr(_ value: Any) -> String {
    if value is NSNull { return "" }
    if isBool(value), let b = value as? Bool { return b ? "true" : "false" }
    if let s = value as? String { return s }
    if let n = value as? Int { return "\(n)" }
    if let n = value as? Double { return "\(n)" }
    return ""
}
