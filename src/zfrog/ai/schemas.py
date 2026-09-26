"""Pydantic schemas for AI structured output.

Used with Instructor for guaranteed JSON schema compliance.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    """A single extracted data item."""
    label: str = Field(description="Field name or key")
    value: str = Field(description="Extracted value")
    confidence: float = Field(default=1.0, ge=0, le=1, description="Confidence 0-1")


class ExtractionResult(BaseModel):
    """Result of structured extraction from a page."""
    items: list[ExtractedItem] = Field(default_factory=list)
    summary: str = Field(default="", description="One-line summary of what was extracted")
    page_title: str = Field(default="", description="Title of the page if available")


class SelectorSuggestion(BaseModel):
    """A CSS/XPath selector suggested by AI."""
    selector: str = Field(description="CSS or XPath selector")
    selector_type: str = Field(description="css or xpath")
    description: str = Field(description="What this selector matches")
    confidence: float = Field(default=0.8, ge=0, le=1)


class PageAnalysis(BaseModel):
    """AI analysis of a page's content structure."""
    content_type: str = Field(description="article, product, listing, form, app, other")
    main_content_selector: str | None = Field(default=None, description="Selector for main content")
    data_fields: list[str] = Field(default_factory=list, description="Detected data fields")
    suggestions: list[SelectorSuggestion] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Response to a natural language question about content."""
    answer: str = Field(description="Direct answer to the question")
    sources: list[str] = Field(default_factory=list, description="Where the answer came from")
    confidence: float = Field(default=0.8, ge=0, le=1)


class SummaryResult(BaseModel):
    """Structured summary of a page or site."""
    title: str = Field(default="", description="Title of the summarized content")
    summary: str = Field(default="", description="Summary in 3-5 sentences")
    key_points: list[str] = Field(default_factory=list, description="3-7 key points")


class Entity(BaseModel):
    """A named entity found in the text."""
    name: str = Field(description="Entity text as it appears")
    type: str = Field(description="person, organization, location, date, product, other")
    confidence: float = Field(default=0.8, ge=0, le=1)


class EntityResult(BaseModel):
    """Named entities extracted from a page."""
    entities: list[Entity] = Field(default_factory=list)


class TranslationResult(BaseModel):
    """Translated text."""
    text: str = Field(description="The translated text")
    source_language: str = Field(default="", description="Detected source language")
    target_language: str = Field(default="", description="Target language code")


class SentimentResult(BaseModel):
    """Emotional tone of a piece of content."""
    sentiment: str = Field(description="positive, negative or neutral")
    score: float = Field(default=0.0, ge=-1, le=1, description="-1 very negative, 1 very positive")
    rationale: str = Field(default="", description="Short justification")


class TagResult(BaseModel):
    """Topical tags for a page."""
    tags: list[str] = Field(default_factory=list, description="3-8 short topical tags")


class SignificanceResult(BaseModel):
    """Whether a change matters, judged from the actual content."""
    significant: bool = Field(default=False)
    score: float = Field(default=0.0, ge=0, le=1, description="0 irrelevant, 1 major")
    summary: str = Field(default="", description="What changed, in one sentence")
    reasons: list[str] = Field(default_factory=list)
