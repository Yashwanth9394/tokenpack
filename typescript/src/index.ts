/**
 * promptpack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * Usage:
 *   import { pack, unpack, packForPrompt } from 'promptpack';
 *
 *   const csv = pack(myJsonData);          // JSON → CSV (fewer tokens)
 *   const json = unpack(csv);              // CSV → JSON (back to original)
 *   const prompt = packForPrompt("Analyze:", data);
 */

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Convert JSON data to the most token-efficient text format.
 * Arrays of similar objects → CSV with dot-flattened headers.
 * Everything else → compact JSON.
 */
export function pack(data: unknown): string {
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return data as string;
    }
  }

  if (Array.isArray(data) && data.length >= 2 && isPackableArray(data)) {
    return toCsv(data);
  }

  return JSON.stringify(data);
}

/**
 * Convert packed text back to JSON-compatible objects.
 * Detects CSV vs JSON automatically.
 */
export function unpack(text: string): unknown {
  text = text.trim();
  if (!text) return [];

  if (text[0] === "{" || text[0] === "[") {
    return JSON.parse(text);
  }

  return fromCsv(text);
}

/**
 * Combine a user message with packed data.
 */
export function packForPrompt(message: string, data: unknown): string {
  return `${message}\n${pack(data)}`;
}

/**
 * Estimate character savings (proxy for token savings).
 */
export function estimateSavings(data: unknown): {
  jsonChars: number;
  packedChars: number;
  charSavingsPct: number;
  formatUsed: string;
} {
  const jsonText = JSON.stringify(data);
  const packedText = pack(data);
  const savings =
    jsonText.length > 0
      ? (1 - packedText.length / jsonText.length) * 100
      : 0;
  return {
    jsonChars: jsonText.length,
    packedChars: packedText.length,
    charSavingsPct: Math.round(savings * 10) / 10,
    formatUsed: packedText !== jsonText ? "csv" : "json",
  };
}

// ---------------------------------------------------------------------------
// Internal: shape detection
// ---------------------------------------------------------------------------

function isPackableArray(data: unknown[]): boolean {
  if (!data.every((item) => typeof item === "object" && item !== null && !Array.isArray(item))) {
    return false;
  }

  const dicts = data as Record<string, unknown>[];
  const allKeys = new Set<string>();
  for (const item of dicts) {
    for (const k of Object.keys(item)) allKeys.add(k);
  }
  if (allKeys.size === 0) return false;

  // Must share at least some keys
  let sharedKeys = new Set(Object.keys(dicts[0]));
  for (const item of dicts) {
    const itemKeys = new Set(Object.keys(item));
    sharedKeys = new Set([...sharedKeys].filter((k) => itemKeys.has(k)));
  }
  if (sharedKeys.size === 0) return false;

  const threshold = Math.max(allKeys.size * 0.3, 1);
  for (const item of dicts) {
    if (Object.keys(item).length < threshold) return false;
  }

  return true;
}

// ---------------------------------------------------------------------------
// Internal: CSV writing
// ---------------------------------------------------------------------------

function flattenValue(value: unknown, prefix: string): Record<string, unknown> {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const fullKey = prefix ? `${prefix}.${k}` : k;
      Object.assign(out, flattenValue(v, fullKey));
    }
    return out;
  }

  if (Array.isArray(value)) {
    if (value.every(isPrimitive)) {
      return { [prefix]: value.map(primToStr).join("|") };
    }
    return { [prefix]: JSON.stringify(value) };
  }

  return { [prefix]: value };
}

function flattenRow(row: Record<string, unknown>): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    Object.assign(flat, flattenValue(value, key));
  }
  return flat;
}

function toCsv(data: Record<string, unknown>[]): string {
  const flatRows = data.map(flattenRow);

  // Ordered superset of keys
  const seen = new Map<string, null>();
  for (const row of flatRows) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) seen.set(k, null);
    }
  }
  const headers = [...seen.keys()];

  const lines: string[] = [csvLine(headers)];
  for (const row of flatRows) {
    lines.push(csvLine(headers.map((h) => formatCell(row[h]))));
  }
  return lines.join("\n");
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function csvLine(fields: string[]): string {
  return fields.map(csvEscape).join(",");
}

function csvEscape(value: string): string {
  if (
    value.includes(",") ||
    value.includes('"') ||
    value.includes("\n") ||
    value.includes("\r")
  ) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

// ---------------------------------------------------------------------------
// Internal: CSV parsing (unpack)
// ---------------------------------------------------------------------------

function fromCsv(text: string): Record<string, unknown>[] {
  const lines = parseCsvLines(text);
  if (lines.length < 2) return [];

  const headers = lines[0];
  const rows: Record<string, unknown>[] = [];

  for (let i = 1; i < lines.length; i++) {
    const csvRow = lines[i];
    if (csvRow.every((c) => c === "")) continue;

    const flat: Record<string, unknown> = {};
    for (let j = 0; j < headers.length; j++) {
      const raw = j < csvRow.length ? csvRow[j] : "";
      flat[headers[j]] = parseCell(raw);
    }
    rows.push(unflatten(flat));
  }

  return rows;
}

function parseCell(raw: string): unknown {
  if (raw === "") return null;
  if (raw === "true") return true;
  if (raw === "false") return false;

  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);

  if (raw.includes("|") && !raw.startsWith("[")) {
    return raw.split("|").map(parseCell);
  }

  if (raw.startsWith("[") || raw.startsWith("{")) {
    try {
      return JSON.parse(raw);
    } catch {
      // not JSON, treat as string
    }
  }

  return raw;
}

function unflatten(flat: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(flat)) {
    const parts = key.split(".");
    let current: Record<string, unknown> = result;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!(parts[i] in current) || typeof current[parts[i]] !== "object") {
        current[parts[i]] = {};
      }
      current = current[parts[i]] as Record<string, unknown>;
    }
    current[parts[parts.length - 1]] = value;
  }
  return result;
}

function parseCsvLines(text: string): string[][] {
  const lines: string[][] = [];
  let current: string[] = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ",") {
        current.push(field);
        field = "";
      } else if (ch === "\n") {
        current.push(field);
        field = "";
        lines.push(current);
        current = [];
      } else if (ch === "\r") {
        // skip
      } else {
        field += ch;
      }
    }
  }

  current.push(field);
  if (current.some((c) => c !== "")) {
    lines.push(current);
  }

  return lines;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function primToStr(value: unknown): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}
