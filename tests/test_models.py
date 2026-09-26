"""Tests for core models."""

import pytest
from datetime import datetime
from pydantic import ValidationError

from zfrog.models import (
    JobCreate,
    JobResult,
    JobStatus,
    Job,
    ProbeResult,
)


class TestJobCreate:
    """Tests for JobCreate schema."""
    
    def test_valid_mirror_job(self):
        job = JobCreate(url="https://example.com", mode="mirror")
        assert str(job.url) == "https://example.com/"
        assert job.mode == "mirror"
        assert job.follow_links is True
        assert job.max_depth == 3
        assert job.respect_robots is True
    
    def test_valid_singlepage_job(self):
        job = JobCreate(url="http://test.org", mode="singlepage", max_depth=1)
        assert job.mode == "singlepage"
        assert job.max_depth == 1
    
    def test_invalid_url(self):
        with pytest.raises(ValidationError):
            JobCreate(url="not-a-url")
    
    def test_invalid_mode(self):
        with pytest.raises(ValidationError):
            JobCreate(url="https://example.com", mode="invalid")
    
    def test_depth_bounds(self):
        with pytest.raises(ValidationError):
            JobCreate(url="https://example.com", max_depth=-1)
        with pytest.raises(ValidationError):
            JobCreate(url="https://example.com", max_depth=101)


class TestProbeResult:
    """Tests for ProbeResult schema."""
    
    def test_default_values(self):
        probe = ProbeResult(url="https://example.com")
        assert probe.is_spa is False
        assert probe.has_js_rendering is False
        assert probe.robots_restricted is False
        assert probe.framework is None
        assert probe.content_type == "text/html"
    
    def test_spa_detection(self):
        probe = ProbeResult(
            url="https://nextjs-app.com",
            is_spa=True,
            has_js_rendering=True,
            framework="next",
            suggested_engine="playwright",
        )
        assert probe.is_spa is True
        assert probe.framework == "next"
        assert probe.suggested_engine == "playwright"


class TestJob:
    """Tests for Job schema."""
    
    def test_job_creation(self):
        job = Job(
            id="test-123",
            url="https://example.com",
            mode="mirror",
        )
        assert job.id == "test-123"
        assert job.status == JobStatus.PENDING
        assert job.probe is None
        assert job.error is None
        assert isinstance(job.created_at, datetime)
    
    def test_job_with_result(self):
        job = Job(
            id="test-456",
            url="https://example.com",
            mode="singlepage",
            status=JobStatus.COMPLETED,
            output_path="/output/test-456",
        )
        assert job.status == JobStatus.COMPLETED
        assert job.output_path == "/output/test-456"


class TestJobResult:
    """Tests for JobResult schema."""
    
    def test_result_creation(self):
        result = JobResult(
            job_id="test-789",
            output_path="/output/test-789",
            files_count=15,
            total_size_bytes=1024000,
            engine_used="wget",
            duration_seconds=45.2,
        )
        assert result.job_id == "test-789"
        assert result.files_count == 15
        assert result.engine_used == "wget"
