package com.promptpack;

import com.google.gson.*;

import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * PromptPack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * <pre>
 * String csv = PromptPack.pack(jsonArray);       // JSON → CSV (fewer tokens)
 * JsonArray arr = PromptPack.unpack(csv);         // CSV → JSON (back to original)
 * String prompt = PromptPack.packForPrompt("Analyze:", jsonArray);
 *
 * // 1-line integration with any LLM SDK:
 * var response = PromptPack.withPacked("Analyze:", data, content -&gt;
 *     client.chat().completions().create(params.addUserMessage(content).build())
 * );
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

    /**
     * 1-line integration with any LLM SDK. Packs the data and passes
     * the combined prompt to your SDK caller function.
     *
     * <pre>
     * // OpenAI Java SDK:
     * var response = PromptPack.withPacked("Analyze:", jsonData, content -&gt;
     *     client.chat().completions().create(
     *         ChatCompletionCreateParams.builder()
     *             .model(ChatModel.GPT_4O)
     *             .addUserMessage(content)
     *             .build()
     *     )
     * );
     *
     * // Anthropic Java SDK:
     * var response = PromptPack.withPacked("Analyze:", jsonData, content -&gt;
     *     client.messages().create(
     *         MessageCreateParams.builder()
     *             .model(Model.CLAUDE_SONNET_4_20250514)
     *             .maxTokens(1024)
     *             .addUserMessage(content)
     *             .build()
     *     )
     * );
     * </pre>
     *
     * @param message  The instruction/message to prepend
     * @param json     The JSON data to pack
     * @param caller   A function that receives the packed prompt and calls your LLM SDK
     * @param <T>      The return type from your SDK call
     * @return The result from the SDK call
     */
    public static <T> T withPacked(String message, String json, Function<String, T> caller) {
        String packed = packForPrompt(message, json);
        return caller.apply(packed);
    }

    /**
     * 1-line integration with any LLM SDK (JsonElement overload).
     */
    public static <T> T withPacked(String message, JsonElement element, Function<String, T> caller) {
        String packed = packForPrompt(message, element);
        return caller.apply(packed);
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
    // Internal: key/pipe escaping
    // -----------------------------------------------------------------------

    private static String escapeKey(String key) {
        return key.replace("\\", "\\\\").replace(".", "\\.");
    }

    private static List<String> splitDottedKey(String key) {
        List<String> parts = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        int i = 0;
        while (i < key.length()) {
            if (key.charAt(i) == '\\' && i + 1 < key.length()) {
                current.append(key.charAt(i + 1));
                i += 2;
            } else if (key.charAt(i) == '.') {
                parts.add(current.toString());
                current.setLength(0);
                i += 1;
            } else {
                current.append(key.charAt(i));
                i += 1;
            }
        }
        parts.add(current.toString());
        return parts;
    }

    private static String escapePipe(String s) {
        return s.replace("\\", "\\\\").replace("|", "\\|");
    }

    private static List<String> splitPipeJoined(String raw) {
        List<String> parts = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        int i = 0;
        while (i < raw.length()) {
            if (raw.charAt(i) == '\\' && i + 1 < raw.length()) {
                current.append(raw.charAt(i + 1));
                i += 2;
            } else if (raw.charAt(i) == '|') {
                parts.add(current.toString());
                current.setLength(0);
                i += 1;
            } else {
                current.append(raw.charAt(i));
                i += 1;
            }
        }
        parts.add(current.toString());
        return parts;
    }

    // -----------------------------------------------------------------------
    // Internal: JSON → CSV
    // -----------------------------------------------------------------------

    // Track which values came from pipe-joining (for type detection)
    private static final String PIPE_JOINED_MARKER = "\u0000__PP_PIPE__";

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

        // Detect column types
        List<String> colTypes = new ArrayList<>();
        for (String header : headers) {
            colTypes.add(detectColumnType(flatRows, header, arr, headers));
        }

        StringBuilder sb = new StringBuilder();
        sb.append(csvLine(headers));

        // Type hints row
        sb.append('\n');
        sb.append('#');
        sb.append(String.join(",", colTypes));

        for (Map<String, String> row : flatRows) {
            sb.append('\n');
            List<String> values = headers.stream()
                    .map(h -> {
                        String v = row.getOrDefault(h, "");
                        // Remove pipe-joined marker before writing
                        if (v.startsWith(PIPE_JOINED_MARKER)) {
                            return v.substring(PIPE_JOINED_MARKER.length());
                        }
                        return v;
                    })
                    .collect(Collectors.toList());
            sb.append(csvLine(values));
        }

        return sb.toString();
    }

    private static String detectColumnType(List<Map<String, String>> flatRows, String header,
                                           JsonArray originalArr, List<String> headers) {
        // Check if any value in this column was pipe-joined
        boolean hasPipeJoined = false;
        Set<String> typesSeen = new HashSet<>();

        for (Map<String, String> row : flatRows) {
            String val = row.get(header);
            if (val == null || val.isEmpty()) continue;

            if (val.startsWith(PIPE_JOINED_MARKER)) {
                hasPipeJoined = true;
                continue;
            }

            // Check original JSON types by trying to determine from the formatted value
            // We need to check original data types
        }

        if (hasPipeJoined) return "a";

        // Check original JSON element types for this column
        for (JsonElement item : originalArr) {
            if (!item.isJsonObject()) continue;
            JsonObject obj = item.getAsJsonObject();

            // Navigate to the value using the header (which may be dot-notated)
            JsonElement val = resolveNestedValue(obj, header);
            if (val == null || val.isJsonNull()) continue;

            if (val.isJsonPrimitive()) {
                JsonPrimitive p = val.getAsJsonPrimitive();
                if (p.isBoolean()) typesSeen.add("b");
                else if (p.isNumber()) typesSeen.add("n");
                else typesSeen.add("s");
            } else if (val.isJsonArray()) {
                typesSeen.add("a");
            } else {
                typesSeen.add("j");
            }
        }

        if (typesSeen.size() == 1) return typesSeen.iterator().next();
        if (typesSeen.contains("s")) return "s";
        if (typesSeen.isEmpty()) return "x";
        return "x";
    }

    private static JsonElement resolveNestedValue(JsonObject obj, String header) {
        // The header might be dot-escaped. Parse it to find the right value.
        List<String> parts = splitDottedKey(header);
        JsonElement current = obj;
        for (int i = 0; i < parts.size(); i++) {
            if (current == null || !current.isJsonObject()) return null;
            current = current.getAsJsonObject().get(parts.get(i));
        }
        return current;
    }

    private static Map<String, String> flattenRow(JsonObject obj) {
        Map<String, String> flat = new LinkedHashMap<>();
        for (Map.Entry<String, JsonElement> entry : obj.entrySet()) {
            String escapedKey = escapeKey(entry.getKey());
            flattenValue(entry.getValue(), escapedKey, flat);
        }
        return flat;
    }

    private static void flattenValue(JsonElement value, String prefix, Map<String, String> out) {
        if (value.isJsonObject()) {
            JsonObject obj = value.getAsJsonObject();
            for (Map.Entry<String, JsonElement> entry : obj.entrySet()) {
                String escapedKey = escapeKey(entry.getKey());
                String key = prefix.isEmpty() ? escapedKey : prefix + "." + escapedKey;
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
                // Pipe-join primitives with escaping
                StringJoiner sj = new StringJoiner("|");
                for (JsonElement el : arr) {
                    sj.add(escapePipe(formatCell(el)));
                }
                // Mark as pipe-joined for type detection
                out.put(prefix, PIPE_JOINED_MARKER + sj.toString());
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

        // Check for type hints row
        List<String> colTypes = null;
        int dataStartIdx = 1;

        if (lines.size() > 1) {
            List<String> maybeTypes = lines.get(1);
            if (!maybeTypes.isEmpty() && maybeTypes.get(0).startsWith("#")) {
                // Type hints: CSV parser splits "#s,n,a,b" into ["#s", "n", "a", "b"]
                colTypes = new ArrayList<>();
                colTypes.add(maybeTypes.get(0).substring(1));
                for (int i = 1; i < maybeTypes.size(); i++) {
                    colTypes.add(maybeTypes.get(i));
                }
                dataStartIdx = 2;
            }
        }

        JsonArray result = new JsonArray();

        for (int i = dataStartIdx; i < lines.size(); i++) {
            List<String> row = lines.get(i);
            if (row.stream().allMatch(String::isEmpty)) continue;

            Map<String, JsonElement> flat = new LinkedHashMap<>();
            for (int j = 0; j < headers.size(); j++) {
                String raw = j < row.size() ? row.get(j) : "";
                String typeHint = colTypes != null && j < colTypes.size() ? colTypes.get(j) : null;
                flat.put(headers.get(j), parseCell(raw, typeHint));
            }

            result.add(unflatten(flat));
        }

        return result;
    }

    private static JsonElement parseCell(String raw, String typeHint) {
        if (raw.isEmpty()) return JsonNull.INSTANCE;

        // Type-hinted parsing (safe round-trip)
        if ("s".equals(typeHint)) return new JsonPrimitive(raw);
        if ("b".equals(typeHint)) return new JsonPrimitive("true".equals(raw));
        if ("n".equals(typeHint)) {
            try {
                if (raw.contains(".")) return new JsonPrimitive(Double.parseDouble(raw));
                return new JsonPrimitive(Long.parseLong(raw));
            } catch (NumberFormatException e) {
                return new JsonPrimitive(raw);
            }
        }
        if ("a".equals(typeHint)) {
            JsonArray arr = new JsonArray();
            for (String part : splitPipeJoined(raw)) {
                arr.add(parseArrayElement(part));
            }
            return arr;
        }
        if ("j".equals(typeHint)) {
            try {
                return JsonParser.parseString(raw);
            } catch (JsonSyntaxException e) {
                return new JsonPrimitive(raw);
            }
        }

        // No type hint — auto-detect (backward compat)
        return parseCellAutoDetect(raw);
    }

    private static JsonElement parseCellAutoDetect(String raw) {
        if (raw.isEmpty()) return JsonNull.INSTANCE;
        if ("true".equals(raw)) return new JsonPrimitive(true);
        if ("false".equals(raw)) return new JsonPrimitive(false);

        if (raw.matches("-?\\d+")) {
            try {
                return new JsonPrimitive(Long.parseLong(raw));
            } catch (NumberFormatException ignored) {}
        }

        if (raw.matches("-?\\d+\\.\\d+")) {
            try {
                return new JsonPrimitive(Double.parseDouble(raw));
            } catch (NumberFormatException ignored) {}
        }

        if (raw.contains("|") && !raw.startsWith("[")) {
            JsonArray arr = new JsonArray();
            for (String part : raw.split("\\|", -1)) {
                arr.add(parseArrayElement(part));
            }
            return arr;
        }

        if (raw.startsWith("[") || raw.startsWith("{")) {
            try {
                return JsonParser.parseString(raw);
            } catch (JsonSyntaxException ignored) {}
        }

        return new JsonPrimitive(raw);
    }

    private static JsonElement parseArrayElement(String raw) {
        if (raw.isEmpty()) return JsonNull.INSTANCE;
        if ("true".equals(raw)) return new JsonPrimitive(true);
        if ("false".equals(raw)) return new JsonPrimitive(false);

        if (raw.matches("-?\\d+")) {
            try {
                return new JsonPrimitive(Long.parseLong(raw));
            } catch (NumberFormatException ignored) {}
        }

        if (raw.matches("-?\\d+\\.\\d+")) {
            try {
                return new JsonPrimitive(Double.parseDouble(raw));
            } catch (NumberFormatException ignored) {}
        }

        return new JsonPrimitive(raw);
    }

    private static JsonObject unflatten(Map<String, JsonElement> flat) {
        JsonObject result = new JsonObject();
        for (Map.Entry<String, JsonElement> entry : flat.entrySet()) {
            List<String> parts = splitDottedKey(entry.getKey());
            JsonObject current = result;
            for (int i = 0; i < parts.size() - 1; i++) {
                if (!current.has(parts.get(i)) || !current.get(parts.get(i)).isJsonObject()) {
                    current.add(parts.get(i), new JsonObject());
                }
                current = current.getAsJsonObject(parts.get(i));
            }
            current.add(parts.get(parts.size() - 1), entry.getValue());
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
