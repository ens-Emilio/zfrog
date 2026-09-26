"""Tests for organization-scoped data isolation.

The point of an organization is that its clones never mix with another's. These
tests pin the two places that decide where a job's data lands.
"""

from pathlib import Path

import pytest

from zfrog.config import settings
from zfrog.models import JobCreate
from zfrog.storage.local import get_output_dir, output_base


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")


def test_output_base_without_org_is_the_shared_dir():
    """No org keeps the pre-existing behaviour: jobs land in output/."""
    assert output_base() == settings.output_dir
    assert output_base(None) == settings.output_dir


def test_output_base_with_org_is_inside_that_workspace():
    base = output_base("acme")

    assert base != settings.output_dir
    assert "acme" in str(base)
    assert str(base).startswith(str(settings.output_dir))


def test_two_orgs_get_disjoint_job_directories():
    acme = get_output_dir("job-1", org="acme")
    globex = get_output_dir("job-1", org="globex")

    # Same job id, different orgs: different places.
    assert acme != globex
    assert "acme" in str(acme) and "globex" in str(globex)
    assert acme.is_dir() and globex.is_dir()

    # Writing into one is invisible from the other.
    (acme / "index.html").write_text("<html>acme</html>", encoding="utf-8")
    assert not (globex / "index.html").exists()


def test_org_slug_is_filesystem_safe():
    """An org name cannot be used to escape the output directory."""
    path = get_output_dir("job-1", org="Acme Corp")

    assert path.is_dir()
    assert "acme-corp" in str(path)
    assert str(path).startswith(str(settings.output_dir))


def test_job_create_carries_the_org():
    job = JobCreate(url="https://example.com", org="acme")

    assert job.org == "acme"
    # The field is optional so existing callers keep working unchanged.
    assert JobCreate(url="https://example.com").org is None


def test_traversal_in_org_is_refused():
    """A malicious org name must raise, not silently write elsewhere."""
    with pytest.raises(ValueError):
        get_output_dir("job-1", org="../../etc")
