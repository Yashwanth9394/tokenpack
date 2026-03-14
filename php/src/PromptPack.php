<?php

namespace PromptPack;

/**
 * PromptPack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * Usage:
 *   use PromptPack\PromptPack;
 *
 *   $csv   = PromptPack::pack($myData);            // Array/JSON → CSV (fewer tokens)
 *   $array = PromptPack::unpack($csv);              // CSV → PHP array
 *   $prompt = PromptPack::packForPrompt("Analyze:", $data);
 */
class PromptPack
{
    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /**
     * Convert data to the most token-efficient text format.
     * Arrays of similar assoc arrays → CSV with dot-flattened headers.
     * Everything else → compact JSON.
     *
     * @param array|string $data PHP array or JSON string
     * @return string
     */
    public static function pack($data): string
    {
        if (is_string($data)) {
            $decoded = json_decode($data, true);
            if (json_last_error() === JSON_ERROR_NONE) {
                $data = $decoded;
            } else {
                return $data;
            }
        }

        if (is_array($data) && self::isSequential($data) && count($data) >= 2 && self::isPackableArray($data)) {
            return self::toCsv($data);
        }

        return json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    /**
     * Convert packed text back to a PHP array.
     * Detects CSV vs JSON automatically.
     *
     * @param string $text
     * @return array
     */
    public static function unpack(string $text): array
    {
        $text = trim($text);
        if ($text === '') {
            return [];
        }

        $first = $text[0];
        if ($first === '{' || $first === '[') {
            $decoded = json_decode($text, true);
            if (json_last_error() === JSON_ERROR_NONE) {
                return $decoded;
            }
        }

        return self::fromCsv($text);
    }

    /**
     * Combine a user message with packed data.
     *
     * @param string $message
     * @param array|string $data
     * @return string
     */
    public static function packForPrompt(string $message, $data): string
    {
        return $message . "\n" . self::pack($data);
    }

    // -----------------------------------------------------------------------
    // Internal: shape detection
    // -----------------------------------------------------------------------

    /**
     * Check if an array is a sequential (non-associative) list.
     */
    private static function isSequential(array $arr): bool
    {
        if (empty($arr)) {
            return true;
        }
        return array_keys($arr) === range(0, count($arr) - 1);
    }

    /**
     * Determine if the array of items is suitable for CSV packing.
     * All items must be assoc arrays, share at least one key,
     * and each row must have >= 30% of the superset of all keys.
     */
    private static function isPackableArray(array $data): bool
    {
        $allKeys = [];
        $rowKeys = [];

        foreach ($data as $item) {
            if (!is_array($item) || self::isSequential($item)) {
                return false;
            }
            $keys = array_keys($item);
            $rowKeys[] = $keys;
            foreach ($keys as $k) {
                $allKeys[$k] = true;
            }
        }

        if (empty($allKeys)) {
            return false;
        }

        // Compute shared keys (intersection of all rows)
        $shared = array_flip($rowKeys[0]);
        for ($i = 1; $i < count($rowKeys); $i++) {
            $shared = array_intersect_key($shared, array_flip($rowKeys[$i]));
        }
        if (empty($shared)) {
            return false;
        }

        // Each row must have at least 30% of the superset keys
        $supersetSize = count($allKeys);
        $threshold = max($supersetSize * 0.3, 1);
        foreach ($rowKeys as $keys) {
            if (count($keys) < $threshold) {
                return false;
            }
        }

        return true;
    }

    // -----------------------------------------------------------------------
    // Internal: CSV writing
    // -----------------------------------------------------------------------

    /**
     * Flatten a value with dot-notation prefix.
     */
    private static function flattenValue($value, string $prefix): array
    {
        // Nested assoc array → recurse with dot notation
        if (is_array($value) && !empty($value) && !self::isSequential($value)) {
            $out = [];
            foreach ($value as $k => $v) {
                $fullKey = $prefix !== '' ? $prefix . '.' . $k : (string) $k;
                $out = array_merge($out, self::flattenValue($v, $fullKey));
            }
            return $out;
        }

        // Sequential array of primitives → pipe-join
        if (is_array($value)) {
            if (self::allPrimitive($value)) {
                return [$prefix => implode('|', array_map([self::class, 'primToStr'], $value))];
            }
            return [$prefix => json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)];
        }

        return [$prefix => $value];
    }

    /**
     * Flatten an entire row (assoc array) into dot-notation keys.
     */
    private static function flattenRow(array $row): array
    {
        $flat = [];
        foreach ($row as $key => $value) {
            $flat = array_merge($flat, self::flattenValue($value, (string) $key));
        }
        return $flat;
    }

    /**
     * Convert array of assoc arrays to CSV string.
     */
    private static function toCsv(array $data): string
    {
        $flatRows = array_map([self::class, 'flattenRow'], $data);

        // Collect ordered superset of headers
        $seen = [];
        foreach ($flatRows as $row) {
            foreach (array_keys($row) as $k) {
                if (!isset($seen[$k])) {
                    $seen[$k] = true;
                }
            }
        }
        $headers = array_keys($seen);

        $lines = [self::csvLine($headers)];
        foreach ($flatRows as $row) {
            $cells = [];
            foreach ($headers as $h) {
                $cells[] = self::formatCell(array_key_exists($h, $row) ? $row[$h] : null);
            }
            $lines[] = self::csvLine($cells);
        }

        return implode("\n", $lines);
    }

    /**
     * Format a cell value as a string for CSV output.
     */
    private static function formatCell($value): string
    {
        if ($value === null) {
            return '';
        }
        if (is_bool($value)) {
            return $value ? 'true' : 'false';
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }
        if (is_string($value)) {
            return $value;
        }
        return json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    /**
     * Join fields into a CSV line with proper escaping.
     */
    private static function csvLine(array $fields): string
    {
        return implode(',', array_map([self::class, 'csvEscape'], $fields));
    }

    /**
     * Escape a CSV field value if it contains special characters.
     */
    private static function csvEscape(string $value): string
    {
        if (
            strpos($value, ',') !== false ||
            strpos($value, '"') !== false ||
            strpos($value, "\n") !== false ||
            strpos($value, "\r") !== false
        ) {
            return '"' . str_replace('"', '""', $value) . '"';
        }
        return $value;
    }

    // -----------------------------------------------------------------------
    // Internal: CSV parsing (unpack)
    // -----------------------------------------------------------------------

    /**
     * Parse CSV text back into an array of assoc arrays.
     */
    private static function fromCsv(string $text): array
    {
        $lines = self::parseCsvLines($text);
        if (count($lines) < 2) {
            return [];
        }

        $headers = $lines[0];
        $rows = [];

        for ($i = 1; $i < count($lines); $i++) {
            $csvRow = $lines[$i];

            // Skip completely empty rows
            $allEmpty = true;
            foreach ($csvRow as $c) {
                if ($c !== '') {
                    $allEmpty = false;
                    break;
                }
            }
            if ($allEmpty) {
                continue;
            }

            $flat = [];
            for ($j = 0; $j < count($headers); $j++) {
                $raw = $j < count($csvRow) ? $csvRow[$j] : '';
                $flat[$headers[$j]] = self::parseCell($raw);
            }
            $rows[] = self::unflatten($flat);
        }

        return $rows;
    }

    /**
     * Parse a single CSV cell string back into a typed PHP value.
     */
    private static function parseCell(string $raw)
    {
        if ($raw === '') {
            return null;
        }
        if ($raw === 'true') {
            return true;
        }
        if ($raw === 'false') {
            return false;
        }

        // Integer
        if (preg_match('/^-?\d+$/', $raw)) {
            return (int) $raw;
        }
        // Float
        if (preg_match('/^-?\d+\.\d+$/', $raw)) {
            return (float) $raw;
        }

        // Pipe-separated → array (but not if it looks like JSON)
        if (strpos($raw, '|') !== false && $raw[0] !== '[') {
            return array_map([self::class, 'parseCell'], explode('|', $raw));
        }

        // Try JSON decode for arrays/objects
        if ($raw[0] === '[' || $raw[0] === '{') {
            $decoded = json_decode($raw, true);
            if (json_last_error() === JSON_ERROR_NONE) {
                return $decoded;
            }
        }

        return $raw;
    }

    /**
     * Unflatten dot-notation keys back into nested arrays.
     */
    private static function unflatten(array $flat): array
    {
        $result = [];
        foreach ($flat as $key => $value) {
            $parts = explode('.', (string) $key);
            $current = &$result;
            for ($i = 0; $i < count($parts) - 1; $i++) {
                $part = $parts[$i];
                if (!isset($current[$part]) || !is_array($current[$part])) {
                    $current[$part] = [];
                }
                $current = &$current[$part];
            }
            $current[$parts[count($parts) - 1]] = $value;
            unset($current);
        }
        return $result;
    }

    /**
     * Parse raw CSV text into an array of string arrays (rows of fields).
     */
    private static function parseCsvLines(string $text): array
    {
        $lines = [];
        $current = [];
        $field = '';
        $inQuotes = false;
        $len = strlen($text);

        for ($i = 0; $i < $len; $i++) {
            $ch = $text[$i];

            if ($inQuotes) {
                if ($ch === '"') {
                    if ($i + 1 < $len && $text[$i + 1] === '"') {
                        $field .= '"';
                        $i++;
                    } else {
                        $inQuotes = false;
                    }
                } else {
                    $field .= $ch;
                }
            } else {
                if ($ch === '"') {
                    $inQuotes = true;
                } elseif ($ch === ',') {
                    $current[] = $field;
                    $field = '';
                } elseif ($ch === "\n") {
                    $current[] = $field;
                    $field = '';
                    $lines[] = $current;
                    $current = [];
                } elseif ($ch === "\r") {
                    // skip carriage return
                } else {
                    $field .= $ch;
                }
            }
        }

        $current[] = $field;
        $hasContent = false;
        foreach ($current as $c) {
            if ($c !== '') {
                $hasContent = true;
                break;
            }
        }
        if ($hasContent) {
            $lines[] = $current;
        }

        return $lines;
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    /**
     * Check if all elements in an array are primitive (scalar or null).
     */
    private static function allPrimitive(array $arr): bool
    {
        foreach ($arr as $v) {
            if ($v !== null && !is_scalar($v)) {
                return false;
            }
        }
        return true;
    }

    /**
     * Convert a primitive value to its string representation.
     */
    private static function primToStr($value): string
    {
        if ($value === null) {
            return '';
        }
        if (is_bool($value)) {
            return $value ? 'true' : 'false';
        }
        return (string) $value;
    }
}
