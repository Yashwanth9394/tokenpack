using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PromptPack;

/// <summary>
/// Converts JSON arrays of objects into token-efficient CSV for LLM prompts.
/// </summary>
public static class PromptPack
{
    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /// <summary>
    /// Convert a JSON string to the most token-efficient text format.
    /// Arrays of similar objects become CSV; everything else stays compact JSON.
    /// </summary>
    public static string Pack(string json)
    {
        JsonElement element;
        try
        {
            using var doc = JsonDocument.Parse(json);
            element = doc.RootElement.Clone();
        }
        catch
        {
            return json;
        }

        return Pack(element);
    }

    /// <summary>
    /// Convert a JsonElement to the most token-efficient text format.
    /// </summary>
    public static string Pack(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Array && element.GetArrayLength() >= 2)
        {
            var items = new List<JsonElement>();
            foreach (var item in element.EnumerateArray())
                items.Add(item);

            if (IsPackableArray(items))
                return ToCsv(items);
        }

        return ToCompactJson(element);
    }

    /// <summary>
    /// Convert packed text (CSV or JSON) back to a JsonElement.
    /// </summary>
    public static JsonElement Unpack(string text)
    {
        text = text.Trim();
        if (string.IsNullOrEmpty(text))
        {
            using var emptyDoc = JsonDocument.Parse("[]");
            return emptyDoc.RootElement.Clone();
        }

        if (text[0] == '{' || text[0] == '[')
        {
            try
            {
                using var doc = JsonDocument.Parse(text);
                return doc.RootElement.Clone();
            }
            catch { }
        }

        return FromCsv(text);
    }

    /// <summary>
    /// Combine a user message with packed data.
    /// </summary>
    public static string PackForPrompt(string message, string json)
    {
        return message + "\n" + Pack(json);
    }

    // -----------------------------------------------------------------------
    // Shape detection
    // -----------------------------------------------------------------------

    private static bool IsPackableArray(List<JsonElement> items)
    {
        if (items.Count < 2) return false;

        // All items must be objects
        foreach (var item in items)
        {
            if (item.ValueKind != JsonValueKind.Object) return false;
        }

        // Compute superset and intersection of keys
        var supersetKeys = new HashSet<string>();
        HashSet<string>? intersectionKeys = null;

        foreach (var item in items)
        {
            var currentKeys = new HashSet<string>();
            var flat = FlattenObject(item, "");
            foreach (var k in flat.Keys)
            {
                currentKeys.Add(k);
                supersetKeys.Add(k);
            }

            if (intersectionKeys == null)
                intersectionKeys = new HashSet<string>(currentKeys);
            else
                intersectionKeys.IntersectWith(currentKeys);
        }

        if (supersetKeys.Count == 0) return false;
        if (intersectionKeys == null || intersectionKeys.Count == 0) return false;

        // Each row must have >= 30% of superset keys
        double threshold = Math.Max(supersetKeys.Count * 0.3, 1);
        foreach (var item in items)
        {
            var flat = FlattenObject(item, "");
            if (flat.Count < threshold) return false;
        }

        return true;
    }

    // -----------------------------------------------------------------------
    // CSV writing
    // -----------------------------------------------------------------------

    private static Dictionary<string, object?> FlattenObject(JsonElement element, string prefix)
    {
        var result = new Dictionary<string, object?>();

        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in element.EnumerateObject())
            {
                string key = string.IsNullOrEmpty(prefix) ? prop.Name : prefix + "." + prop.Name;
                var nested = FlattenValue(prop.Value, key);
                foreach (var kv in nested)
                    result[kv.Key] = kv.Value;
            }
        }

        return result;
    }

    private static Dictionary<string, object?> FlattenValue(JsonElement value, string key)
    {
        var result = new Dictionary<string, object?>();

        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                foreach (var prop in value.EnumerateObject())
                {
                    string childKey = key + "." + prop.Name;
                    var nested = FlattenValue(prop.Value, childKey);
                    foreach (var kv in nested)
                        result[kv.Key] = kv.Value;
                }
                break;

            case JsonValueKind.Array:
                if (IsPrimitiveArray(value))
                {
                    var parts = new List<string>();
                    foreach (var item in value.EnumerateArray())
                        parts.Add(PrimToStr(item));
                    result[key] = string.Join("|", parts);
                }
                else
                {
                    result[key] = ToCompactJson(value);
                }
                break;

            case JsonValueKind.Null:
            case JsonValueKind.Undefined:
                result[key] = null;
                break;

            case JsonValueKind.True:
                result[key] = true;
                break;

            case JsonValueKind.False:
                result[key] = false;
                break;

            case JsonValueKind.Number:
                if (value.TryGetInt64(out long l))
                    result[key] = l;
                else
                    result[key] = value.GetDouble();
                break;

            case JsonValueKind.String:
                result[key] = value.GetString();
                break;
        }

        return result;
    }

    private static string ToCsv(List<JsonElement> items)
    {
        var flatRows = new List<Dictionary<string, object?>>();
        foreach (var item in items)
            flatRows.Add(FlattenObject(item, ""));

        // Ordered superset of keys (insertion order)
        var headers = new List<string>();
        var seen = new HashSet<string>();
        foreach (var row in flatRows)
        {
            foreach (var k in row.Keys)
            {
                if (seen.Add(k))
                    headers.Add(k);
            }
        }

        var sb = new StringBuilder();
        sb.Append(CsvLine(headers.Select(h => h).ToArray()));

        foreach (var row in flatRows)
        {
            sb.Append('\n');
            var cells = headers.Select(h =>
                row.TryGetValue(h, out var val) ? FormatCell(val) : "").ToArray();
            sb.Append(CsvLine(cells));
        }

        return sb.ToString();
    }

    private static string FormatCell(object? value)
    {
        if (value == null) return "";
        if (value is bool b) return b ? "true" : "false";
        if (value is long l) return l.ToString(CultureInfo.InvariantCulture);
        if (value is int i) return i.ToString(CultureInfo.InvariantCulture);
        if (value is double d) return FormatDouble(d);
        if (value is string s) return s;
        return value.ToString() ?? "";
    }

    private static string FormatDouble(double d)
    {
        if (d == Math.Truncate(d) && !double.IsInfinity(d) && !double.IsNaN(d))
            return ((long)d).ToString(CultureInfo.InvariantCulture);
        return d.ToString("G", CultureInfo.InvariantCulture);
    }

    private static string CsvLine(string[] fields)
    {
        return string.Join(",", fields.Select(CsvEscape));
    }

    private static string CsvEscape(string value)
    {
        if (value.Contains(',') || value.Contains('"') ||
            value.Contains('\n') || value.Contains('\r'))
        {
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }
        return value;
    }

    // -----------------------------------------------------------------------
    // CSV parsing (unpack)
    // -----------------------------------------------------------------------

    private static JsonElement FromCsv(string text)
    {
        var lines = ParseCsvLines(text);
        if (lines.Count < 2)
        {
            using var emptyDoc = JsonDocument.Parse("[]");
            return emptyDoc.RootElement.Clone();
        }

        var headers = lines[0];
        var rows = new List<Dictionary<string, object?>>();

        for (int i = 1; i < lines.Count; i++)
        {
            var csvRow = lines[i];
            if (csvRow.All(c => c == "")) continue;

            var flat = new Dictionary<string, object?>();
            for (int j = 0; j < headers.Count; j++)
            {
                string raw = j < csvRow.Count ? csvRow[j] : "";
                flat[headers[j]] = ParseCell(raw);
            }
            rows.Add(Unflatten(flat));
        }

        // Convert to JsonElement
        string json = SerializeRows(rows);
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.Clone();
    }

    private static object? ParseCell(string raw)
    {
        if (raw == "") return null;
        if (raw == "true") return true;
        if (raw == "false") return false;

        // Try integer
        if (Regex.IsMatch(raw, @"^-?\d+$"))
        {
            if (long.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out long l))
                return l;
        }

        // Try double
        if (Regex.IsMatch(raw, @"^-?\d+\.\d+$"))
        {
            if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out double d))
                return d;
        }

        // Pipe-separated (not starting with '[')
        if (raw.Contains('|') && !raw.StartsWith("["))
        {
            var parts = raw.Split('|');
            return parts.Select(ParseCell).ToList();
        }

        // Try JSON
        if (raw.StartsWith("[") || raw.StartsWith("{"))
        {
            try
            {
                using var doc = JsonDocument.Parse(raw);
                return doc.RootElement.Clone();
            }
            catch { }
        }

        return raw;
    }

    private static Dictionary<string, object?> Unflatten(Dictionary<string, object?> flat)
    {
        var result = new Dictionary<string, object?>();
        foreach (var kv in flat)
        {
            var parts = kv.Key.Split('.');
            SetNested(result, parts, 0, kv.Value);
        }
        return result;
    }

    private static void SetNested(Dictionary<string, object?> map, string[] keys, int index, object? value)
    {
        if (index == keys.Length - 1)
        {
            map[keys[index]] = value;
            return;
        }

        if (!map.TryGetValue(keys[index], out var existing) || existing is not Dictionary<string, object?> sub)
        {
            sub = new Dictionary<string, object?>();
            map[keys[index]] = sub;
        }

        SetNested(sub, keys, index + 1, value);
    }

    private static List<List<string>> ParseCsvLines(string text)
    {
        var lines = new List<List<string>>();
        var current = new List<string>();
        var field = new StringBuilder();
        bool inQuotes = false;

        for (int i = 0; i < text.Length; i++)
        {
            char ch = text[i];

            if (inQuotes)
            {
                if (ch == '"')
                {
                    if (i + 1 < text.Length && text[i + 1] == '"')
                    {
                        field.Append('"');
                        i++;
                    }
                    else
                    {
                        inQuotes = false;
                    }
                }
                else
                {
                    field.Append(ch);
                }
            }
            else
            {
                if (ch == '"')
                {
                    inQuotes = true;
                }
                else if (ch == ',')
                {
                    current.Add(field.ToString());
                    field.Clear();
                }
                else if (ch == '\n')
                {
                    current.Add(field.ToString());
                    field.Clear();
                    lines.Add(current);
                    current = new List<string>();
                }
                else if (ch == '\r')
                {
                    // skip
                }
                else
                {
                    field.Append(ch);
                }
            }
        }

        current.Add(field.ToString());
        if (current.Any(c => c != ""))
        {
            lines.Add(current);
        }

        return lines;
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private static bool IsPrimitiveArray(JsonElement array)
    {
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Object || item.ValueKind == JsonValueKind.Array)
                return false;
        }
        return true;
    }

    private static string PrimToStr(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.Null => "",
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            JsonValueKind.Number => value.TryGetInt64(out long l)
                ? l.ToString(CultureInfo.InvariantCulture)
                : value.GetDouble().ToString("G", CultureInfo.InvariantCulture),
            JsonValueKind.String => value.GetString() ?? "",
            _ => value.ToString()
        };
    }

    private static string ToCompactJson(JsonElement element)
    {
        return JsonSerializer.Serialize(element, new JsonSerializerOptions
        {
            WriteIndented = false
        });
    }

    /// <summary>
    /// Serialize List of dictionaries (with possible nesting) to JSON string.
    /// </summary>
    private static string SerializeRows(List<Dictionary<string, object?>> rows)
    {
        var sb = new StringBuilder();
        sb.Append('[');
        for (int i = 0; i < rows.Count; i++)
        {
            if (i > 0) sb.Append(',');
            SerializeObject(sb, rows[i]);
        }
        sb.Append(']');
        return sb.ToString();
    }

    private static void SerializeObject(StringBuilder sb, Dictionary<string, object?> obj)
    {
        sb.Append('{');
        bool first = true;
        foreach (var kv in obj)
        {
            if (!first) sb.Append(',');
            first = false;
            sb.Append(JsonSerializer.Serialize(kv.Key));
            sb.Append(':');
            SerializeValue(sb, kv.Value);
        }
        sb.Append('}');
    }

    private static void SerializeValue(StringBuilder sb, object? value)
    {
        switch (value)
        {
            case null:
                sb.Append("null");
                break;
            case bool b:
                sb.Append(b ? "true" : "false");
                break;
            case long l:
                sb.Append(l.ToString(CultureInfo.InvariantCulture));
                break;
            case int i:
                sb.Append(i.ToString(CultureInfo.InvariantCulture));
                break;
            case double d:
                sb.Append(FormatDouble(d));
                break;
            case string s:
                sb.Append(JsonSerializer.Serialize(s));
                break;
            case List<object?> list:
                sb.Append('[');
                for (int idx = 0; idx < list.Count; idx++)
                {
                    if (idx > 0) sb.Append(',');
                    SerializeValue(sb, list[idx]);
                }
                sb.Append(']');
                break;
            case Dictionary<string, object?> dict:
                SerializeObject(sb, dict);
                break;
            case JsonElement el:
                sb.Append(ToCompactJson(el));
                break;
            default:
                sb.Append(JsonSerializer.Serialize(value.ToString()));
                break;
        }
    }
}
