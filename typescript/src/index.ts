/**
 * promptpack - Pack JSON data into token-efficient CSV for LLM prompts.
 *
 * Usage:
 *   import { pack, unpack, packForPrompt } from 'promptpack';
 *
 *   const csv = pack(myJsonData);              // JSON → pure CSV (fewer tokens)
 *   const json = unpack(csv);                  // CSV → JSON (back to original)
 *   const typed = pack(myJsonData, true);      // CSV + type hints (safe round-trip)
 *   const prompt = packForPrompt("Analyze:", data);
 */

// Null sentinel for typed mode
const NULL_SENTINEL = "\\N";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Convert JSON data to the most token-efficient text format.
 * Arrays of similar objects → CSV with dot-flattened headers.
 * Everything else → compact JSON.
 *
 * @param typed If true, include #types row and \N null markers for safe round-tripping.
 */
export function pack(data: unknown, typed: boolean = false): string {
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return data as string;
    }
  }

  if (Array.isArray(data) && data.length >= 2 && isPackableArray(data)) {
    return toCsv(data, typed);
  }

  return JSON.stringify(data);
}

/**
 * Convert packed text back to JSON-compatible objects.
 * Detects CSV vs JSON automatically. Detects #types row if present.
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

/**
 * 1-line wrapper for OpenAI SDK calls with auto-packing.
 */
export async function openaiPack(
  client: { chat: { completions: { create: (opts: Record<string, unknown>) => Promise<unknown> } } },
  message: string,
  data: unknown,
  model: string = "gpt-4o",
  opts: Record<string, unknown> = {},
): Promise<unknown> {
  const packed = pack(data);
  const content = message ? `${message}\n${packed}` : packed;
  return client.chat.completions.create({
    model,
    messages: [{ role: "user", content }],
    ...opts,
  });
}

/**
 * 1-line wrapper for Anthropic SDK calls with auto-packing.
 */
export async function anthropicPack(
  client: { messages: { create: (opts: Record<string, unknown>) => Promise<unknown> } },
  message: string,
  data: unknown,
  model: string = "claude-sonnet-4-20250514",
  maxTokens: number = 4096,
  opts: Record<string, unknown> = {},
): Promise<unknown> {
  const packed = pack(data);
  const content = message ? `${message}\n${packed}` : packed;
  return client.messages.create({
    model,
    max_tokens: maxTokens,
    messages: [{ role: "user", content }],
    ...opts,
  });
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
// Internal: key escaping for dot-notation
// ---------------------------------------------------------------------------

function escapeKey(key: string): string {
  return key.replace(/\\/g, "\\\\").replace(/\./g, "\\.");
}

function splitDottedKey(key: string): string[] {
  const parts: string[] = [];
  let current: string[] = [];
  let i = 0;
  while (i < key.length) {
    if (key[i] === "\\" && i + 1 < key.length) {
      current.push(key[i + 1]);
      i += 2;
    } else if (key[i] === ".") {
      parts.push(current.join(""));
      current = [];
      i += 1;
    } else {
      current.push(key[i]);
      i += 1;
    }
  }
  parts.push(current.join(""));
  return parts;
}

// ---------------------------------------------------------------------------
// Internal: pipe escaping for array values
// ---------------------------------------------------------------------------

function escapePipe(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
}

function splitPipeJoined(raw: string): string[] {
  const parts: string[] = [];
  let current: string[] = [];
  let i = 0;
  while (i < raw.length) {
    if (raw[i] === "\\" && i + 1 < raw.length) {
      current.push(raw[i + 1]);
      i += 2;
    } else if (raw[i] === "|") {
      parts.push(current.join(""));
      current = [];
      i += 1;
    } else {
      current.push(raw[i]);
      i += 1;
    }
  }
  parts.push(current.join(""));
  return parts;
}

// ---------------------------------------------------------------------------
// Internal: pipe-joined marker
// ---------------------------------------------------------------------------

const PIPE_JOINED = Symbol("PipeJoined");

interface PipeJoinedValue {
  value: string;
  [PIPE_JOINED]: true;
}

function makePipeJoined(value: string): PipeJoinedValue {
  return { value, [PIPE_JOINED]: true };
}

function isPipeJoined(v: unknown): v is PipeJoinedValue {
  return typeof v === "object" && v !== null && PIPE_JOINED in v;
}

// ---------------------------------------------------------------------------
// Internal: CSV writing
// ---------------------------------------------------------------------------

function flattenValue(value: unknown, prefix: string): Record<string, unknown> {
  if (value !== null && typeof value === "object" && !Array.isArray(value) && !isPipeJoined(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const escapedK = escapeKey(k);
      const fullKey = prefix ? `${prefix}.${escapedK}` : escapedK;
      Object.assign(out, flattenValue(v, fullKey));
    }
    return out;
  }

  if (Array.isArray(value)) {
    if (value.every(isPrimitive)) {
      return { [prefix]: makePipeJoined(value.map((v) => escapePipe(primToStr(v))).join("|")) };
    }
    return { [prefix]: JSON.stringify(value) };
  }

  return { [prefix]: value };
}

function flattenRow(row: Record<string, unknown>): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    const escapedKey = escapeKey(key);
    Object.assign(flat, flattenValue(value, escapedKey));
  }
  return flat;
}

function detectColumnType(flatRows: Record<string, unknown>[], header: string): string {
  const vals: unknown[] = [];
  for (const row of flatRows) {
    if (header in row && row[header] !== null && row[header] !== undefined) {
      vals.push(row[header]);
    }
  }
  if (vals.length === 0) return "x";

  if (vals.some(isPipeJoined)) return "a";

  const typesSeen = new Set<string>();
  for (const v of vals) {
    if (typeof v === "boolean") {
      typesSeen.add("b");
    } else if (typeof v === "number") {
      typesSeen.add("n");
    } else if (typeof v === "string") {
      if (v && (v[0] === "{" || v[0] === "[")) {
        try {
          JSON.parse(v);
          typesSeen.add("j");
          continue;
        } catch {
          // not JSON
        }
      }
      typesSeen.add("s");
    } else {
      typesSeen.add("x");
    }
  }

  if (typesSeen.size === 1) return [...typesSeen][0];
  if (typesSeen.has("s")) return "s";
  return "x";
}

function toCsv(data: Record<string, unknown>[], typed: boolean): string {
  const flatRows = data.map(flattenRow);

  const seen = new Map<string, null>();
  for (const row of flatRows) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) seen.set(k, null);
    }
  }
  const headers = [...seen.keys()];

  const lines: string[] = [csvLine(headers)];

  if (typed) {
    const colTypes = headers.map((h) => detectColumnType(flatRows, h));
    lines.push("#" + colTypes.join(","));
  }

  for (const row of flatRows) {
    lines.push(csvLine(headers.map((h) => formatCell(row[h], typed))));
  }
  return lines.join("\n");
}

function formatCell(value: unknown, typed: boolean = false): string {
  if (value === null || value === undefined) return typed ? NULL_SENTINEL : "";
  if (isPipeJoined(value)) return value.value;
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

  let colTypes: string[] | null = null;
  let typedMode = false;
  let dataStartIdx = 1;

  if (lines.length > 1 && lines[1].length > 0 && lines[1][0].startsWith("#")) {
    colTypes = [lines[1][0].substring(1), ...lines[1].slice(1)];
    typedMode = true;
    dataStartIdx = 2;
  }

  const rows: Record<string, unknown>[] = [];

  for (let i = dataStartIdx; i < lines.length; i++) {
    const csvRow = lines[i];
    if (csvRow.every((c) => c === "")) continue;

    const flat: Record<string, unknown> = {};
    for (let j = 0; j < headers.length; j++) {
      const raw = j < csvRow.length ? csvRow[j] : "";
      const t = colTypes && j < colTypes.length ? colTypes[j] : null;
      flat[headers[j]] = parseCell(raw, t, typedMode);
    }
    rows.push(unflatten(flat));
  }

  return rows;
}

function parseCell(raw: string, typeHint: string | null = null, typedMode: boolean = false): unknown {
  // Null sentinel (typed mode)
  if (raw === NULL_SENTINEL && typedMode) return null;

  if (raw === "") {
    return typedMode ? "" : null;
  }

  // Type-hinted parsing
  if (typeHint === "s") return raw;
  if (typeHint === "b") return raw === "true";
  if (typeHint === "n") {
    if (raw.includes(".")) return parseFloat(raw);
    const n = parseInt(raw, 10);
    return isNaN(n) ? raw : n;
  }
  if (typeHint === "a") {
    return splitPipeJoined(raw).map(parseArrayElement);
  }
  if (typeHint === "j") {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }

  // No type hint — auto-detect
  if (raw === "true") return true;
  if (raw === "false") return false;

  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);

  if (raw.includes("|") && !raw.startsWith("[")) {
    return raw.split("|").map(parseArrayElement);
  }

  if (raw.startsWith("[") || raw.startsWith("{")) {
    try {
      return JSON.parse(raw);
    } catch {
      // not JSON
    }
  }

  return raw;
}

function parseArrayElement(raw: string): unknown {
  if (raw === "") return null;
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);
  return raw;
}

function unflatten(flat: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(flat)) {
    const parts = splitDottedKey(key);
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
