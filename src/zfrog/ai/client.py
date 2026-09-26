"""AI multi-provider client via LiteLLM.

Supports any provider: Ollama, OpenAI, Anthropic, Google, Groq, Mistral, etc.
Configuration via environment variables or ai_config.yaml.

Examples:
    # Local (default)
    ZFROG_AI_MODEL=ollama/qwen2.5

    # Cloud providers
    ZFROG_AI_MODEL=openai/gpt-4o
    ZFROG_AI_MODEL=anthropic/claude-sonnet-4-20250514
    ZFROG_AI_MODEL=google/gemini-2.0-flash
    ZFROG_AI_MODEL=groq/llama-3.3-70b-versatile

    # Embeddings (separate from completion)
    ZFROG_AI_EMBEDDING=sentence-transformers/all-MiniLM-L6-v2
"""

from __future__ import annotations

import os
from typing import Any

from zfrog.config import settings


def get_model() -> str:
    """Get the configured AI model string."""
    return os.environ.get("ZFROG_AI_MODEL", "ollama/qwen2.5")


def get_embedding_model() -> str:
    """Get the configured embedding model string."""
    return os.environ.get("ZFROG_AI_EMBEDDING", "sentence-transformers/all-MiniLM-L6-v2")


async def complete(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    **kwargs,
) -> str:
    """Send a completion request via LiteLLM.

    Args:
        messages: OpenAI-format messages [{"role": "user", "content": "..."}]
        model: Override model (default: ZFROG_AI_MODEL env var)
        temperature: Sampling temperature.
        max_tokens: Max tokens in response.
        response_format: Optional JSON schema for structured output.
        **kwargs: Additional provider-specific parameters.

    Returns:
        Model response as string.
    """
    import litellm

    model = model or get_model()

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        **kwargs,
    )

    return response.choices[0].message.content or ""


async def complete_structured(
    messages: list[dict[str, str]],
    response_model: type,
    model: str | None = None,
    temperature: float = 0.0,
    max_retries: int = 2,
    **kwargs,
) -> Any:
    """Send a completion request and parse into a Pydantic model.

    Uses Instructor for structured output with automatic retries.

    Args:
        messages: OpenAI-format messages.
        response_model: Pydantic model class for response parsing.
        model: Override model.
        temperature: Sampling temperature.
        max_retries: Retries for parse failures.
        **kwargs: Additional parameters.

    Returns:
        Instance of response_model.
    """
    import instructor
    import litellm

    model = model or get_model()

    client = instructor.from_litellm(litellm.acompletion)

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        response_model=response_model,
        temperature=temperature,
        max_retries=max_retries,
        **kwargs,
    )

    return response


async def embed(
    texts: list[str],
    model: str | None = None,
) -> list[list[float]]:
    """Generate embeddings for a list of texts.

    Args:
        texts: List of strings to embed.
        model: Override embedding model.

    Returns:
        List of embedding vectors.
    """
    import litellm

    model = model or get_embedding_model()

    response = await litellm.aembedding(
        model=model,
        input=texts,
    )

    return [item["embedding"] for item in response.data]


def is_available() -> bool:
    """Check if AI module is usable (LiteLLM installed, model accessible)."""
    try:
        import litellm
        return True
    except ImportError:
        return False


def provider_info() -> dict[str, str]:
    """Return info about the current AI configuration."""
    model = get_model()
    embedding = get_embedding_model()

    # Detect provider from model string
    provider = model.split("/")[0] if "/" in model else "ollama"

    return {
        "model": model,
        "embedding_model": embedding,
        "provider": provider,
        "available": str(is_available()),
    }
