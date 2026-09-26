"""AI extraction: natural language → structured data."""

from __future__ import annotations

from zfrog.ai.client import complete_structured, complete, is_available
from zfrog.ai.schemas import ExtractionResult, ExtractedItem, PageAnalysis, SelectorSuggestion


async def extract_from_text(
    text: str,
    query: str,
    model: str | None = None,
) -> ExtractionResult:
    """Extract structured data from text based on a natural language query.

    Args:
        text: The page text content.
        query: What to extract (e.g., "prices and product names").
        model: Optional model override.

    Returns:
        ExtractionResult with extracted items.
    """
    if not is_available():
        return ExtractionResult(
            items=[],
            summary="AI module not available. Install litellm: pip install litellm",
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a data extraction assistant. Extract the requested information "
                "from the provided text. Return structured data with labels, values, and "
                "confidence scores. Be precise and only extract what is clearly present."
            ),
        },
        {
            "role": "user",
            "content": f"Text content:\n\n{text[:8000]}\n\n---\nExtract: {query}",
        },
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=ExtractionResult,
            model=model,
            temperature=0.0,
        )
        return result
    except Exception as e:
        # Fallback to unstructured completion
        response = await complete(
            messages=messages,
            model=model,
            temperature=0.0,
        )
        return ExtractionResult(
            items=[ExtractedItem(label="raw_response", value=response, confidence=0.5)],
            summary=f"Extraction returned raw text (parse error: {e})",
        )


async def analyze_page(
    text: str,
    url: str = "",
    model: str | None = None,
) -> PageAnalysis:
    """Analyze a page's content structure using AI.

    Args:
        text: The page text content.
        url: Original URL for context.
        model: Optional model override.

    Returns:
        PageAnalysis with structure analysis.
    """
    if not is_available():
        return PageAnalysis(content_type="unknown")

    messages = [
        {
            "role": "system",
            "content": (
                "Analyze the page structure. Identify: content type (article, product, listing, "
                "form, app, other), the main content area, data fields present, and suggest "
                "CSS/XPath selectors for extracting each field."
            ),
        },
        {
            "role": "user",
            "content": f"URL: {url}\n\nContent:\n\n{text[:6000]}",
        },
    ]

    try:
        result = await complete_structured(
            messages=messages,
            response_model=PageAnalysis,
            model=model,
            temperature=0.0,
        )
        return result
    except Exception:
        return PageAnalysis(content_type="unknown")


async def generate_selectors(
    html_snippet: str,
    target_fields: list[str],
    model: str | None = None,
) -> list[SelectorSuggestion]:
    """Generate CSS/XPath selectors for target fields from an HTML snippet.

    Args:
        html_snippet: HTML snippet to analyze.
        target_fields: List of field names to find selectors for.
        model: Optional model override.

    Returns:
        List of SelectorSuggestion with selectors and confidence.
    """
    if not is_available():
        return []

    messages = [
        {
            "role": "system",
            "content": (
                "Given an HTML snippet and target field names, suggest the best CSS or XPath "
                "selectors to extract each field. Return selectors with type and confidence."
            ),
        },
        {
            "role": "user",
            "content": (
                f"HTML:\n{html_snippet[:4000]}\n\n"
                f"Target fields: {', '.join(target_fields)}"
            ),
        },
    ]

    try:
        # Use a list response via instructor
        import instructor
        import litellm

        from zfrog.ai.client import get_model

        client = instructor.from_litellm(litellm.acompletion)
        response = await client.chat.completions.create(
            model=model or get_model(),
            messages=messages,
            response_model=SelectorSuggestion,
            temperature=0.0,
        )
        return [response] if isinstance(response, SelectorSuggestion) else response
    except Exception:
        return []
