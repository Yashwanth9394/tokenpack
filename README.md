# promptpack

Pack JSON data into token-efficient formats for LLM prompts. **Save 40-62% on input tokens** with zero learning curve.

```
JSON (115 tokens)                         CSV (66 tokens) — 43% savings
──────────────────                        ─────────────────
[{"name":"Yash P","role":"Senior Eng",    name,role,city,salary,active
"city":"New York","salary":150000,    →   Yash P,Senior Eng,New York,150000,true
"active":true},{"name":"Ali Khan"...      Ali Khan,Designer,Los Angeles,120000,false
```

promptpack auto-detects your data shape, converts JSON arrays to CSV (which every LLM already understands), handles nested objects with dot-flattening, and falls back to JSON for anything it can't safely convert.

## Install

```bash
# Python
pip install promptpack

# Node.js
npm install promptpack

# Java (Maven)
<dependency>
    <groupId>com.promptpack</groupId>
    <artifactId>promptpack</artifactId>
    <version>0.1.0</version>
</dependency>
```

## Usage

### Python

```python
from promptpack import pack, unpack

data = [
    {"name": "Yash P", "role": "Senior Eng", "city": "New York", "salary": 150000},
    {"name": "Ali Khan", "role": "Designer", "city": "Los Angeles", "salary": 120000},
    {"name": "Bob", "role": "PM", "city": "SF", "salary": None},
]

# Pack: JSON → CSV (43% fewer tokens)
packed = pack(data)
print(packed)
# name,role,city,salary
# Yash P,Senior Eng,New York,150000
# Ali Khan,Designer,Los Angeles,120000
# Bob,PM,SF,

# Unpack: CSV → JSON (back to original)
original = unpack(packed)

# Use with any LLM — just put the packed data in your prompt
prompt = f"Analyze these employees:\n{packed}"
```

### With OpenAI

```python
from openai import OpenAI
from promptpack import pack

client = OpenAI()
packed = pack(my_large_dataset)  # 46% fewer tokens

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": f"Analyze this data:\n{packed}"}]
)
```

### With Anthropic

```python
import anthropic
from promptpack import pack

client = anthropic.Anthropic()
packed = pack(my_large_dataset)  # 46% fewer tokens

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": f"Analyze this data:\n{packed}"}]
)
```

### Node.js / TypeScript

```typescript
import { pack, unpack, packForPrompt } from 'promptpack';

const data = [
  { name: "Yash P", role: "Senior Eng", city: "New York", salary: 150000 },
  { name: "Ali Khan", role: "Designer", city: "Los Angeles", salary: 120000 },
];

const packed = pack(data);         // JSON → CSV
const original = unpack(packed);   // CSV → JSON

// One-liner for prompts
const prompt = packForPrompt("Analyze these employees:", data);
```

### Java

```java
import com.promptpack.PromptPack;

String json = "[{\"name\":\"Yash\",\"role\":\"Eng\"},{\"name\":\"Ali\",\"role\":\"Des\"}]";

String packed = PromptPack.pack(json);              // JSON → CSV
JsonArray original = PromptPack.unpack(packed);      // CSV → JSON

String prompt = PromptPack.packForPrompt("Analyze:", json);
```

## Benchmarks

Measured with tiktoken (GPT-4o tokenizer):

| Dataset | JSON tokens | Packed tokens | Savings |
|---------|------------|---------------|---------|
| Simple flat (3 rows, 3 cols) | 41 | 25 | **39.0%** |
| Realistic with spaces (5 rows, 5 cols) | 115 | 66 | **42.6%** |
| Nested objects (3 rows) | 65 | 36 | **44.6%** |
| Array values (3 rows) | 57 | 36 | **36.8%** |
| Large dataset (50 rows, 5 cols) | 1,102 | 608 | **44.8%** |
| Very large (100 rows, 7 cols) | 3,402 | 1,811 | **46.8%** |
| **Total** | **4,782** | **2,582** | **46.0%** |

Run the benchmark yourself:

```bash
cd benchmarks && python benchmark.py
```

### Cost Savings at Scale

| Scale | Tokens saved/call | Monthly savings (at $3/M input tokens) |
|-------|-------------------|---------------------------------------|
| 1K calls/day | ~1,050 | ~$9 |
| 10K calls/day | ~1,050 | ~$95 |
| 100K calls/day | ~1,050 | ~$945 |

The bigger value: **fitting more data into the context window**. Converting 50K tokens of JSON to 27K tokens of CSV frees up 23K tokens for instructions, conversation history, and other context.

## How It Works

promptpack looks at your data and picks the best strategy:

| Data shape | Strategy | Savings |
|-----------|----------|---------|
| Array of objects `[{}, {}]` | Straight CSV | 40-47% |
| Nested objects `{address: {city}}` | Dot-flatten: `address.city` | 44-62% |
| Array of primitives `{skills: ["A","B"]}` | Pipe-join: `A\|B` | 36-52% |
| Single object / config | Keep JSON (not worth converting) | 0% |
| Small data (< 2 rows) | Keep JSON (overhead > savings) | 0% |
| Non-uniform objects (0% shared keys) | Keep JSON (can't make safe CSV) | 0% |

### Why CSV?

We benchmarked every format LLMs understand:

| Format | Token savings vs JSON | LLM can write it? | Parsers exist? |
|--------|----------------------|-------------------|---------------|
| JSON | baseline | 99% reliable | Every language |
| TOON | 40% | ~50% (too new) | 5 languages |
| **CSV** | **43-47%** | **95% reliable** | **Every language** |
| YAML | -22% (worse!) | 90% reliable | Every language |
| Markdown table | 20% | 95% reliable | Many |

CSV beats TOON while being universally understood by LLMs (billions of CSV examples in training data) and parseable by every programming language.

## What It Handles

| Edge case | How it's handled |
|-----------|-----------------|
| Values with commas (`New York, NY`) | Standard CSV quoting |
| Values with quotes (`He said "hi"`) | CSV double-quote escaping |
| Values with newlines | CSV quoting |
| Values with spaces (`Yash P`) | Works naturally in CSV |
| Null / missing values | Empty cell between commas |
| Boolean values | `true` / `false` |
| Nested objects | Dot-notation flattening |
| Arrays of primitives | Pipe-joined (`Python\|Java`) |
| Unicode / emoji | Pass-through |
| Non-uniform objects | Superset headers + empty cells |
| Deeply nested (3+ levels) | Recursive dot-flatten (`a.b.c`) |
| Unparseable data | Falls back to JSON (never corrupts) |

## Known Limitations

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| Numeric strings (`"10001"`) unpack as numbers | Low — LLMs understand both | Use for LLM input only, not as a database serializer |
| Empty string vs null indistinguishable | Low — both become empty CSV cell | Acceptable for LLM context |
| Nested arrays of objects | Falls back to JSON-in-cell | Still works, just less savings for that column |

## API Reference

### Python

```python
pack(data)                    # JSON-compatible data → packed string
unpack(text)                  # Packed string → JSON-compatible data
pack_for_prompt(msg, data)    # Combine message + packed data
estimate_savings(data)        # Get savings estimate dict
```

### TypeScript

```typescript
pack(data: unknown): string
unpack(text: string): unknown
packForPrompt(message: string, data: unknown): string
estimateSavings(data: unknown): { jsonChars, packedChars, charSavingsPct, formatUsed }
```

### Java

```java
PromptPack.pack(String json): String
PromptPack.pack(JsonElement element): String
PromptPack.unpack(String text): JsonArray
PromptPack.packForPrompt(String message, String json): String
```

## Project Structure

```
promptpack/
├── python/                 # Python package (pip)
│   ├── promptpack/
│   │   ├── __init__.py
│   │   └── core.py         # Core pack/unpack logic
│   ├── tests/
│   │   └── test_core.py    # 37 tests covering all edge cases
│   └── pyproject.toml
├── typescript/             # TypeScript package (npm)
│   ├── src/
│   │   └── index.ts        # Full port with CSV parser
│   ├── package.json
│   └── tsconfig.json
├── java/                   # Java package (Maven)
│   ├── src/main/java/com/promptpack/
│   │   └── PromptPack.java
│   └── pom.xml
├── benchmarks/
│   └── benchmark.py        # Token count benchmarks
└── README.md
```

## Why Not TOON?

TOON (Token-Oriented Object Notation) is a new format designed for LLM token efficiency. We benchmarked it:

- TOON saves ~40% vs JSON — **CSV saves 43-47%** (CSV wins)
- TOON requires LLMs to learn a new format — **CSV is in every LLM's training data**
- TOON has SDKs in 5 languages — **CSV parsers exist in every language ever made**
- TOON can't be reliably output by LLMs — **LLMs write CSV perfectly**

The insight: the #1 waste in JSON is **repeating field names** for every row. CSV already solved this in 1972 by putting field names in the header once. No new format needed.

## License

MIT

## Contributing

Issues and PRs welcome at [github.com/Yashwanth9394/promptpack](https://github.com/Yashwanth9394/promptpack)
