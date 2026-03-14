package com.tokenpack

import com.google.gson.*
import kotlin.math.floor
import kotlin.math.max

/**
 * TokenPack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * ```
 * val csv = TokenPack.pack(jsonString)        // JSON -> CSV (fewer tokens)
 * val arr = TokenPack.unpack(csv)             // CSV -> JSON (back to original)
 * val prompt = TokenPack.packForPrompt("Analyze:", jsonString)
 * ```
 */
object TokenPack {

    private val gson = Gson()

    // -------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------

    /**
     * Convert a JSON string to the most token-efficient text format.
     * Arrays of similar objects -> CSV. Everything else -> compact JSON.
     */
    fun pack(json: String): String {
        val el = try {
            JsonParser.parseString(json)
        } catch (_: JsonSyntaxException) {
            return json
        }
        return packElement(el)
    }

    /**
     * Convert a JsonElement to the most token-efficient text format.
     */
    fun pack(element: JsonElement): String = packElement(element)

    /**
     * Convert packed text (CSV or JSON) back to a JsonArray.
     */
    fun unpack(text: String): JsonArray {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return JsonArray()

        return when (trimmed[0]) {
            '[' -> JsonParser.parseString(trimmed).asJsonArray
            '{' -> JsonArray().apply {
                add(JsonParser.parseString(trimmed).asJsonObject)
            }
            else -> fromCsv(trimmed)
        }
    }

    /**
     * Combine a message with packed data.
     */
    fun packForPrompt(message: String, json: String): String =
        "$message\n${pack(json)}"

    fun packForPrompt(message: String, element: JsonElement): String =
        "$message\n${pack(element)}"

    // -------------------------------------------------------------------
    // Internal: shape detection
    // -------------------------------------------------------------------

    private fun packElement(el: JsonElement): String {
        if (!el.isJsonArray) return gson.toJson(el)

        val arr = el.asJsonArray
        if (arr.size() < 2) return gson.toJson(el)
        if (!isPackableArray(arr)) return gson.toJson(el)

        return toCsv(arr)
    }

    private fun isPackableArray(arr: JsonArray): Boolean {
        val allKeys = linkedSetOf<String>()
        val rowKeys = mutableListOf<Set<String>>()

        for (item in arr) {
            if (!item.isJsonObject) return false
            val keys = item.asJsonObject.keySet()
            allKeys.addAll(keys)
            rowKeys.add(keys)
        }

        if (allKeys.isEmpty()) return false

        // Shared keys = intersection of all row key sets
        val shared = linkedSetOf<String>().apply { addAll(rowKeys[0]) }
        for (rk in rowKeys) {
            shared.retainAll(rk)
        }
        if (shared.isEmpty()) return false

        val threshold = max(allKeys.size * 0.3, 1.0)
        return rowKeys.all { it.size >= threshold }
    }

    // -------------------------------------------------------------------
    // Internal: JSON -> CSV
    // -------------------------------------------------------------------

    private fun toCsv(arr: JsonArray): String {
        val flatRows = arr.map { flattenRow(it.asJsonObject) }

        // Ordered superset of headers
        val headerSet = linkedSetOf<String>()
        for (row in flatRows) {
            headerSet.addAll(row.keys)
        }
        val headers = headerSet.toList()

        return buildString {
            append(csvLine(headers))
            for (row in flatRows) {
                append('\n')
                val values = headers.map { h -> row.getOrDefault(h, "") }
                append(csvLine(values))
            }
        }
    }

    private fun flattenRow(obj: JsonObject): Map<String, String> {
        val flat = linkedMapOf<String, String>()
        flattenValue(obj, "", flat)
        return flat
    }

    private fun flattenValue(value: JsonElement, prefix: String, out: MutableMap<String, String>) {
        when {
            value.isJsonObject -> {
                for ((key, child) in value.asJsonObject.entrySet()) {
                    val fullKey = if (prefix.isEmpty()) key else "$prefix.$key"
                    flattenValue(child, fullKey, out)
                }
            }
            value.isJsonArray -> {
                val arr = value.asJsonArray
                val allPrimitive = arr.all { !it.isJsonObject && !it.isJsonArray }
                if (allPrimitive) {
                    out[prefix] = arr.joinToString("|") { formatCell(it) }
                } else {
                    out[prefix] = gson.toJson(arr)
                }
            }
            else -> {
                out[prefix] = formatCell(value)
            }
        }
    }

    private fun formatCell(el: JsonElement?): String {
        if (el == null || el.isJsonNull) return ""
        if (el.isJsonPrimitive) {
            val p = el.asJsonPrimitive
            return when {
                p.isBoolean -> if (p.asBoolean) "true" else "false"
                p.isNumber -> {
                    val d = p.asDouble
                    if (d == floor(d) && !d.isInfinite()) {
                        d.toLong().toString()
                    } else {
                        p.asString
                    }
                }
                else -> p.asString
            }
        }
        return gson.toJson(el)
    }

    private fun csvLine(fields: List<String>): String =
        fields.joinToString(",") { csvEscape(it) }

    private fun csvEscape(value: String): String =
        if (value.contains(",") || value.contains("\"") || value.contains("\n") || value.contains("\r")) {
            "\"${value.replace("\"", "\"\"")}\""
        } else {
            value
        }

    // -------------------------------------------------------------------
    // Internal: CSV -> JSON (unpack)
    // -------------------------------------------------------------------

    private fun fromCsv(text: String): JsonArray {
        val lines = parseCsvLines(text)
        if (lines.size < 2) return JsonArray()

        val headers = lines[0]
        val result = JsonArray()

        for (i in 1 until lines.size) {
            val row = lines[i]
            if (row.all { it.isEmpty() }) continue

            val flat = linkedMapOf<String, JsonElement>()
            for (j in headers.indices) {
                val raw = if (j < row.size) row[j] else ""
                flat[headers[j]] = parseCell(raw)
            }
            result.add(unflatten(flat))
        }

        return result
    }

    private fun parseCell(raw: String): JsonElement {
        if (raw.isEmpty()) return JsonNull.INSTANCE

        when (raw) {
            "true" -> return JsonPrimitive(true)
            "false" -> return JsonPrimitive(false)
        }

        // Try integer
        if (raw.matches(Regex("-?\\d+"))) {
            raw.toLongOrNull()?.let { return JsonPrimitive(it) }
        }

        // Try float
        if (raw.matches(Regex("-?\\d+\\.\\d+"))) {
            raw.toDoubleOrNull()?.let { return JsonPrimitive(it) }
        }

        // Pipe-separated array
        if ('|' in raw && !raw.startsWith("[")) {
            return JsonArray().apply {
                for (part in raw.split("|", limit = -1)) {
                    add(parseCell(part))
                }
            }
        }

        // Embedded JSON
        if (raw.startsWith("[") || raw.startsWith("{")) {
            try {
                return JsonParser.parseString(raw)
            } catch (_: JsonSyntaxException) {
                // fall through
            }
        }

        return JsonPrimitive(raw)
    }

    private fun unflatten(flat: Map<String, JsonElement>): JsonObject {
        val result = JsonObject()
        for ((key, value) in flat) {
            val parts = key.split(".")
            var current = result
            for (i in 0 until parts.size - 1) {
                if (!current.has(parts[i]) || !current[parts[i]].isJsonObject) {
                    current.add(parts[i], JsonObject())
                }
                current = current.getAsJsonObject(parts[i])
            }
            current.add(parts.last(), value)
        }
        return result
    }

    private fun parseCsvLines(text: String): List<List<String>> {
        val lines = mutableListOf<List<String>>()
        var current = mutableListOf<String>()
        val field = StringBuilder()
        var inQuotes = false

        var i = 0
        while (i < text.length) {
            val ch = text[i]

            if (inQuotes) {
                if (ch == '"') {
                    if (i + 1 < text.length && text[i + 1] == '"') {
                        field.append('"')
                        i++
                    } else {
                        inQuotes = false
                    }
                } else {
                    field.append(ch)
                }
            } else {
                when (ch) {
                    '"' -> inQuotes = true
                    ',' -> {
                        current.add(field.toString())
                        field.setLength(0)
                    }
                    '\n' -> {
                        current.add(field.toString())
                        field.setLength(0)
                        lines.add(current)
                        current = mutableListOf()
                    }
                    '\r' -> { /* skip */ }
                    else -> field.append(ch)
                }
            }
            i++
        }

        current.add(field.toString())
        if (current.any { it.isNotEmpty() }) {
            lines.add(current)
        }

        return lines
    }
}
