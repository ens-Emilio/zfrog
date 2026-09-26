"""Tests for the Celery dispatch payload contract.

The API hands a serialized JobCreate to the Celery task. A hand-maintained key
list there silently dropped fields (e.g. `pdf_filename`), so these tests pin the
round-trip: whatever JobCreate carries must survive dispatch.
"""

import inspect

from zfrog.api import create_job
from zfrog.models import JobCreate


def test_celery_dispatch_serializes_whole_job():
    """The dispatch call must spread the model dump, not enumerate fields."""
    source = inspect.getsource(create_job)

    assert 'job.model_dump(mode="json")' in source
    assert '"pdf_filename"' not in source


def test_job_create_round_trip_preserves_every_field():
    """Every JobCreate field must survive a model_dump → JobCreate round trip."""
    job = JobCreate(
        url="https://example.com",
        mode="pdf",
        max_depth=2,
        follow_links=False,
        respect_robots=False,
        delay_ms=250,
        jitter_ms=100,
        max_pages=7,
        max_bytes=1234,
        crawl_timeout_s=99,
        pdf_filename="relatorio-cliente",
    )

    payload = {"job_id": "job-1", **job.model_dump(mode="json")}
    restored = JobCreate(**{k: v for k, v in payload.items() if k != "job_id"})

    assert restored == job
    # Guards the reason this test exists: a crawl-budget field silently lost
    # during dispatch changes how much of a site gets downloaded.
    for field in ("delay_ms", "jitter_ms", "max_pages", "max_bytes", "crawl_timeout_s", "pdf_filename"):
        assert getattr(restored, field) == getattr(job, field)
