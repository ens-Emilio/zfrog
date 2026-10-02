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


def _litellm():
    """Import LiteLLM, with its provider banner turned off.

    When a call fails to resolve a model, LiteLLM prints a provider list and a support
    banner to stderr before raising. That is library advertising, not our output, and it
    lands in the middle of commands whose real answer is the error message below it. The
    switch is the module attribute — an env var does not control it.

    Imported lazily, as the call sites already did: LiteLLM is heavy, and this module is
    imported by code paths that never make a call.
    """
    import litellm

    litellm.suppress_debug_info = True
    return litellm


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
    litellm = _litellm()

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

    litellm = _litellm()

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
    litellm = _litellm()

    model = model or get_embedding_model()

    response = await litellm.aembedding(
        model=model,
        input=texts,
    )

    return [item["embedding"] for item in response.data]


def is_available() -> bool:
    """Whether LiteLLM is importable.

    This is a *dependency* check, not a readiness check: it is true on every install,
    including one where no model was ever started. Code that is about to make a call
    must also ask :func:`model_configured` (or :func:`embedding_configured`), or it
    reaches a default model the user never installed and reports a provider error for a
    feature they did not ask for.
    """
    try:
        _litellm()
        return True
    except ImportError:
        return False


def model_configured() -> bool:
    """Whether a chat model was pointed at explicitly (``ZFROG_AI_MODEL``).

    The default is ``ollama/qwen2.5``; treating that default as "configured" is what
    makes an unconfigured install print a provider error on a job that only wanted the
    heuristic.
    """
    return bool(os.environ.get("ZFROG_AI_MODEL"))


def embedding_configured() -> bool:
    """Whether an embedding model was pointed at explicitly (``ZFROG_AI_EMBEDDING``)."""
    return bool(os.environ.get("ZFROG_AI_EMBEDDING"))


def can_call() -> bool:
    """Whether a chat completion has a chance of working.

    One predicate for the two conditions, so callers have one seam to stub and one
    thing to check: litellm must be importable *and* a model must have been named.
    """
    return is_available() and model_configured()


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
