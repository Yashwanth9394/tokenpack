"""One-line wrappers for OpenAI and Anthropic SDK calls with auto-packing."""

from promptpack.core import pack
from typing import Any


def openai_pack(client: Any, message: str, data: Any, model: str = "gpt-4o", **kwargs) -> Any:
    """Send a message + data to OpenAI with auto-packing.

    Usage:
        from openai import OpenAI
        from promptpack.wrappers import openai_pack

        client = OpenAI()
        response = openai_pack(client, "Analyze this:", my_data)
        print(response.choices[0].message.content)
    """
    packed = pack(data)
    content = f"{message}\n{packed}" if message else packed
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        **kwargs,
    )


def anthropic_pack(client: Any, message: str, data: Any, model: str = "claude-sonnet-4-20250514",
                   max_tokens: int = 4096, **kwargs) -> Any:
    """Send a message + data to Anthropic with auto-packing.

    Usage:
        import anthropic
        from promptpack.wrappers import anthropic_pack

        client = anthropic.Anthropic()
        response = anthropic_pack(client, "Analyze this:", my_data)
        print(response.content[0].text)
    """
    packed = pack(data)
    content = f"{message}\n{packed}" if message else packed
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        **kwargs,
    )
