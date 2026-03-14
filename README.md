# promptpack

Pack JSON data into token-efficient formats for LLM prompts. **Save 37-47% on input tokens** with zero learning curve.

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
pip install promptpack          # Python
npm install promptpack          # Node.js / TypeScript
gem install promptpack          # Ruby
composer require yashwanth/promptpack  # PHP
go get github.com/Yashwanth9394/promptpack/go  # Go
cargo add promptpack            # Rust
dotnet add package PromptPack   # C# / .NET
```

```xml
<!-- Java (Maven) -->
<dependency>
    <groupId>com.promptpack</groupId>
    <artifactId>promptpack</artifactId>
    <version>0.1.0</version>
</dependency>
```

```kotlin
// Kotlin (Gradle)
implementation("com.promptpack:promptpack:0.1.0")
```

```swift
// Swift (Package.swift)
.package(url: "https://github.com/Yashwanth9394/promptpack", from: "0.1.0")
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

// 1-line integration with any LLM SDK:
var response = PromptPack.withPacked("Analyze:", json, content ->
    client.chat().completions().create(
        ChatCompletionCreateParams.builder()
            .model(ChatModel.GPT_4O)
            .addUserMessage(content)
            .build()
    )
);
```

### Go

```go
import "github.com/Yashwanth9394/promptpack/go"

data := []map[string]interface{}{
    {"name": "Yash", "role": "Eng"},
    {"name": "Ali", "role": "Des"},
}

packed := promptpack.Pack(data)          // JSON → CSV
original := promptpack.Unpack(packed)    // CSV → JSON
prompt := promptpack.PackForPrompt("Analyze:", data)
```

### Rust

```rust
use promptpack::{pack, unpack};
use serde_json::json;

let data = json!([{"name": "Yash", "role": "Eng"}, {"name": "Ali", "role": "Des"}]);

let packed = pack(&data);               // JSON → CSV
let original = unpack(&packed);          // CSV → JSON
```

### C# / .NET

```csharp
using PromptPack;

string json = "[{\"name\":\"Yash\",\"role\":\"Eng\"},{\"name\":\"Ali\",\"role\":\"Des\"}]";

string packed = PromptPack.Pack(json);
JsonElement original = PromptPack.Unpack(packed);
```

### Ruby

```ruby
require 'promptpack'

data = [{ "name" => "Yash", "role" => "Eng" }, { "name" => "Ali", "role" => "Des" }]

packed = PromptPack.pack(data)           # JSON → CSV
original = PromptPack.unpack(packed)     # CSV → JSON
```

### PHP

```php
use PromptPack\PromptPack;

$data = [["name" => "Yash", "role" => "Eng"], ["name" => "Ali", "role" => "Des"]];

$packed = PromptPack::pack($data);       // JSON → CSV
$original = PromptPack::unpack($packed); // CSV → JSON
```

### Kotlin

```kotlin
import com.promptpack.PromptPack

val packed = PromptPack.pack("""[{"name":"Yash","role":"Eng"},{"name":"Ali","role":"Des"}]""")
val original = PromptPack.unpack(packed)
```

### Swift

```swift
import PromptPack

let data: [[String: Any]] = [["name": "Yash", "role": "Eng"], ["name": "Ali", "role": "Des"]]

let packed = PromptPack.pack(data)       // JSON → CSV
let original = PromptPack.unpack(packed) // CSV → JSON
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
| Array of objects `[{}, {}]` | Pure CSV | 39-47% |
| Nested objects `{address: {city}}` | Dot-flatten: `address.city` | 44-47% |
| Array of primitives `{skills: ["A","B"]}` | Pipe-join: `A\|B` | 37-47% |
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
| Keys with dots (`"config.name"`) | Escaped dot-notation (`config\.name`) |
| Nested objects | Dot-notation flattening |
| Arrays of primitives | Pipe-joined with escaping (`Python\|Java`) |
| Unicode / emoji | Pass-through |
| Non-uniform objects | Superset headers + empty cells |
| Deeply nested (3+ levels) | Recursive dot-flatten (`a.b.c`) |
| Unparseable data | Falls back to JSON (never corrupts) |

## Known Limitations

`pack()` outputs **pure standard CSV** — the LLM reads it perfectly. These limitations only affect `unpack()` (reversing CSV back to JSON):

| Limitation | Impact | Fix |
|-----------|--------|-----|
| Numeric strings (`"10001"`) unpack as numbers | Low — LLMs understand both | Use `pack(data, typed=True)` for safe round-trip |
| String `"true"`/`"false"` unpack as booleans | Low — LLMs understand both | Use `pack(data, typed=True)` |
| String with `\|` unpacks as array | Low — rare in real data | Use `pack(data, typed=True)` |
| Empty string vs null indistinguishable | Low — both become empty CSV cell | Use `pack(data, typed=True)` (uses `\N` sentinel) |
| Nested arrays of objects | Falls back to JSON-in-cell | Still works, just less savings for that column |

## API Reference

### Python

```python
pack(data)                           # JSON → pure CSV (for LLM input)
pack(data, typed=True)               # JSON → CSV + type hints (for safe round-trip)
unpack(text)                         # CSV or JSON → Python objects
pack_for_prompt(msg, data)           # Combine message + packed data
estimate_savings(data)               # Get savings estimate dict

# 1-line SDK wrappers
from promptpack.wrappers import openai_pack, anthropic_pack
openai_pack(client, msg, data)       # Auto-pack + send to OpenAI
anthropic_pack(client, msg, data)    # Auto-pack + send to Anthropic
```

### TypeScript

```typescript
pack(data: unknown, typed?: boolean): string  // typed=false → pure CSV, typed=true → with type hints
unpack(text: string): unknown
packForPrompt(message: string, data: unknown): string
estimateSavings(data: unknown): { jsonChars, packedChars, charSavingsPct, formatUsed }

// 1-line SDK wrappers
openaiPack(client, message, data): Promise<unknown>
anthropicPack(client, message, data): Promise<unknown>
```

### Java

```java
PromptPack.pack(String json): String
PromptPack.pack(JsonElement element): String
PromptPack.unpack(String text): JsonArray
PromptPack.packForPrompt(String message, String json): String
PromptPack.withPacked(String message, String json, Function<String, T> caller): T  // 1-line SDK wrapper
```

## Supported Languages

| Language | Package Manager | Directory |
|----------|----------------|-----------|
| Python | pip | `python/` |
| TypeScript | npm | `typescript/` |
| Java | Maven | `java/` |
| Go | go modules | `go/` |
| Rust | cargo | `rust/` |
| C# / .NET | NuGet | `csharp/` |
| Ruby | gem | `ruby/` |
| PHP | composer | `php/` |
| Kotlin | Gradle | `kotlin/` |
| Swift | SwiftPM | `swift/` |

## Project Structure

```
promptpack/
├── python/                 # pip install promptpack
│   ├── promptpack/
│   │   ├── core.py         # Core pack/unpack logic
│   │   └── wrappers.py     # OpenAI/Anthropic 1-line wrappers
│   └── tests/test_core.py  # 37 tests covering all edge cases
├── typescript/             # npm install promptpack
│   └── src/index.ts
├── java/                   # Maven
│   └── src/.../PromptPack.java
├── go/                     # go get
│   ├── promptpack.go
│   └── promptpack_test.go  # 16 tests
├── rust/                   # cargo add promptpack
│   └── src/lib.rs          # 12 tests
├── csharp/                 # dotnet add package PromptPack
│   └── PromptPack.cs
├── ruby/                   # gem install promptpack
│   └── lib/promptpack.rb
├── php/                    # composer require
│   └── src/PromptPack.php
├── kotlin/                 # Gradle
│   └── src/.../PromptPack.kt
├── swift/                  # SwiftPM
│   └── Sources/PromptPack/PromptPack.swift
├── benchmarks/
│   └── benchmark.py
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
