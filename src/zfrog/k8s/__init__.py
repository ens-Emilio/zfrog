"""Kubernetes integration: the ZfrogJob operator and its API client.

Public names are re-exported lazily so that `python -m zfrog.k8s.operator` (the
operator Deployment command) does not import the submodule twice.
"""

from __future__ import annotations

from typing import Any

_EXPORTS = (
    "K8sClient",
    "Operator",
    "api_base",
    "build_job_manifest",
    "child_job_name",
    "job_phase_to_cr_status",
    "load_token",
)

def __getattr__(name: str) -> Any:
    """Resolve the public names from `zfrog.k8s.operator` on first access."""
    if name in _EXPORTS:
        from zfrog.k8s import operator
        return getattr(operator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
