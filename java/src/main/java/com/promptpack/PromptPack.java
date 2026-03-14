package com.promptpack;

import com.google.gson.*;

import java.util.*;
import java.util.stream.Collectors;

/**
 * PromptPack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * <pre>
 * String csv = PromptPack.pack(jsonArray);       // JSON → CSV (fewer tokens)
 * JsonArray arr = PromptPack.unpack(csv);         // CSV → JSON (back to original)
 * String prompt = PromptPack.packForPrompt("Analyze:", jsonArray);
 * </pre>
 */
public final class PromptPack {

    private static final Gson GSON = new Gson();

    private PromptPack() {}

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /**
     * Convert a JSON string to the most token-efficient text format.
     * Arrays of similar objects → CSV. Everything else → compact JSON.
     */
    public static String pack(String json) {
        JsonElement el;
        try {
            el = JsonParser.parseString(json);
        } catch (JsonSyntaxException e) {
            return json; // not valid JSON, return as-is
        }
        return packElement(el);
    }

    /**
     * Convert a JsonElement to the most token-efficient text format.
     */
    public static String pack(JsonElement element) {
        return packElement(element);
    }

    /**
     * Convert packed text (CSV or JSON) back to a JsonArray.
     */
    public static JsonArray unpack(String text) {
        text = text.trim();
        if (text.isEmpty()) return new JsonArray();

        if (text.charAt(0) == '[') {
            return JsonParser.parseString(text).getAsJsonArray();
        }
        if (text.charAt(0) == '{') {
            JsonArray arr = new JsonArray();
            arr.add(JsonParser.parseString(text).getAsJsonObject());
            return arr;
        }

        return fromCsv(text);
    }

    /**
     * Combine a message with packed data.
     */
    public static String packForPrompt(String message, String json) {
        return message + "\n" + pack(json);
    }

    public static String packForPrompt(String message, JsonElement element) {
        return message + "\n" + pack(element);
    }

    // -----------------------------------------------------------------------
    // Internal: shape detection
    // -----------------------------------------------------------------------

    private static String packElement(JsonElement el) {
        if (!el.isJsonArray()) return GSON.toJson(el);

        JsonArray arr = el.getAsJsonArray();
        if (arr.size() < 2) return GSON.toJson(el);

        if (!isPackableArray(arr)) return GSON.toJson(el);

        return toCsv(arr);
    }

    private static boolean isPackableArray(JsonArray arr) {
        Set<String> allKeys = new LinkedHashSet<>();
        List<Set<String>> rowKeys = new ArrayList<>();

        for (JsonElement item : arr) {
            if (!item.isJsonObject()) return false;
            Set<String> keys = item.getAsJsonObject().keySet();
            allKeys.addAll(keys);
            rowKeys.add(keys);
        }

        if (allKeys.isEmpty()) return false;

        // Must share at least some keys
        Set<String> shared = new LinkedHashSet<>(rowKeys.get(0));
        for (Set<String> rk : rowKeys) {
            shared.retainAll(rk);
        }
        if (shared.isEmpty()) return false;

        double threshold = Math.max(allKeys.size() * 0.3, 1);
        for (Set<String> rk : rowKeys) {
            if (rk.size() < threshold) return false;
        }

        return true;
    }

    // -----------------------------------------------------------------------
    // Internal: JSON → CSV
    // -----------------------------------------------------------------------

    private static String toCsv(JsonArray arr) {
        List<Map<String, String>> flatRows = new ArrayList<>();

        for (JsonElement item : arr) {
            flatRows.add(flattenRow(item.getAsJsonObject()));
        }

        // Ordered superset of headers
        LinkedHashSet<String> headerSet = new LinkedHashSet<>();
        for (Map<String, String> row : flatRows) {
            headerSet.addAll(row.keySet());
        }
        List<String> headers = new ArrayList<>(headerSet);

        StringBuilder sb = new StringBuilder();
        sb.append(csvLine(headers));

        for (Map<String, String> row : flatRows) {
            sb.append('\n');
            List<String> values = headers.stream()
                    .map(h -> row.getOrDefault(h, ""))
                    .collect(Collectors.toList());
            sb.append(csvLine(values));
        }

        return sb.toString();
    }

    private static Map<String, String> flattenRow(JsonObject obj) {
        Map<String, String> flat = new LinkedHashMap<>();
        flattenValue(obj, "", flat);
        return flat;
    }

    private static void flattenValue(JsonElement value, String prefix, Map<String, String> out) {
        if (value.isJsonObject()) {
            JsonObject obj = value.getAsJsonObject();
            for (Map.Entry<String, JsonElement> entry : obj.entrySet()) {
                String key = prefix.isEmpty() ? entry.getKey() : prefix + "." + entry.getKey();
                flattenValue(entry.getValue(), key, out);
            }
        } else if (value.isJsonArray()) {
            JsonArray arr = value.getAsJsonArray();
            boolean allPrimitive = true;
            for (JsonElement el : arr) {
                if (el.isJsonObject() || el.isJsonArray()) {
                    allPrimitive = false;
                    break;
                }
            }
            if (allPrimitive) {
                // Pipe-join primitives
                StringJoiner sj = new StringJoiner("|");
                for (JsonElement el : arr) {
                    sj.add(formatCell(el));
                }
                out.put(prefix, sj.toString());
            } else {
                // Fallback: JSON string in cell
                out.put(prefix, GSON.toJson(arr));
            }
        } else {
            out.put(prefix, formatCell(value));
        }
    }

    private static String formatCell(JsonElement el) {
        if (el == null || el.isJsonNull()) return "";
        if (el.isJsonPrimitive()) {
            JsonPrimitive p = el.getAsJsonPrimitive();
            if (p.isBoolean()) return p.getAsBoolean() ? "true" : "false";
            if (p.isNumber()) {
                // Avoid trailing .0 for integers
                double d = p.getAsDouble();
                if (d == Math.floor(d) && !Double.isInfinite(d)) {
                    return String.valueOf((long) d);
                }
                return p.getAsString();
            }
            return p.getAsString();
        }
        return GSON.toJson(el);
    }

    private static String csvLine(List<String> fields) {
        return fields.stream().map(PromptPack::csvEscape).collect(Collectors.joining(","));
    }

    private static String csvEscape(String value) {
        if (value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r")) {
            return "\"" + value.replace("\"", "\"\"") + "\"";
        }
        return value;
    }

    // -----------------------------------------------------------------------
    // Internal: CSV → JSON (unpack)
    // -----------------------------------------------------------------------

    private static JsonArray fromCsv(String text) {
        List<List<String>> lines = parseCsvLines(text);
        if (lines.size() < 2) return new JsonArray();

        List<String> headers = lines.get(0);
        JsonArray result = new JsonArray();

        for (int i = 1; i < lines.size(); i++) {
            List<String> row = lines.get(i);
            if (row.stream().allMatch(String::isEmpty)) continue;

            Map<String, JsonElement> flat = new LinkedHashMap<>();
            for (int j = 0; j < headers.size(); j++) {
                String raw = j < row.size() ? row.get(j) : "";
                flat.put(headers.get(j), parseCell(raw));
            }

            result.add(unflatten(flat));
        }

        return result;
    }

    private static JsonElement parseCell(String raw) {
        if (raw.isEmpty()) return JsonNull.INSTANCE;
        if ("true".equals(raw)) return new JsonPrimitive(true);
        if ("false".equals(raw)) return new JsonPrimitive(false);

        // Try integer
        if (raw.matches("-?\\d+")) {
            try {
                return new JsonPrimitive(Long.parseLong(raw));
            } catch (NumberFormatException ignored) {}
        }

        // Try float
        if (raw.matches("-?\\d+\\.\\d+")) {
            try {
                return new JsonPrimitive(Double.parseDouble(raw));
            } catch (NumberFormatException ignored) {}
        }

        // Pipe-separated array
        if (raw.contains("|") && !raw.startsWith("[")) {
            JsonArray arr = new JsonArray();
            for (String part : raw.split("\\|", -1)) {
                arr.add(parseCell(part));
            }
            return arr;
        }

        // Embedded JSON
        if (raw.startsWith("[") || raw.startsWith("{")) {
            try {
                return JsonParser.parseString(raw);
            } catch (JsonSyntaxException ignored) {}
        }

        return new JsonPrimitive(raw);
    }

    private static JsonObject unflatten(Map<String, JsonElement> flat) {
        JsonObject result = new JsonObject();
        for (Map.Entry<String, JsonElement> entry : flat.entrySet()) {
            String[] parts = entry.getKey().split("\\.");
            JsonObject current = result;
            for (int i = 0; i < parts.length - 1; i++) {
                if (!current.has(parts[i]) || !current.get(parts[i]).isJsonObject()) {
                    current.add(parts[i], new JsonObject());
                }
                current = current.getAsJsonObject(parts[i]);
            }
            current.add(parts[parts.length - 1], entry.getValue());
        }
        return result;
    }

    private static List<List<String>> parseCsvLines(String text) {
        List<List<String>> lines = new ArrayList<>();
        List<String> current = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;

        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);

            if (inQuotes) {
                if (ch == '"') {
                    if (i + 1 < text.length() && text.charAt(i + 1) == '"') {
                        field.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    field.append(ch);
                }
            } else {
                if (ch == '"') {
                    inQuotes = true;
                } else if (ch == ',') {
                    current.add(field.toString());
                    field.setLength(0);
                } else if (ch == '\n') {
                    current.add(field.toString());
                    field.setLength(0);
                    lines.add(current);
                    current = new ArrayList<>();
                } else if (ch != '\r') {
                    field.append(ch);
                }
            }
        }

        current.add(field.toString());
        if (current.stream().anyMatch(s -> !s.isEmpty())) {
            lines.add(current);
        }

        return lines;
    }
}
