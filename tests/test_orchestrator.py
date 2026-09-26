"""Tests for orchestrator."""

import pytest
import tempfile
from pathlib import Path

from zfrog.orchestrator import run_job, get_job, get_result, list_jobs
from zfrog.models import JobCreate, JobStatus


class TestOrchestrator:
    """Tests for orchestrator module."""
    
    @pytest.mark.asyncio
    async def test_run_singlepage_job(self, tmp_path):
        """Test running a singlepage job end-to-end."""
        # Override output directory
        from zfrog.config import settings
        original_output = settings.output_dir
        settings.output_dir = tmp_path / "output"
        
        try:
            job = JobCreate(
                url="https://example.com",
                mode="singlepage",
                max_depth=1,
            )
            
            result = await run_job(job)
            
            # Verify result
            assert result.job_id
            assert result.engine_used == "static_file"
            assert result.files_count >= 1
            assert result.total_size_bytes > 0
            assert result.duration_seconds > 0
            
            # Verify output file exists
            output_path = Path(result.output_path)
            assert output_path.exists()
            assert output_path.name == "archive.zip"
            
            # Verify job record
            job_record = get_job(result.job_id)
            assert job_record is not None
            assert job_record.status == JobStatus.COMPLETED
            assert job_record.probe is not None
            
        finally:
            settings.output_dir = original_output
    
    def test_get_job_nonexistent(self):
        """Test getting a nonexistent job."""
        assert get_job("nonexistent-id") is None
    
    def test_get_result_nonexistent(self):
        """Test getting a nonexistent result."""
        assert get_result("nonexistent-id") is None
    
    def test_list_jobs_empty(self):
        """Test listing jobs when none exist."""
        # This depends on state from previous tests
        jobs = list_jobs()
        assert isinstance(jobs, list)
