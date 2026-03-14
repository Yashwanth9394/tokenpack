"""Benchmark: tokenpack vs JSON vs TOON token counts using tiktoken."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from tokenpack import pack, estimate_savings

try:
    import tiktoken
    enc = tiktoken.encoding_for_model("gpt-4o")
    def count_tokens(text: str) -> int:
        return len(enc.encode(text))
except ImportError:
    print("Install tiktoken for exact token counts: pip install tiktoken")
    print("Using character count as proxy.\n")
    def count_tokens(text: str) -> int:
        return len(text)


def benchmark(label: str, data: list[dict]):
    json_text = json.dumps(data, separators=(",", ":"))
    packed_text = pack(data)

    json_tokens = count_tokens(json_text)
    packed_tokens = count_tokens(packed_text)
    savings = (1 - packed_tokens / json_tokens) * 100 if json_tokens else 0

    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(f"  Rows:           {len(data)}")
    print(f"  JSON tokens:    {json_tokens}")
    print(f"  Packed tokens:  {packed_tokens}")
    print(f"  Savings:        {savings:.1f}%")
    print(f"  Format:         {'CSV' if packed_text != json_text else 'JSON (fallback)'}")

    return json_tokens, packed_tokens


def main():
    print("=" * 60)
    print("  tokenpack Benchmark")
    print("  Tokenizer: GPT-4o (tiktoken cl100k_base)")
    print("=" * 60)

    total_json = 0
    total_packed = 0

    # 1. Simple flat data
    simple = [
        {"name": "Yash", "role": "Eng", "city": "NYC"},
        {"name": "Ali", "role": "Des", "city": "LA"},
        {"name": "Bob", "role": "PM", "city": "SF"},
    ]
    j, p = benchmark("Simple flat data (3 rows, 3 cols)", simple)
    total_json += j
    total_packed += p

    # 2. Real-world with spaces in values
    realistic = [
        {"name": "Yash P", "role": "Senior Eng", "city": "New York", "salary": 150000, "active": True},
        {"name": "Ali Khan", "role": "Designer", "city": "Los Angeles", "salary": 120000, "active": False},
        {"name": "Bob", "role": "PM", "city": "SF", "salary": None, "active": True},
        {"name": "Eve", "role": "QA Lead", "city": "Chicago", "salary": 95000, "active": True},
        {"name": "Dan Kim", "role": "Dev", "city": "Seattle", "salary": 130000, "active": False},
    ]
    j, p = benchmark("Realistic data with spaces (5 rows, 5 cols)", realistic)
    total_json += j
    total_packed += p

    # 3. Nested objects
    nested = [
        {"name": "Yash", "address": {"city": "NYC", "zip": "10001"}, "role": "Eng"},
        {"name": "Ali", "address": {"city": "LA", "zip": "90001"}, "role": "Des"},
        {"name": "Bob", "address": {"city": "SF", "zip": "94101"}, "role": "PM"},
    ]
    j, p = benchmark("Nested objects - address.city flattening (3 rows)", nested)
    total_json += j
    total_packed += p

    # 4. With arrays
    with_arrays = [
        {"name": "Yash", "skills": ["Python", "TypeScript", "Java"], "level": "Senior"},
        {"name": "Ali", "skills": ["Figma", "CSS"], "level": "Mid"},
        {"name": "Bob", "skills": ["Jira", "Confluence", "Slack"], "level": "Lead"},
    ]
    j, p = benchmark("Array values - pipe-joined skills (3 rows)", with_arrays)
    total_json += j
    total_packed += p

    # 5. Large dataset
    large = [{"id": i, "name": f"User{i}", "role": "Eng", "dept": "Backend", "salary": 100000 + i * 1000}
             for i in range(50)]
    j, p = benchmark("Large dataset (50 rows, 5 cols)", large)
    total_json += j
    total_packed += p

    # 6. Very large dataset
    very_large = [{"id": i, "name": f"User{i}", "email": f"user{i}@company.com", "role": "Eng",
                   "dept": "Backend", "salary": 100000 + i * 1000, "active": i % 3 != 0}
                  for i in range(100)]
    j, p = benchmark("Very large dataset (100 rows, 7 cols)", very_large)
    total_json += j
    total_packed += p

    # Summary
    total_savings = (1 - total_packed / total_json) * 100
    print(f"\n{'=' * 60}")
    print(f"  TOTAL ACROSS ALL BENCHMARKS")
    print(f"{'=' * 60}")
    print(f"  Total JSON tokens:    {total_json}")
    print(f"  Total Packed tokens:  {total_packed}")
    print(f"  Total Savings:        {total_savings:.1f}%")
    print(f"  Tokens saved:         {total_json - total_packed}")
    print()


if __name__ == "__main__":
    main()
