"""Local filesystem storage backend."""

from pathlib import Path

from zfrog.config import settings


def output_base(org: str | None = None) -> Path:
    """Base directory jobs of an organization are written under.

    With no org this is `settings.output_dir`, exactly as before organizations
    existed. With an org it is that organization's workspace, so its clones,
    versions and indexes stay separate from everyone else's.
    """
    if not org:
        return Path(settings.output_dir)

    from zfrog.workspaces import WorkspaceManager

    return WorkspaceManager().for_org(org).output_dir


def get_output_dir(job_id: str, org: str | None = None) -> Path:
    """Get the output directory for a job.
    
    Args:
        job_id: Unique job identifier.
        org: Organization that owns the job; None uses the shared output dir.
        
    Returns:
        Path to job output directory.
    """
    output_base_path = output_base(org) / job_id
    output_base_path.mkdir(parents=True, exist_ok=True)
    return output_base_path
