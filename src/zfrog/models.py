"""Core data models for Zfrog."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    PROBING = "probing"
    RUNNING = "running"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCreate(BaseModel):
    """Request to create a new extraction job."""
    
    url: HttpUrl
    mode: Literal["auto", "jump", "tongue", "mirror", "scrape", "singlepage", "extract", "analyze", "compare", "ask", "pdf", "summarize", "delta", "entities", "enrich", "translate", "sentiment", "tags", "video", "api_discovery"] = "auto"
    follow_links: bool = True
    max_depth: int = Field(default=3, ge=0, le=100)
    respect_robots: bool = True
    # Crawl budgets & politeness
    delay_ms: int = Field(default=1000, ge=0, le=60000, description="Delay between requests in ms")
    jitter_ms: int = Field(default=500, ge=0, le=5000, description="Random jitter added to delay")
    max_pages: int = Field(default=100, ge=1, le=10000, description="Maximum pages to crawl")
    max_bytes: int = Field(default=100_000_000, ge=1, description="Maximum total bytes to download")
    crawl_timeout_s: int = Field(default=600, ge=10, le=7200, description="Max crawl duration in seconds")
    # PDF mode: base name of the generated file (sanitized by the engine)
    pdf_filename: str | None = None
    # tongue mode: the CSS selector whose component is extracted
    selector: str | None = None
    # jump mode: which breakpoint the screenshot is taken at (desktop/tablet/mobile)
    token_breakpoint: str | None = None
    # Tags applied to the reference card created by a capture
    card_tags: list[str] = Field(default_factory=list)
    # Save a version (git-like history) after the crawl completes
    versioned: bool = False
    # Translate mode: target language code (defaults to settings.translation_target)
    translate_target: str | None = None
    # Organization that owns this job's data. Set by the API from the caller's
    # key, never taken from the request body; None means the shared output dir.
    org: str | None = None


class ProbeResult(BaseModel):
    """Result of URL probing/auto-detection."""
    
    url: str
    is_spa: bool = False
    has_js_rendering: bool = False
    robots_restricted: bool = False
    framework: str | None = None
    content_type: str = "text/html"
    # Capture motor the probe recommends: "playwright" (the visual capture
    # motor) for pages that need JavaScript, "static_file" (the light motor)
    # for plain pages.
    suggested_engine: str = "playwright"
    status_code: int | None = None
    final_url: str | None = None


class Job(BaseModel):
    """Active job with status tracking."""
    
    id: str
    url: str
    mode: str
    max_depth: int = 3
    status: JobStatus = JobStatus.PENDING
    probe: ProbeResult | None = None
    output_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None
    # Organization that owns this job's data, copied from the JobCreate that
    # started it. None means the shared area. The WebSocket reads it to refuse
    # streaming one workspace's events to a key from another.
    org: str | None = None


class JobResult(BaseModel):
    """Result of a completed job."""
    
    job_id: str
    output_path: str
    files_count: int
    total_size_bytes: int
    engine_used: str
    duration_seconds: float
